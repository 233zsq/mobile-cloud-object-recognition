"""Conservative, reversible decisions on untouched public photos only."""
import json
import math
import os
import random
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from datetime import datetime

import click
from werkzeug.exceptions import BadRequest, Conflict, Forbidden

from . import ai_review as ai
from .assets import PUBLIC_SOURCES

POLICY = 'strict-crosscheck-v1'
ACTIVE = 'd.sample_id=s.id AND d.applied_revision=s.revision AND d.after_status=s.status AND d.reverted_at IS NULL'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS ai_triage_settings(id INTEGER PRIMARY KEY CHECK(id=1),enabled INTEGER NOT NULL DEFAULT 0);
INSERT OR IGNORE INTO ai_triage_settings VALUES(1,0);
CREATE TABLE IF NOT EXISTS ai_triage_jobs(
 id TEXT PRIMARY KEY,actor INTEGER NOT NULL REFERENCES users(id),state TEXT NOT NULL,
 apply_changes INTEGER NOT NULL,limit_count INTEGER NOT NULL,profiles TEXT NOT NULL,
 processed INTEGER NOT NULL DEFAULT 0,pid INTEGER,report TEXT NOT NULL DEFAULT '{}',
 error_code TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS ai_triage_single_worker ON ai_triage_jobs((1)) WHERE state IN ('queued','running');
CREATE TABLE IF NOT EXISTS ai_auto_decisions(
 id TEXT PRIMARY KEY,sample_id TEXT NOT NULL REFERENCES samples(id),job_id TEXT NOT NULL REFERENCES ai_triage_jobs(id),
 policy TEXT NOT NULL,applied_revision INTEGER NOT NULL,after_status TEXT NOT NULL,before_values TEXT NOT NULL,
 evidence TEXT NOT NULL,audit_required INTEGER NOT NULL DEFAULT 1,reverted_at TEXT,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ai_auto_sample ON ai_auto_decisions(sample_id);
'''


def enabled(db):
    return bool(db.execute('SELECT enabled FROM ai_triage_settings WHERE id=1').fetchone()[0])


def administrator(db, actor):
    if not db.execute('SELECT 1 FROM users WHERE id=? AND role="admin" AND active=1', (actor,)).fetchone():
        raise Forbidden('严格分流需要有效管理员账号')


def log(db, actor, action, subject, details):
    db.execute('INSERT INTO events(actor,action,subject,details,created_at) VALUES(?,?,?,?,?)',
               (actor, action, subject, json.dumps(details, ensure_ascii=False), ai.stamp()))


def set_enabled(db, actor, value):
    db.execute('BEGIN IMMEDIATE')
    try:
        administrator(db, actor)
        db.execute('UPDATE ai_triage_settings SET enabled=? WHERE id=1', (int(value),))
        log(db, actor, 'ai_triage_enabled' if value else 'ai_triage_paused', POLICY, {'enabled': bool(value)})
        db.commit()
    except Exception:
        db.rollback(); raise


def profiles(primary):
    if primary not in ('qwen3.8-flash', 'qwen3-vl-plus-2025-12-19'):
        raise BadRequest('先选择已校验的视觉分流模型')
    return [ai.Profile(primary, 'campus-ai-review-v4'),
            ai.Profile('qwen3-vl-plus-2025-12-19', 'campus-ai-review-v3'),
            ai.Profile('qwen3-vl-plus-2025-12-19', 'campus-ai-review-v5')]


def candidate(result, category):
    """No self-reported confidence. Crop/quality/boundary cases always stay human."""
    if not result or result.get('bbox') is not None:
        return None
    decision, actual, flags = result.get('decision'), result.get('category_id'), result.get('flags')
    words = str(result.get('subject', '')) + ' ' + str(result.get('reason', ''))
    if re.search(r'疑似|可能|用途不明|不确定|无法确认|无法确定|主要主体之一', words):
        return None
    if decision == 'pass' and type(actual) is int and actual == category and flags == []:
        if re.search(r'人物|人群|人身|人体|由人|人背|人像|人脸|会议|街景|书架|整机|局部|扫描|包装|场景|截断|出画|切掉|未完整|主要物品之一|主体之一', words):
            return None
        return 'approved'
    if (decision == 'reject' and actual is None and isinstance(flags, list) and flags and
            set(flags) <= {'out_of_scope', 'illustration'}):
        return 'rejected'
    return None


def decide(results, category):
    choices = [candidate(result, category) for result in results]
    return choices[0] if len(choices) == 3 and choices[0] and len(set(choices)) == 1 else None


def untouched(db, row):
    return (row['source'] in PUBLIC_SOURCES and row['status'] == 'pending' and row['batch'] is None and
            row['revision'] == 1 and not row['crop'] and not row['reason'] and
            not db.execute('SELECT 1 FROM events WHERE subject=? AND action IN ("review","ai_auto_undo")', (row['id'],)).fetchone() and
            not db.execute('SELECT 1 FROM review_leases WHERE sample_id=? AND expires>?', (row['id'], time.time())).fetchone())


def current_decision(db, row):
    return db.execute('SELECT * FROM ai_auto_decisions WHERE sample_id=? AND applied_revision=? AND after_status=? AND reverted_at IS NULL',
                      (row['id'], row['revision'], row['status'])).fetchone()


def apply_decision(db, data, snapshot, categories, job, checks):
    """Recheck everything under the same writer lock as human leases/reviews."""
    db.execute('BEGIN IMMEDIATE')
    try:
        administrator(db, job['actor'])
        running = db.execute('SELECT state,apply_changes FROM ai_triage_jobs WHERE id=?', (job['id'],)).fetchone()
        if not running or running['state'] != 'running' or not running['apply_changes']:
            db.rollback(); return 'inactive_job'
        if not enabled(db):
            db.rollback(); return 'paused'
        row = db.execute('SELECT * FROM samples WHERE id=?', (snapshot['id'],)).fetchone()
        if (not row or not untouched(db, row) or any(row[name] != snapshot[name] for name in
                ('sha256', 'category', 'crop', 'revision', 'source'))):
            db.rollback(); return 'changed_or_claimed'
        path = (data / 'images' / row['filename']).resolve()
        if not path.is_relative_to((data / 'images').resolve()) or ai.digest(path.read_bytes()) != row['sha256']:
            db.rollback(); return 'photo_changed'
        # Only actual, validated ledger entries can authorize a write.
        results, actual_checks = [], []
        for check in checks:
            profile = ai.Profile(**check['profile'])
            identity = ai.cache_key(row, categories, profile)
            record = db.execute('SELECT state,result FROM ai_reviews WHERE cache_key=?', (identity,)).fetchone()
            if identity != check['cache_key'] or not record or record['state'] != 'done':
                db.rollback(); return 'evidence_changed'
            result = json.loads(record['result'])
            results.append(result)
            actual_checks.append({**check, 'suggestion': result})
        expected_profiles = json.loads(job['profiles'])
        if [check['profile'] for check in checks] != expected_profiles:
            db.rollback(); return 'evidence_changed'
        status = decide(results, row['category'])
        if status is None:
            db.rollback(); return 'manual'
        evidence = {'policy': POLICY, 'category_version': categories['category_version'],
                    'photo_sha256': row['sha256'], 'category_id': row['category'], 'crop': None, 'checks': actual_checks,
                    'same_provider_errors_may_be_correlated': True}
        identity = uuid.uuid4().hex
        before = {'status': row['status'], 'reason': row['reason']}
        reason = ('AI严格分流通过：三项交叉核验一致。' if status == 'approved' else
                  'AI严格分流拒绝：' + results[-1]['reason'][:130])
        db.execute('UPDATE samples SET status=?,reason=?,revision=revision+1 WHERE id=? AND revision=?',
                   (status, reason, row['id'], row['revision']))
        db.execute('DELETE FROM review_leases WHERE sample_id=?', (row['id'],))
        db.execute('INSERT INTO ai_auto_decisions(id,sample_id,job_id,policy,applied_revision,after_status,before_values,evidence,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                   (identity, row['id'], job['id'], POLICY, row['revision'] + 1, status, json.dumps(before), json.dumps(evidence, ensure_ascii=False), ai.stamp()))
        log(db, job['actor'], 'ai_auto_' + status, row['id'], {'automated': True, 'decision_id': identity,
            'policy': POLICY, 'job_id': job['id'], 'photo_sha256': row['sha256'], 'category': row['category'],
            'evidence_sha256': ai.digest(json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode())})
        db.commit()
        return status
    except Exception:
        db.rollback(); raise


def undo(db, actor, sid, revision):
    db.execute('BEGIN IMMEDIATE')
    try:
        administrator(db, actor)
        row = db.execute('SELECT * FROM samples WHERE id=?', (sid,)).fetchone()
        if not row or row['batch']:
            raise Conflict('照片不存在或已冻结，不能撤回')
        decision = current_decision(db, row)
        if not decision or str(row['revision']) != str(revision):
            raise Conflict('决定已被人工修改或撤回，请刷新')
        holder = db.execute('SELECT user_id FROM review_leases WHERE sample_id=? AND expires>?', (sid, time.time())).fetchone()
        if holder and holder[0] != actor:
            raise Conflict('其他成员正在复核，暂不能撤回')
        before = json.loads(decision['before_values'])
        db.execute('UPDATE samples SET status=?,reason=?,revision=revision+1 WHERE id=?', (before['status'], before['reason'], sid))
        db.execute('UPDATE ai_auto_decisions SET reverted_at=? WHERE id=?', (ai.stamp(), decision['id']))
        db.execute('DELETE FROM review_leases WHERE sample_id=?', (sid,))
        log(db, actor, 'ai_auto_undo', sid, {'decision_id': decision['id'], 'restored_status': before['status']})
        db.commit()
    except Exception:
        db.rollback(); raise


def summary(db):
    counts = dict(db.execute('SELECT d.after_status,COUNT(*) FROM ai_auto_decisions d JOIN samples s ON s.id=d.sample_id WHERE ' + ACTIVE + ' AND s.batch IS NULL GROUP BY d.after_status'))
    audits = db.execute('SELECT COUNT(*) FROM ai_auto_decisions d JOIN samples s ON s.id=d.sample_id WHERE ' + ACTIVE + ' AND d.audit_required=1 AND s.batch IS NULL').fetchone()[0]
    return {'enabled': enabled(db), 'counts': counts, 'audit_count': audits,
            'jobs': db.execute('SELECT * FROM ai_triage_jobs ORDER BY created_at DESC,rowid DESC LIMIT 5').fetchall()}


def pending_approval_audits(db):
    return db.execute('SELECT COUNT(*) FROM ai_auto_decisions d JOIN samples s ON s.id=d.sample_id WHERE ' + ACTIVE +
                      ' AND d.audit_required=1 AND s.status="approved" AND s.batch IS NULL').fetchone()[0]


def provenance(db, rows):
    return {row['id']: {'decision_id': record['id'], 'policy': record['policy'],
                      'evidence_sha256': ai.digest(record['evidence'].encode())}
            for row in rows if (record := current_decision(db, row))}


def recover_interrupted(db):
    for job in db.execute('SELECT * FROM ai_triage_jobs WHERE state IN ("queued","running")').fetchall():
        age = time.time() - datetime.fromisoformat(job['updated_at']).timestamp()
        if age < 120:
            continue
        process = Path('/proc') / str(job['pid'] or 0) / 'cmdline'
        if process.exists() and job['id'].encode() in process.read_bytes():
            continue
        db.execute('UPDATE ai_triage_jobs SET state="interrupted",error_code="worker_interrupted",updated_at=? WHERE id=? AND state IN ("queued","running")',
                   (ai.stamp(), job['id']))


def new_job(db, actor, limit, config, apply_changes=True):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise BadRequest('每批只能处理1到50张照片')
    administrator(db, actor)
    selected = profiles(config.get('REVIEW_TRIAGE_PRIMARY_MODEL', ai.MODEL))
    db.execute('BEGIN IMMEDIATE')
    try:
        recover_interrupted(db)
        if apply_changes and not enabled(db):
            raise Conflict('严格分流已暂停，请先开启')
        spent = ai.usage_totals(db)
        reservation = max(32000 * ai.MODEL_RATES[p.model][0] + 500 * ai.MODEL_RATES[p.model][1] for p in selected)
        if spent[2] + reservation > config['REVIEW_AI_BUDGET_NANO'] or spent[4] >= config['REVIEW_AI_MAX_CALLS']:
            raise Conflict('累计预算或调用次数已到上限，历史用量不会重置')
        identity, now = uuid.uuid4().hex, ai.stamp()
        db.execute('INSERT INTO ai_triage_jobs(id,actor,state,apply_changes,limit_count,profiles,created_at,updated_at) VALUES(?,?,"queued",?,?,?,?,?)',
                   (identity, actor, int(apply_changes), limit, json.dumps([p.__dict__ for p in selected]), now, now))
        log(db, actor, 'ai_triage_started', identity, {'limit': limit, 'apply_changes': bool(apply_changes), 'policy': POLICY})
        db.commit()
        return identity
    except sqlite3.IntegrityError:
        db.rollback(); raise Conflict('已有一个分流任务，请等待完成') from None
    except Exception:
        db.rollback(); raise


def launch(app, identity):
    data = app.extensions['review_data']
    directory = data / 'triage-jobs'; directory.mkdir(exist_ok=True, mode=0o700)
    descriptor = os.open(directory / (identity + '.log'), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        return subprocess.Popen([sys.executable, '-m', 'flask', '--app', 'wsgi', 'ai-triage-worker', '--job', identity],
                                cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL, stdout=stream,
                                stderr=subprocess.STDOUT, start_new_session=True).pid


def audit_sample(db, job_id):
    # All automatic decisions require audit until the job finishes. Interrupted
    # jobs keep that stricter default. Choose >=10%, at least one per outcome.
    for status in ('approved', 'rejected'):
        rows = db.execute('SELECT id FROM ai_auto_decisions WHERE job_id=? AND after_status=? ORDER BY id', (job_id, status)).fetchall()
        if not rows:
            continue
        chosen = {row[0] for row in sorted(rows, key=lambda r: ai.digest((job_id + r[0]).encode()))[:max(1, math.ceil(len(rows) * .1))]}
        db.executemany('UPDATE ai_auto_decisions SET audit_required=? WHERE id=?', [(int(row[0] in chosen), row[0]) for row in rows])


def run_job(db, data, categories, config, identity, analyze=ai.analyze):
    db.execute('BEGIN IMMEDIATE')
    job = db.execute('SELECT * FROM ai_triage_jobs WHERE id=?', (identity,)).fetchone()
    if not job or job['state'] != 'queued':
        db.rollback(); raise Conflict('任务不存在或已经运行')
    db.execute('UPDATE ai_triage_jobs SET state="running",pid=?,updated_at=? WHERE id=?', (os.getpid(), ai.stamp(), identity)); db.commit()
    report = {'job_id': identity, 'policy': POLICY, 'apply_changes': bool(job['apply_changes']), 'samples': [], 'counts': {}, 'errors': {}}
    before_usage = ai.usage_totals(db)
    state, error_code = 'done', ''
    try:
        administrator(db, job['actor'])
        key = ai.read_key(config)
        chosen_profiles = [ai.Profile(**p) for p in json.loads(job['profiles'])]
        rows = [dict(r) for r in db.execute('SELECT * FROM samples ORDER BY id').fetchall() if untouched(db, r)]
        random.Random(42).shuffle(rows)
        groups = {}
        for row in rows:
            groups.setdefault(row['category'], []).append(row)
        rows = []
        while len(rows) < job['limit_count'] and any(groups.values()):
            for category in sorted(groups):
                if groups[category] and len(rows) < job['limit_count']:
                    rows.append(groups[category].pop())
        for row in rows:
            if job['apply_changes'] and not enabled(db):
                state, error_code = 'stopped', 'paused'; break
            checks, suggestions = [], []
            outcome = 'manual'
            for profile in chosen_profiles:
                status, result = analyze(db, data, row, categories, config, key, profile=profile)
                cache_identity = ai.cache_key(row, categories, profile)
                if status != 'done':
                    record = db.execute('SELECT error_code FROM ai_reviews WHERE cache_key=?', (cache_identity,)).fetchone()
                    fault = record[0] if record and record[0] else 'reserved_or_unavailable'
                    report['errors'][fault] = report['errors'].get(fault, 0) + 1
                    if fault not in ('invalid_suggestion', 'reserved_or_unavailable'):
                        state, error_code = 'stopped', fault
                    break
                checks.append({'profile': profile.__dict__, 'cache_key': cache_identity, 'suggestion': result,
                               'alias_cache_generation': ai.ALIAS_GENERATIONS.get(profile.model)})
                suggestions.append(result)
                choice = candidate(result, row['category'])
                if choice is None or (len(suggestions) > 1 and choice != candidate(suggestions[0], row['category'])):
                    break
            if decide(suggestions, row['category']):
                outcome = (apply_decision(db, data, row, categories, job, checks) if job['apply_changes'] else
                           'would_' + decide(suggestions, row['category']))
            report['samples'].append({'sample_id': row['id'], 'category_id': row['category'], 'outcome': outcome, 'checks': checks})
            report['counts'][outcome] = report['counts'].get(outcome, 0) + 1
            db.execute('UPDATE ai_triage_jobs SET processed=?,report=?,updated_at=? WHERE id=?',
                       (len(report['samples']), json.dumps(report, ensure_ascii=False), ai.stamp(), identity))
            if state == 'stopped':
                break
    except ai.ReviewError as error:
        state, error_code = 'stopped', str(error)
    except Exception:
        if db.in_transaction:
            db.rollback()
        state, error_code = 'error', 'internal_error'
    finally:
        usage = ai.usage_totals(db)
        report.update(state=state, error_code=error_code, usage=ai.usage_report(usage),
                      run_usage=ai.usage_report(tuple(a - b for a, b in zip(usage, before_usage))),
                      automatic_decisions_are_not_ground_truth=True)
        db.execute('BEGIN IMMEDIATE')
        try:
            audit_sample(db, identity)
            db.execute('UPDATE ai_triage_jobs SET state=?,report=?,error_code=?,updated_at=? WHERE id=?',
                       (state, json.dumps(report, ensure_ascii=False), error_code, ai.stamp(), identity))
            log(db, job['actor'], 'ai_triage_finished', identity, {'state': state, 'counts': report['counts'], 'error_code': error_code})
            db.commit()
        except Exception:
            db.rollback(); raise
    return report


def register(app, get_db, data, categories):
    @app.cli.command('ai-triage-worker')
    @click.option('--job', required=True)
    def worker(job):
        if not re.fullmatch('[0-9a-f]{32}', job):
            raise click.ClickException('invalid_job_id')
        report = run_job(get_db(), data, categories, app.config, job)
        click.echo(json.dumps({key: value for key, value in report.items() if key != 'samples'}, ensure_ascii=False))
        if report['state'] != 'done':
            raise click.ClickException('triage_' + report['error_code'])

    @app.cli.command('ai-triage')
    @click.option('--actor', type=int, required=True)
    @click.option('--limit', type=click.IntRange(1, 50), default=20)
    @click.option('--apply', 'apply_changes', is_flag=True)
    def triage(actor, limit, apply_changes):
        identity = new_job(get_db(), actor, limit, app.config, apply_changes)
        report = run_job(get_db(), data, categories, app.config, identity)
        click.echo(json.dumps({key: value for key, value in report.items() if key != 'samples'}, ensure_ascii=False))
        if report['state'] != 'done':
            raise click.ClickException('triage_' + report['error_code'])

    @app.cli.command('ai-triage-policy')
    @click.option('--actor', type=int, required=True)
    @click.option('--enabled', 'value', type=bool, required=True)
    def policy(actor, value):
        set_enabled(get_db(), actor, value)
        click.echo(json.dumps({'enabled': value, 'policy': POLICY}))
