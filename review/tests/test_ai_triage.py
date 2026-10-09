"""Actual SQLite/HTTP triage writes, leases, budgets and manual overrides."""
import json
import time
from pathlib import Path

import pytest
from werkzeug.exceptions import Conflict

from test_review import admin, app, csrf, review_body, upload
from test_workflow import connect, member
from test_ai_review import answer, categories, public_sample
from campus_review import ai_review as ai, ai_triage as triage


def prepare(app, owner):
    row = public_sample(app, owner)
    app.config.update(REVIEW_TRIAGE_PRIMARY_MODEL='qwen3.8-flash', REVIEW_AI_BUDGET_NANO=30_000_000_000,
                      REVIEW_AI_MAX_CALLS=5000)
    with connect(app) as db:
        db.isolation_level = None
        uid = db.execute('SELECT id FROM users WHERE role="admin"').fetchone()[0]
        triage.set_enabled(db, uid, True)
    return row, uid


def transport(result=None):
    return lambda key, text, photo: (result or answer(), [300, 80], len(photo))


def execute(app, uid, result=None, apply=True, limit=50, analyze=None):
    with connect(app) as db:
        db.isolation_level = None
        identity = triage.new_job(db, uid, limit, app.config, apply)
        return triage.run_job(db, Path(app.config['DATA_DIR']), categories(), app.config, identity,
                             analyze or (lambda *args, **kwargs: ai.analyze(*args, api=transport(result), **kwargs)))


@pytest.mark.parametrize('change', [
    {'bbox': [0, 0, 9000, 9000]}, {'flags': ['multiple_subjects']}, {'category_id': 1},
    {'subject': '会议室里的鼠标'}, {'reason': '可能是杯子'}, {'reason': '一个主要主体之一'},
    {'reason': '虽有部分人体遮挡但背包可辨认'}, {'subject': '由人背负使用的背包'},
    {'decision': 'crop'}, {'decision': 'uncertain'},
    {'decision': 'reject', 'category_id': None, 'flags': ['occluded']},
    {'decision': 'reject', 'category_id': None, 'flags': ['too_small', 'out_of_scope']},
])
def test_consensus_never_promotes_boundary_crops_quality_or_disagreement(change):
    good = json.loads(answer())
    assert triage.decide([good, good, good], 0) == 'approved'
    other = {**good, **change}
    assert triage.decide([other, other, other], 0) is None
    assert triage.decide([good, good, other], 0) is None


def test_automatic_write_is_auditable_and_blocks_freeze_until_manual_audit(app, monkeypatch):
    owner = admin(app); row, uid = prepare(app, owner)
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    report = execute(app, uid)
    assert report['state'] == 'done' and report['counts'] == {'approved': 1}
    with connect(app) as db:
        updated = db.execute('SELECT * FROM samples').fetchone()
        assert updated['revision'] == 2 and updated['sha256'] == row['sha256']
        decision = triage.current_decision(db, updated)
        assert decision['audit_required'] == 1
        checks = json.loads(decision['evidence'])['checks']
        assert [p['profile']['model'] for p in checks] == ['qwen3.8-flash', 'qwen3-vl-plus-2025-12-19', 'qwen3-vl-plus-2025-12-19']
        assert ai.usage_totals(db)[4] == 3
        assert db.execute('SELECT COUNT(*) FROM events WHERE action="ai_auto_approved"').fetchone()[0] == 1
    page = owner.get('/?status=all&triage=audit')
    assert row['id'] in page.text and 'AI自动通过' in page.text
    assert owner.post('/batches', data={'csrf': csrf(owner, '/'), 'version': 'blocked'}).status_code == 409
    path = owner.get('/review/next?status=all&triage=audit').headers['Location']
    assert row['id'] in path and 'triage=audit' in path
    assert '本张待抽检' in owner.get(path).text
    body = review_body(owner, path, revision='2', decision='approved', reason='人工确认主体完整')
    response = owner.post(path, data=body)
    assert response.status_code == 302
    assert row['id'] not in owner.get('/?status=all&triage=audit').text
    assert owner.post('/batches', data={'csrf': csrf(owner, '/'), 'version': 'checked'}).status_code == 302


def test_undo_checks_role_revision_and_lease_and_never_reautoprocesses(app, monkeypatch):
    owner = admin(app); row, uid = prepare(app, owner)
    reviewer = member(app, owner, 'reviewer')
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    assert execute(app, uid)['counts'] == {'approved': 1}
    undo = '/samples/' + row['id'] + '/ai-undo'
    assert owner.post(undo, data={'revision': '2'}).status_code == 400
    assert reviewer.post(undo, data={'csrf': csrf(reviewer, '/'), 'revision': '2'}).status_code == 403
    assert owner.post(undo, data={'csrf': csrf(owner, '/'), 'revision': '1'}).status_code == 409
    draft = review_body(reviewer, '/samples/' + row['id'], revision='2')
    assert owner.post(undo, data={'csrf': csrf(owner, '/'), 'revision': '2'}).status_code == 409
    reviewer.post('/samples/' + row['id'] + '/release', data={'csrf': draft['csrf'], 'lease': draft['lease']})
    assert owner.post(undo, data={'csrf': csrf(owner, '/'), 'revision': '2'}).status_code == 302
    with connect(app) as db:
        current = db.execute('SELECT * FROM samples').fetchone()
        assert current['status'] == 'pending' and current['revision'] == 3
        assert not triage.untouched(db, current) and triage.current_decision(db, current) is None
    assert execute(app, uid)['counts'] == {}


@pytest.mark.parametrize('mutation', ['human', 'lease', 'field', 'frozen', 'revision'])
def test_human_activity_and_nonpublic_or_frozen_photos_are_skipped(app, monkeypatch, mutation):
    owner = admin(app); row, uid = prepare(app, owner)
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    with connect(app) as db:
        if mutation == 'human':
            db.execute('INSERT INTO events(actor,action,subject,details,created_at) VALUES(?,"review",?,"{}",?)', (uid,row['id'],ai.stamp()))
        elif mutation == 'lease':
            db.execute('INSERT INTO review_leases VALUES(?,?,"held",?)', (row['id'],uid,time.time()+900))
        elif mutation == 'field':
            db.execute('UPDATE samples SET source="field"')
        elif mutation == 'frozen':
            db.execute('UPDATE samples SET batch="already-frozen"')
        else:
            db.execute('UPDATE samples SET revision=2')
    def prohibited(*args, **kwargs):
        pytest.fail('Ineligible photo must not call API')
    assert execute(app, uid, analyze=prohibited)['counts'] == {}


def test_human_claim_during_calls_wins_over_auto_write(app, monkeypatch):
    owner = admin(app); row, uid = prepare(app, owner)
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    calls = []
    def analyze(*args, **kwargs):
        result = ai.analyze(*args, api=transport(), **kwargs)
        calls.append(1)
        if len(calls) == 3:
            assert owner.get('/samples/' + row['id']).status_code == 200
        return result
    assert execute(app, uid, analyze=analyze)['counts'] == {'changed_or_claimed': 1}
    with connect(app) as db:
        assert db.execute('SELECT status,revision FROM samples').fetchone()[:] == ('pending', 1)


def test_provider_error_and_exhausted_budget_leave_photos_pending(app, monkeypatch):
    owner = admin(app); row, uid = prepare(app, owner)
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    def failed(*args):
        raise ai.ReviewError('provider_auth_error')
    report = execute(app, uid, analyze=lambda *a, **k: ai.analyze(*a, api=failed, **k))
    assert report['state'] == 'stopped'
    with connect(app) as db:
        db.isolation_level = None
        assert db.execute('SELECT status FROM samples').fetchone()[0] == 'pending'
        config = {**app.config, 'REVIEW_AI_BUDGET_NANO': 0}
        with pytest.raises(Conflict, match='累计预算'):
            triage.new_job(db, uid, 1, config)


def test_rejection_dryrun_pause_and_single_worker_permissions(app, monkeypatch):
    owner = admin(app); row, uid = prepare(app, owner)
    reviewer = member(app, owner, 'member')
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    rejection = answer(decision='reject', category_id=None, flags=['out_of_scope'], subject='硬盘', reason='主要主体是硬盘，不属于十类物品')
    assert execute(app, uid, rejection, apply=False)['counts'] == {'would_rejected': 1}
    assert execute(app, uid, rejection)['counts'] == {'rejected': 1}
    with connect(app) as db:
        assert ai.usage_totals(db)[4] == 3  # dry run cache reused
    assert reviewer.post('/ai-triage/policy', data={'csrf': csrf(reviewer, '/'), 'enabled':'true'}).status_code == 403
    assert owner.post('/ai-triage/jobs', data={'csrf': csrf(owner, '/'), 'limit':51}).status_code == 400
    with connect(app) as db:
        db.isolation_level = None
        identity = triage.new_job(db, uid, 1, app.config)
        with pytest.raises(Conflict, match='已有一个'):
            triage.new_job(db, uid, 1, app.config)
        triage.set_enabled(db, uid, False)
        assert not triage.enabled(db)


def test_changed_photo_or_evidence_cannot_authorize_and_pause_is_rechecked(app, monkeypatch):
    owner = admin(app); row, uid = prepare(app, owner)
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    def analyze(*args, **kwargs):
        result = ai.analyze(*args, api=transport(), **kwargs)
        if kwargs['profile'].prompt_version == 'campus-ai-review-v5':
            Path(app.config['DATA_DIR'], 'images', row['filename']).write_bytes(b'changed')
        return result
    assert execute(app, uid, analyze=analyze)['counts'] == {'photo_changed': 1}
    with connect(app) as db:
        assert db.execute('SELECT status FROM samples').fetchone()[0] == 'pending'


@pytest.mark.parametrize('change', ['evidence', 'pause', 'label', 'human'])
def test_changes_between_analysis_and_apply_are_rechecked_atomically(app, monkeypatch, change):
    owner = admin(app); row, uid = prepare(app, owner)
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    def analyze(*args, **kwargs):
        result = ai.analyze(*args, api=transport(), **kwargs)
        if kwargs['profile'].prompt_version == 'campus-ai-review-v5':
            with connect(app) as connection:
                if change == 'evidence':
                    connection.execute('UPDATE ai_reviews SET state="error"')
                elif change == 'pause':
                    connection.execute('UPDATE ai_triage_settings SET enabled=0')
                elif change == 'label':
                    connection.execute('UPDATE samples SET category=1')
                else:
                    connection.execute('UPDATE samples SET status="approved",revision=revision+1,reason="human"')
        return result
    report = execute(app, uid, analyze=analyze)
    assert not set(report['counts']) & {'approved','rejected'}
    with connect(app) as db:
        assert db.execute('SELECT COUNT(*) FROM ai_auto_decisions').fetchone()[0] == 0
        if change == 'human':
            assert db.execute('SELECT reason FROM samples').fetchone()[0] == 'human'


def test_audit_sampling_preserves_provenance_and_freeze_is_immutable(app, monkeypatch):
    owner = admin(app); row, uid = prepare(app, owner)
    for color in ('blue','green','red'):
        public_sample(app, owner, color=color)
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    assert execute(app, uid)['counts'] == {'approved':4}
    with connect(app) as db:
        rows = db.execute('SELECT * FROM samples').fetchall()
        audits = [r for r in rows if triage.current_decision(db,r)['audit_required']]
        assert len(audits) == 1
        auto_ids = {r['id'] for r in rows if r['id'] != audits[0]['id']}
    path = '/samples/' + audits[0]['id']
    assert owner.post(path, data=review_body(owner,path,revision='2')).status_code == 302
    assert owner.post('/batches',data={'csrf':csrf(owner,'/'),'version':'with-auto'}).status_code == 302
    with connect(app) as db:
        receipt=json.loads(db.execute('SELECT receipt FROM batches').fetchone()[0])
        assert set(receipt['ai_review_provenance']) == auto_ids
        assert all(v['policy']==triage.POLICY and len(v['evidence_sha256'])==64 for v in receipt['ai_review_provenance'].values())
    sid=next(iter(auto_ids))
    assert owner.post('/samples/'+sid+'/ai-undo',data={'csrf':csrf(owner,'/'),'revision':'3'}).status_code == 409
