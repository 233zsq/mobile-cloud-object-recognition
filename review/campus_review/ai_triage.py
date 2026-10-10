"""Versioned, reversible AI decisions on untouched public photos only."""
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
import csv
import io
import zipfile
from werkzeug.exceptions import BadRequest, Conflict, Forbidden

from . import ai_review as ai
from .assets import PUBLIC_SOURCES

POLICY = 'strict-crosscheck-v2'
MAX_POLICY = 'max-direct-v1'
MAX_MODEL = 'qwen3.8-max-0902'
CASCADE_POLICY = 'flash-max-cascade-v1'
FLASH_MODEL = 'qwen3.8-flash'
# No pilot references yet for chargers/keys. Do not freeze their automatic
# approvals without reviewing every one, even when all models agree.
FULL_APPROVAL_AUDIT_CATEGORIES = (7, 8)
ACTIVE = 'd.sample_id=s.id AND d.applied_revision=s.revision AND d.after_status=s.status AND d.reverted_at IS NULL'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS ai_triage_settings(id INTEGER PRIMARY KEY CHECK(id=1),enabled INTEGER NOT NULL DEFAULT 0);
INSERT OR IGNORE INTO ai_triage_settings VALUES(1,0);
CREATE TABLE IF NOT EXISTS ai_triage_jobs(
 id TEXT PRIMARY KEY,actor INTEGER NOT NULL REFERENCES users(id),state TEXT NOT NULL,
 apply_changes INTEGER NOT NULL,limit_count INTEGER NOT NULL,profiles TEXT NOT NULL,
 audit_percent INTEGER NOT NULL DEFAULT 10,
 policy TEXT NOT NULL DEFAULT 'strict-crosscheck-v2',
 processed INTEGER NOT NULL DEFAULT 0,pid INTEGER,report TEXT NOT NULL DEFAULT '{}',
 error_code TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS ai_triage_single_worker ON ai_triage_jobs((1)) WHERE state IN ('queued','running');
CREATE TABLE IF NOT EXISTS ai_auto_decisions(
 id TEXT PRIMARY KEY,sample_id TEXT NOT NULL REFERENCES samples(id),job_id TEXT NOT NULL REFERENCES ai_triage_jobs(id),
 policy TEXT NOT NULL,applied_revision INTEGER NOT NULL,after_status TEXT NOT NULL,before_values TEXT NOT NULL,
 evidence TEXT NOT NULL,audit_required INTEGER NOT NULL DEFAULT 1,reverted_at TEXT,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ai_auto_sample ON ai_auto_decisions(sample_id);
CREATE TABLE IF NOT EXISTS ai_triage_seen(
 identity TEXT PRIMARY KEY,sample_id TEXT NOT NULL REFERENCES samples(id),policy TEXT NOT NULL,
 job_id TEXT NOT NULL REFERENCES ai_triage_jobs(id),created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ai_triage_routes(
 sample_id TEXT PRIMARY KEY REFERENCES samples(id),revision INTEGER NOT NULL,photo_sha256 TEXT NOT NULL,
 category INTEGER NOT NULL,context TEXT NOT NULL,job_id TEXT NOT NULL REFERENCES ai_triage_jobs(id),
 state TEXT NOT NULL CHECK(state IN ('manual','error')),reason_code TEXT NOT NULL,created_at TEXT NOT NULL);
'''


def migrate(db):
    if 'audit_percent' not in {row[1] for row in db.execute('PRAGMA table_info(ai_triage_jobs)')}:
        db.execute("ALTER TABLE ai_triage_jobs ADD COLUMN audit_percent INTEGER NOT NULL DEFAULT 10")
    if 'policy' not in {row[1] for row in db.execute('PRAGMA table_info(ai_triage_jobs)')}:
        # Historical jobs retain their historical rules after a model switch.
        db.execute("ALTER TABLE ai_triage_jobs ADD COLUMN policy TEXT NOT NULL DEFAULT 'strict-crosscheck-v2'")
        if 'report' in {row[1] for row in db.execute('PRAGMA table_info(ai_triage_jobs)')}:
            db.execute("UPDATE ai_triage_jobs SET policy=json_extract(report,'$.policy') "
                       "WHERE json_valid(report) AND json_type(report,'$.policy')='text'")


def enabled(db):
    return bool(db.execute('SELECT enabled FROM ai_triage_settings WHERE id=1').fetchone()[0])


def administrator(db, actor):
    if not db.execute('SELECT 1 FROM users WHERE id=? AND role="admin" AND active=1', (actor,)).fetchone():
        raise Forbidden('严格分流需要有效管理员账号')


def log(db, actor, action, subject, details):
    db.execute('INSERT INTO events(actor,action,subject,details,created_at) VALUES(?,?,?,?,?)',
               (actor, action, subject, json.dumps(details, ensure_ascii=False), ai.stamp()))


def set_enabled(db, actor, value, policy=None):
    db.execute('BEGIN IMMEDIATE')
    try:
        administrator(db, actor)
        db.execute('UPDATE ai_triage_settings SET enabled=? WHERE id=1', (int(value),))
        log(db, actor, 'ai_triage_enabled' if value else 'ai_triage_paused', policy or POLICY, {'enabled': bool(value)})
        db.commit()
    except Exception:
        db.rollback(); raise


def profiles(primary, policy=None):
    if policy == CASCADE_POLICY:
        if primary != FLASH_MODEL:
            raise BadRequest('Flash优先策略需要选择Qwen3.8-Flash')
        return [ai.Profile(FLASH_MODEL, 'campus-ai-review-v6'), ai.Profile(MAX_MODEL, 'campus-ai-review-v6')]
    if policy not in (None, '', POLICY, MAX_POLICY):
        raise BadRequest('未知的自动审核策略')
    if policy == MAX_POLICY and primary != MAX_MODEL or policy == POLICY and primary == MAX_MODEL:
        raise BadRequest('审核策略与模型不匹配')
    if primary == MAX_MODEL:
        return [ai.Profile(MAX_MODEL, 'campus-ai-review-v6')]
    if primary not in ('qwen3.8-flash', 'qwen3-vl-plus-2025-12-19'):
        raise BadRequest('先选择已校验的视觉分流模型')
    return [ai.Profile(primary, 'campus-ai-review-v4'),
            ai.Profile('qwen3-vl-plus-2025-12-19', 'campus-ai-review-v3'),
            ai.Profile('qwen3-vl-plus-2025-12-19', 'campus-ai-review-v5')]


def policy_for(selected):
    if selected == profiles(FLASH_MODEL, CASCADE_POLICY):
        return CASCADE_POLICY
    return MAX_POLICY if selected == [ai.Profile(MAX_MODEL, 'campus-ai-review-v6')] else POLICY


def configured_profiles(config):
    return profiles(config.get('REVIEW_TRIAGE_PRIMARY_MODEL', FLASH_MODEL), config.get('REVIEW_TRIAGE_POLICY'))


def routing_context(categories, selected):
    """Invalidate a routing result when labels, prompts or model generations change."""
    return ai.digest(json.dumps([categories, [{**p.__dict__, 'inference': ai.inference(p),
        'alias_generation': ai.ALIAS_GENERATIONS.get(p.model)} for p in selected]],
        sort_keys=True, ensure_ascii=False).encode())


def candidate(result, category, policy=None):
    """No self-reported confidence; crops and uncertain labels stay human."""
    if not result or result.get('bbox') is not None:
        return None
    decision, actual, flags = result.get('decision'), result.get('category_id'), result.get('flags')
    if policy in (MAX_POLICY, CASCADE_POLICY):
        if policy == CASCADE_POLICY and re.search(r'疑似|可能|用途不明|不确定|无法确认|无法确定',
                                                  str(result.get('subject', '')) + ' ' + str(result.get('reason', ''))):
            return None
        # Trust the validated primary decision, not consensus or keyword votes.
        # Valid in-scope photos carrying a different label still need relabelling.
        if decision == 'pass' and type(actual) is int and actual == category and flags == []:
            return 'approved'
        if (decision == 'reject' and (actual is None or type(actual) is int and actual == category) and
                isinstance(flags, list) and flags and set(flags) <= ai.FLAGS):
            return 'rejected'
        return None
    words = str(result.get('subject', '')) + ' ' + str(result.get('reason', ''))
    if re.search(r'疑似|可能|用途不明|不确定|无法确认|无法确定|主要主体之一', words):
        return None
    if decision == 'pass' and type(actual) is int and actual == category and flags == []:
        if re.search(r'人物|人群|人身|人体|由人|人背|人像|人脸|会议|街景|书架|整机|局部|扫描|包装|场景|截断|出画|切掉|未完整|大量|密集|数量多|成排|多种|电子设备|主要物品之一|主体之一', words):
            return None
        return 'approved'
    if (decision == 'reject' and actual is None and isinstance(flags, list) and flags and
            set(flags) <= {'out_of_scope', 'illustration'}):
        return 'rejected'
    return None


def needs_max(result, category):
    """Only unresolved judgments escalate; edits and wrong labels stay human."""
    return (result.get('bbox') is None and result.get('decision') != 'crop' and
            (result.get('category_id') is None or type(result.get('category_id')) is int and result['category_id'] == category) and
            candidate(result, category, CASCADE_POLICY) is None)


def decide(results, category, policy=None):
    if policy == CASCADE_POLICY:
        if len(results) == 1:
            return candidate(results[0], category, policy)
        if len(results) == 2 and needs_max(results[0], category):
            return candidate(results[1], category, policy)
        return None
    choices = [candidate(result, category, policy) for result in results]
    required = 1 if policy == MAX_POLICY else 3
    return choices[0] if len(choices) == required and choices[0] and len(set(choices)) == 1 else None


def selection_identity(row, categories, selected):
    return ai.digest(json.dumps([policy_for(selected), row['revision'], [ai.cache_key(row, categories, p) for p in selected]]).encode())


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
        running = db.execute('SELECT * FROM ai_triage_jobs WHERE id=?', (job['id'],)).fetchone()
        if not running or running['state'] != 'running' or not running['apply_changes']:
            db.rollback(); return 'inactive_job'
        if any(running[name] != job[name] for name in ('policy', 'profiles', 'actor')):
            db.rollback(); return 'evidence_changed'
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
        policy = job['policy']
        used_profiles = [check['profile'] for check in checks]
        if (used_profiles != (expected_profiles[:len(checks)] if policy == CASCADE_POLICY else expected_profiles) or
                not checks):
            db.rollback(); return 'evidence_changed'
        status = decide(results, row['category'], policy)
        if status is None:
            db.rollback(); return 'manual'
        evidence = {'policy': policy, 'category_version': categories['category_version'],
                    'photo_sha256': row['sha256'], 'category_id': row['category'], 'crop': None, 'checks': actual_checks,
                    'same_provider_errors_may_be_correlated': True}
        identity = uuid.uuid4().hex
        before = {'status': row['status'], 'reason': row['reason']}
        reason = ('AI ' + ('Flash' if len(checks) == 1 else 'Max复核') + '自动审核：' + results[-1]['reason'][:130] if policy == CASCADE_POLICY else
                  'AI Max自动审核：' + results[-1]['reason'][:130] if policy == MAX_POLICY else
                  'AI严格分流通过：三项交叉核验一致。' if status == 'approved' else
                  'AI严格分流拒绝：' + results[-1]['reason'][:130])
        db.execute('UPDATE samples SET status=?,reason=?,revision=revision+1 WHERE id=? AND revision=?',
                   (status, reason, row['id'], row['revision']))
        db.execute('DELETE FROM review_leases WHERE sample_id=?', (row['id'],))
        db.execute('INSERT INTO ai_auto_decisions(id,sample_id,job_id,policy,applied_revision,after_status,before_values,evidence,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                   (identity, row['id'], job['id'], policy, row['revision'] + 1, status, json.dumps(before), json.dumps(evidence, ensure_ascii=False), ai.stamp()))
        log(db, job['actor'], 'ai_auto_' + status, row['id'], {'automated': True, 'decision_id': identity,
            'policy': policy, 'job_id': job['id'], 'photo_sha256': row['sha256'], 'category': row['category'],
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


def summary(db, primary=FLASH_MODEL, policy=None):
    counts = dict(db.execute('SELECT d.after_status,COUNT(*) FROM ai_auto_decisions d JOIN samples s ON s.id=d.sample_id WHERE ' + ACTIVE + ' AND s.batch IS NULL GROUP BY d.after_status'))
    audits = db.execute('SELECT COUNT(*) FROM ai_auto_decisions d JOIN samples s ON s.id=d.sample_id WHERE ' + ACTIVE + ' AND d.audit_required=1 AND s.batch IS NULL').fetchone()[0]
    jobs = [{**dict(row), 'counts': json.loads(row['report']).get('counts', {}),
             'routing': json.loads(row['report']).get('routing', {})}
            for row in db.execute('SELECT * FROM ai_triage_jobs ORDER BY created_at DESC,rowid DESC LIMIT 5')]
    return {'enabled': enabled(db), 'counts': counts, 'audit_count': audits,
            'primary_model': primary, 'max_direct': primary == MAX_MODEL,
            'cascade': policy == CASCADE_POLICY, 'policy': policy_for(profiles(primary, policy)),
            'jobs': jobs}


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
    selected = configured_profiles(config)
    policy = policy_for(selected)
    audit_percent = config.get('REVIEW_AI_AUDIT_PERCENT', 5)
    if type(audit_percent) is not int or not 1 <= audit_percent <= 100:
        raise BadRequest('抽检比例必须为1到100的整数百分比')
    db.execute('BEGIN IMMEDIATE')
    try:
        recover_interrupted(db)
        if apply_changes and not enabled(db):
            raise Conflict('自动审核已暂停，请先开启')
        spent = ai.usage_totals(db)
        reservation = (ai.reservation_for(selected[0]) if policy == CASCADE_POLICY else
                       max(ai.reservation_for(p) for p in selected))
        if spent[2] + reservation > config['REVIEW_AI_BUDGET_NANO'] or spent[4] >= config['REVIEW_AI_MAX_CALLS']:
            raise Conflict('累计预算或调用次数已到上限，历史用量不会重置')
        identity, now = uuid.uuid4().hex, ai.stamp()
        db.execute('INSERT INTO ai_triage_jobs(id,actor,state,apply_changes,limit_count,profiles,policy,audit_percent,created_at,updated_at) VALUES(?,?,"queued",?,?,?,?,?,?,?)',
                   (identity, actor, int(apply_changes), limit, json.dumps([p.__dict__ for p in selected]), policy, audit_percent, now, now))
        log(db, actor, 'ai_triage_started', identity, {'limit': limit, 'apply_changes': bool(apply_changes), 'policy': policy})
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
    # jobs keep that stricter default. Historical jobs retain their pinned rate.
    job = db.execute('SELECT policy,audit_percent FROM ai_triage_jobs WHERE id=?', (job_id,)).fetchone()
    policy, fraction = job['policy'], job['audit_percent'] / 100
    for status in ('approved', 'rejected'):
        rows = db.execute('SELECT d.id,s.category FROM ai_auto_decisions d JOIN samples s ON s.id=d.sample_id WHERE d.job_id=? AND d.after_status=? ORDER BY d.id', (job_id, status)).fetchall()
        if not rows:
            continue
        chosen = {row[0] for row in sorted(rows, key=lambda r: ai.digest((job_id + r[0]).encode()))[:max(1, math.ceil(len(rows) * fraction))]}
        if status == 'approved' and policy not in (MAX_POLICY, CASCADE_POLICY):
            chosen.update(row['id'] for row in rows if row['category'] in FULL_APPROVAL_AUDIT_CATEGORIES)
        db.executemany('UPDATE ai_auto_decisions SET audit_required=? WHERE id=?', [(int(row[0] in chosen), row[0]) for row in rows])


def run_job(db, data, categories, config, identity, analyze=ai.analyze, *, sample_ids=None):
    if sample_ids is not None:
        if not isinstance(sample_ids, (list, tuple, set)) or not 1 <= len(sample_ids) <= 2000 or any(not isinstance(s, str) for s in sample_ids):
            raise ValueError('A bounded sample scope is required')
        sample_ids = set(sample_ids)
    db.execute('BEGIN IMMEDIATE')
    job = db.execute('SELECT * FROM ai_triage_jobs WHERE id=?', (identity,)).fetchone()
    if not job or job['state'] != 'queued':
        db.rollback(); raise Conflict('任务不存在或已经运行')
    db.execute('UPDATE ai_triage_jobs SET state="running",pid=?,updated_at=? WHERE id=?', (os.getpid(), ai.stamp(), identity)); db.commit()
    policy = job['policy']
    report = {'job_id': identity, 'policy': policy, 'audit_percent': job['audit_percent'],
              'apply_changes': bool(job['apply_changes']), 'samples': [], 'counts': {}, 'errors': {}, 'routing': {}}
    if sample_ids is not None:
        report['sample_scope_sha256'] = ai.digest(json.dumps(sorted(sample_ids)).encode())
    before_usage = ai.usage_totals(db)
    identities, selected_usage_before = [], (0, 0, 0, 0, 0)
    state, error_code = 'done', ''
    try:
        administrator(db, job['actor'])
        key = ai.read_key(config)
        chosen_profiles = [ai.Profile(**p) for p in json.loads(job['profiles'])]
        if (policy_for(chosen_profiles) != policy or
                chosen_profiles != profiles(chosen_profiles[0].model, CASCADE_POLICY if policy == CASCADE_POLICY else None)):
            raise ai.ReviewError('job_policy_profile_mismatch')
        seen = {r[0] for r in db.execute('SELECT identity FROM ai_triage_seen')}
        rows = [dict(r) for r in db.execute('SELECT * FROM samples ORDER BY id').fetchall()
                if (sample_ids is None or r['id'] in sample_ids) and untouched(db, r) and selection_identity(r, categories, chosen_profiles) not in seen]
        random.Random(42).shuffle(rows)
        groups = {}
        for row in rows:
            groups.setdefault(row['category'], []).append(row)
        rows = []
        while len(rows) < job['limit_count'] and any(groups.values()):
            for category in sorted(groups):
                if groups[category] and len(rows) < job['limit_count']:
                    rows.append(groups[category].pop())
        identities = [ai.cache_key(row, categories, profile) for row in rows for profile in chosen_profiles]
        selected_usage_before = ai.usage_totals(db, identities)
        for row in rows:
            if job['apply_changes'] and not enabled(db):
                state, error_code = 'stopped', 'paused'; break
            checks, suggestions = [], []
            outcome, fault = 'manual', ''
            for profile in chosen_profiles:
                if policy == CASCADE_POLICY and profile.model == MAX_MODEL:
                    report['routing']['max_reviews'] = report['routing'].get('max_reviews', 0) + 1
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
                               'inference': ai.inference(profile),
                               'alias_cache_generation': ai.ALIAS_GENERATIONS.get(profile.model)})
                suggestions.append(result)
                if policy == CASCADE_POLICY:
                    if len(suggestions) == 1 and needs_max(result, row['category']):
                        continue
                    if len(suggestions) == 1 and candidate(result, row['category'], policy):
                        report['routing']['flash_direct'] = report['routing'].get('flash_direct', 0) + 1
                    break
                choice = candidate(result, row['category'], policy)
                if choice is None or (len(suggestions) > 1 and choice != candidate(suggestions[0], row['category'], policy)):
                    break
            if decide(suggestions, row['category'], policy):
                outcome = (apply_decision(db, data, row, categories, job, checks) if job['apply_changes'] else
                           'would_' + decide(suggestions, row['category'], policy))
            elif fault:
                outcome = 'ai_error'
            report['samples'].append({'sample_id': row['id'], 'category_id': row['category'], 'outcome': outcome, 'checks': checks})
            report['counts'][outcome] = report['counts'].get(outcome, 0) + 1
            db.execute('BEGIN IMMEDIATE')
            try:
                db.execute('UPDATE ai_triage_jobs SET processed=?,report=?,updated_at=? WHERE id=?',
                           (len(report['samples']), json.dumps(report, ensure_ascii=False), ai.stamp(), identity))
                if job['apply_changes'] and outcome in ('manual', 'ai_error'):
                    current = db.execute('SELECT * FROM samples WHERE id=?', (row['id'],)).fetchone()
                    if (current and untouched(db, current) and all(current[k] == row[k] for k in ('revision', 'sha256', 'category', 'crop'))):
                        db.execute('INSERT OR REPLACE INTO ai_triage_routes VALUES(?,?,?,?,?,?,?,?,?)',
                            (row['id'], row['revision'], row['sha256'], row['category'], routing_context(categories, chosen_profiles),
                             identity, 'error' if outcome == 'ai_error' else 'manual',
                             fault or (suggestions[-1]['decision'] if suggestions else 'uncertain'), ai.stamp()))
                if job['apply_changes'] and state != 'stopped' and outcome in ('approved', 'rejected', 'manual', 'ai_error'):
                    db.execute('INSERT OR IGNORE INTO ai_triage_seen VALUES(?,?,?,?,?)',
                               (selection_identity(row, categories, chosen_profiles), row['id'], policy, identity, ai.stamp()))
                db.commit()
            except Exception:
                db.rollback(); raise
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
                      run_usage=ai.usage_report(tuple(a - b for a, b in zip(ai.usage_totals(db, identities), selected_usage_before))),
                      run_usage_basis='selected_inputs_ledger_delta',
                      ledger_window_usage=ai.usage_report(tuple(a - b for a, b in zip(usage, before_usage))),
                      automatic_decisions_are_not_ground_truth=True)
        db.execute('BEGIN IMMEDIATE')
        try:
            if state == 'done':
                audit_sample(db, identity)
            db.execute('UPDATE ai_triage_jobs SET state=?,report=?,error_code=?,updated_at=? WHERE id=?',
                       (state, json.dumps(report, ensure_ascii=False), error_code, ai.stamp(), identity))
            log(db, job['actor'], 'ai_triage_finished', identity, {'state': state, 'counts': report['counts'], 'error_code': error_code})
            db.commit()
        except Exception:
            db.rollback(); raise
    return report


def register(app, get_db, data, categories):
    @app.cli.command('ai-triage-round')
    @click.option('--actor', type=int, required=True)
    @click.option('--archive', type=click.Path(exists=True, path_type=Path), required=True)
    @click.option('--max-photos', type=click.IntRange(1, 2000), default=500)
    @click.option('--progress', type=click.Path(path_type=Path), required=True)
    def triage_round(actor, archive, max_photos, progress):
        """One finite, explicitly scoped round; each job remains <=50 photos."""
        db = get_db()
        administrator(db, actor)
        if progress.exists() or not progress.resolve().is_relative_to(data.resolve()):
            raise click.ClickException('Use a new progress file inside the private review data directory')
        with zipfile.ZipFile(archive) as package:
            if package.getinfo('samples.csv').file_size > 8 * 1024**2 or package.getinfo('queue.json').file_size > 2 * 1024**2:
                raise click.ClickException('Oversize public queue manifest')
            receipt=json.loads(package.read('queue.json'))
            raw=package.read('samples.csv')
            if receipt.get('purpose') != 'public_review_queue' or ai.digest(raw) != receipt['files']['samples.csv']:
                raise click.ClickException('Public queue identity differs')
            rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
        if not 1 <= len(rows) <= 2000 or len(rows) != receipt['count']:
            raise click.ClickException('Round needs 1..2000 candidate photos')
        scope=[]
        for row in rows:
            current=db.execute('SELECT id,category,source_meta FROM samples WHERE sha256=?', (row['image_sha256'],)).fetchone()
            if current and str(current['category']) == row['category_id'] and json.loads(current['source_meta']).get('sample_id') == row['sample_id']:
                scope.append(current['id'])
        if not scope:
            raise click.ClickException('Import this public queue before starting its round')
        result={'state':'running','photo_limit':max_photos,'scope_count':len(scope),'processed':0,'counts':{},'jobs':[],
                'started_at':ai.stamp(),'sample_scope_sha256':ai.digest(json.dumps(sorted(scope)).encode())}
        def save():
            result['updated_at']=ai.stamp()
            temporary=progress.with_suffix('.new')
            descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(descriptor,'w') as stream:
                json.dump(result,stream,ensure_ascii=False,indent=2); stream.flush(); os.fsync(stream.fileno())
            temporary.replace(progress)
        save()
        try:
            while result['processed'] < min(max_photos,len(scope)):
                identity=new_job(db,actor,min(50,max_photos-result['processed']),app.config,True)
                report=run_job(db,data,categories,app.config,identity,sample_ids=scope)
                result['jobs'].append(identity)
                result['processed']+=len(report['samples'])
                for key,value in report['counts'].items(): result['counts'][key]=result['counts'].get(key,0)+value
                save()
                if report['state'] != 'done':
                    result.update(state='stopped',error_code=report['error_code']); break
                if not report['samples']:
                    result['state']='scope_exhausted'; break
            else:
                result['state']='done'
        except Exception as error:
            result.update(state='stopped',error_code=type(error).__name__)
        finally:
            result['usage']=ai.usage_report(ai.usage_totals(db)); save()
        click.echo(json.dumps(result,ensure_ascii=False))
        if result['state']=='stopped':
            raise click.ClickException('round_stopped_'+result['error_code'])

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
        active = policy_for(configured_profiles(app.config))
        set_enabled(get_db(), actor, value, active)
        click.echo(json.dumps({'enabled': value, 'policy': active}))
