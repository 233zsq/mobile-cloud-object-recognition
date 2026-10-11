"""New photos wait for AI; only current, unresolved evidence enters human work."""
import json
from pathlib import Path

from test_review import admin, app, public_archive
from test_workflow import connect
from test_ai_review import answer, categories, public_sample
from test_ai_triage import prepare, execute, transport
from campus_review import ai_triage as triage, ai_review as ai


def test_waiting_manual_and_failed_queues_do_not_mix(app, monkeypatch):
    owner = admin(app)
    row, uid = prepare(app, owner)
    app.config['REVIEW_TRIAGE_POLICY'] = triage.CASCADE_POLICY
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    assert row['id'] not in owner.get('/').text
    assert row['id'] in owner.get('/?triage=waiting').text
    assert execute(app, uid, result=answer(decision='crop', bbox=[0, 0, 1000, 1000]))['counts'] == {'manual': 1}
    assert row['id'] in owner.get('/').text
    assert row['id'] not in owner.get('/?triage=waiting').text
    assert row['id'] not in owner.get('/?triage=error').text
    with connect(app) as db:
        db.execute("UPDATE ai_triage_routes SET state='error'")
    assert row['id'] not in owner.get('/').text
    assert row['id'] in owner.get('/?triage=error').text
    # Changed prompts/configurations must not reuse a stale routing conclusion.
    app.config['REVIEW_TRIAGE_PRIMARY_MODEL'] = triage.MAX_MODEL
    app.config['REVIEW_TRIAGE_POLICY'] = triage.MAX_POLICY
    assert row['id'] not in owner.get('/?triage=error').text
    assert row['id'] in owner.get('/?triage=waiting').text


def test_invalid_ai_output_enters_error_queue_without_auto_status_change(app, monkeypatch):
    owner = admin(app)
    row, uid = prepare(app, owner)
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    def invalid(*args, **kwargs):
        return ai.analyze(*args, api=transport('not-json'), **kwargs)
    assert execute(app, uid, analyze=invalid)['counts'] == {'ai_error': 1}
    assert row['id'] in owner.get('/?triage=error').text
    assert row['id'] not in owner.get('/').text
    assert execute(app, uid, analyze=invalid)['counts'] == {}
    with connect(app) as db:
        assert db.execute('SELECT status,revision FROM samples').fetchone()[:] == ('pending', 1)
        assert db.execute('SELECT COUNT(*) FROM ai_auto_decisions').fetchone()[0] == 0


def test_new_audit_rate_is_pinned_and_old_jobs_keep_their_rate(app, monkeypatch):
    owner = admin(app)
    row, uid = prepare(app, owner)
    app.config.update(REVIEW_TRIAGE_POLICY=triage.CASCADE_POLICY, REVIEW_AI_AUDIT_PERCENT=5)
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    with connect(app) as db:
        db.isolation_level = None
        identity = triage.new_job(db, uid, 50, app.config)
        for n in range(40):
            db.execute('INSERT INTO ai_auto_decisions(id,sample_id,job_id,policy,applied_revision,after_status,before_values,evidence,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                       (f'd{n}', row['id'], identity, triage.CASCADE_POLICY, 1, 'approved', '{}', '{}', ai.stamp()))
        app.config['REVIEW_AI_AUDIT_PERCENT'] = 10
        triage.audit_sample(db, identity)
        assert db.execute('SELECT SUM(audit_required) FROM ai_auto_decisions').fetchone()[0] == 2
        # Historical rate survives subsequent configuration changes.
        db.execute('UPDATE ai_triage_jobs SET audit_percent=10 WHERE id=?', (identity,))
        triage.audit_sample(db, identity)
        assert db.execute('SELECT SUM(audit_required) FROM ai_auto_decisions').fetchone()[0] == 4


def test_finite_round_only_reviews_its_imported_archive_and_does_not_recharge(app, monkeypatch, tmp_path):
    owner=admin(app); archive=tmp_path/'queue.zip'; public_archive(app,archive)
    runner=app.test_cli_runner()
    assert runner.invoke(args=['import-public',str(archive)]).exit_code == 0
    outside=public_sample(app,owner,'blue')
    app.config.update(REVIEW_TRIAGE_POLICY=triage.CASCADE_POLICY,REVIEW_AI_MAX_CALLS=5000)
    monkeypatch.setenv('DASHSCOPE_API_KEY','test-private-key-1234')
    monkeypatch.setattr(ai,'call_api',lambda *args,**kwargs:(answer(),[300,80],100))
    with connect(app) as db:
        db.isolation_level=None
        uid=db.execute('SELECT id FROM users WHERE role="admin"').fetchone()[0]
        triage.set_enabled(db,uid,True)
    command=['ai-triage-round','--actor',str(uid),'--archive',str(archive),'--max-photos','500','--progress']
    first=runner.invoke(args=command+[str(tmp_path/'round.json')])
    assert first.exit_code == 0, first.output
    result=json.loads((tmp_path/'round.json').read_text())
    assert result['state']=='done' and result['processed']==1 and result['counts']=={'approved':1}
    assert len(result['jobs'])==1 and result['sample_scope_sha256']
    assert runner.invoke(args=command+[str(tmp_path/'round.json')]).exit_code != 0
    second=runner.invoke(args=command+[str(tmp_path/'second.json')])
    assert second.exit_code == 0, second.output
    with connect(app) as db:
        assert ai.usage_totals(db)[4]==1
        assert db.execute('SELECT status FROM samples WHERE id=?',(outside['id'],)).fetchone()[0]=='pending'
