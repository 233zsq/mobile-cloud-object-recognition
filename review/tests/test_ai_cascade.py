"""Exercise real ledger writes, conditional routing and historical job isolation."""
import json
from pathlib import Path

import pytest

from test_review import admin, app
from test_workflow import connect
from test_ai_review import answer, categories, public_sample
from test_ai_triage import prepare, execute, transport
from campus_review import ai_review as ai, ai_triage as triage


def cascade(app, owner, monkeypatch):
    row, uid = prepare(app, owner)
    app.config['REVIEW_TRIAGE_POLICY'] = triage.CASCADE_POLICY
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    return row, uid


@pytest.mark.parametrize('first,second,expected,calls', [
    ({}, None, 'approved', 1),
    ({'decision': 'reject', 'category_id': None, 'flags': ['out_of_scope']}, None, 'rejected', 1),
    ({'decision': 'uncertain'}, {}, 'approved', 2),
    ({'reason': '可能是饮水杯'}, {}, 'approved', 2),
    ({'decision': 'uncertain'}, {'decision': 'reject', 'flags': ['blurred']}, 'rejected', 2),
    ({'decision': 'uncertain'}, {'decision': 'uncertain'}, 'manual', 2),
    ({'decision': 'uncertain'}, {'reason': '用途无法确认'}, 'manual', 2),
    ({'decision': 'uncertain'}, {'decision': 'crop', 'bbox': [0, 0, 1000, 1000]}, 'manual', 2),
    ({'decision': 'crop', 'bbox': [0, 0, 1000, 1000]}, None, 'manual', 1),
    ({'category_id': 1}, None, 'manual', 1),
])
def test_clear_flash_uses_one_call_only_uncertainty_escalates(app, monkeypatch, first, second, expected, calls):
    owner = admin(app); row, uid = cascade(app, owner, monkeypatch)
    used = []
    def analyze(*args, **kwargs):
        profile = kwargs['profile']; used.append(profile)
        result = first if profile.model == triage.FLASH_MODEL else second
        assert result is not None, 'Unnecessary Max call'
        return ai.analyze(*args, api=transport(answer(**result)), **kwargs)
    report = execute(app, uid, analyze=analyze)
    assert report['state'] == 'done' and report['counts'] == {expected: 1}
    assert len(used) == calls and used[0].model == triage.FLASH_MODEL
    assert all(p.prompt_version == 'campus-ai-review-v6' for p in used)
    assert report['routing'].get('max_reviews', 0) == calls - 1
    with connect(app) as db:
        assert ai.usage_totals(db)[4] == calls
        updated = db.execute('SELECT * FROM samples').fetchone()
        assert updated['status'] == ('pending' if expected == 'manual' else expected)
        if expected != 'manual':
            record = triage.current_decision(db, updated)
            assert record['policy'] == triage.CASCADE_POLICY and record['audit_required'] == 1
            assert len(json.loads(record['evidence'])['checks']) == calls


def test_cascade_is_fresh_install_default_and_ui_explains_routing(app):
    assert app.config['REVIEW_TRIAGE_POLICY'] == triage.CASCADE_POLICY
    owner = admin(app)
    page = owner.get('/').text
    assert 'Flash 优先 · Max 复核' in page and '不确定交 Max 复核' in page
    assert 'value="50"' in page


@pytest.mark.parametrize('subject', [
    '整面书架中密集排列的大量实体书本', '书店内陈列的实体书籍',
    'A person reading a paperback book while sitting in a blue chair.',
])
def test_book_scene_passes_escalate_and_cannot_auto_pass_even_with_max(subject):
    result=json.loads(answer(category_id=2,subject=subject))
    assert triage.needs_max(result,2)
    assert triage.decide([result,result],2,triage.CASCADE_POLICY) is None
    # A clear Max rejection can still resolve the scene without human work.
    rejected=json.loads(answer(decision='reject',category_id=2,flags=['multiple_subjects']))
    assert triage.decide([result,rejected],2,triage.CASCADE_POLICY)=='rejected'
    closeup=json.loads(answer(category_id=2,subject='一本打开的实体装订书'))
    assert triage.decide([result,closeup],2,triage.CASCADE_POLICY)=='approved'


def test_routing_rule_changes_invalidate_routes_without_invalidating_paid_cache(monkeypatch):
    row={'revision':1,'sha256':'a'*64,'category':2,'crop':None}
    selected=triage.profiles(triage.FLASH_MODEL,triage.CASCADE_POLICY)
    context=triage.routing_context(categories(),selected)
    identity=triage.selection_identity(row,categories(),selected)
    cache=ai.cache_key(row,categories(),selected[0])
    monkeypatch.setattr(triage,'ROUTING_RULES_VERSION','future-rules')
    assert triage.routing_context(categories(),selected)!=context
    assert triage.selection_identity(row,categories(),selected)!=identity
    assert ai.cache_key(row,categories(),selected[0])==cache


def test_flash_v6_uses_same_prompt_without_max_thinking_or_prices(app, monkeypatch):
    owner = admin(app); row, uid = cascade(app, owner, monkeypatch)
    flash, maximum = triage.configured_profiles(app.config)
    assert ai.prompt(categories(), 0, flash.prompt_version) == ai.prompt(categories(), 0, maximum.prompt_version)
    assert ai.inference(flash) == {'enable_thinking': False, 'thinking_budget': 0, 'max_tokens': 500}
    assert ai.inference(maximum)['thinking_budget'] == 1024
    assert ai.reservation_for(flash) == 32000 * 800 + 500 * 2700
    execute(app, uid)
    with connect(app) as db:
        assert db.execute('SELECT model,charged_nano FROM ai_reviews').fetchone()[:] == (triage.FLASH_MODEL, 300 * 800 + 80 * 2700)


@pytest.mark.parametrize('invalid', [True, False])
def test_flash_transport_or_format_error_never_triggers_max(app, monkeypatch, invalid):
    owner = admin(app); row, uid = cascade(app, owner, monkeypatch)
    used = []
    def api(*args):
        if invalid:
            return 'not-json', [300, 80], 100
        raise ai.ReviewError('http_503')
    def analyze(*args, **kwargs):
        used.append(kwargs['profile'].model)
        return ai.analyze(*args, api=api, **kwargs)
    report = execute(app, uid, analyze=analyze)
    assert used == [triage.FLASH_MODEL]
    assert report['state'] == ('done' if invalid else 'stopped')
    with connect(app) as db:
        assert db.execute('SELECT status,revision FROM samples').fetchone()[:] == ('pending', 1)


def test_max_cannot_override_clear_flash_when_saved_evidence_changes(app, monkeypatch):
    owner = admin(app); row, uid = cascade(app, owner, monkeypatch)
    def analyze(*args, **kwargs):
        maximum = kwargs['profile'].model == triage.MAX_MODEL
        result = ai.analyze(*args, api=transport(answer() if maximum else answer(decision='uncertain')), **kwargs)
        if maximum:
            args[0].execute('UPDATE ai_reviews SET result=? WHERE model=?',
                            (answer(decision='reject', category_id=None, flags=['out_of_scope']), triage.FLASH_MODEL))
        return result
    assert execute(app, uid, analyze=analyze)['counts'] == {'manual': 1}
    with connect(app) as db:
        assert db.execute('SELECT COUNT(*) FROM ai_auto_decisions').fetchone()[0] == 0


@pytest.mark.parametrize('claim_at', [triage.FLASH_MODEL, triage.MAX_MODEL])
def test_human_claim_wins_during_either_cascade_step(app, monkeypatch, claim_at):
    owner = admin(app); row, uid = cascade(app, owner, monkeypatch)
    def analyze(*args, **kwargs):
        profile = kwargs['profile']
        first_uncertain = claim_at == triage.MAX_MODEL and profile.model == triage.FLASH_MODEL
        result = ai.analyze(*args, api=transport(answer(decision='uncertain') if first_uncertain else answer()), **kwargs)
        if profile.model == claim_at:
            assert owner.get('/samples/' + row['id']).status_code == 200
        return result
    assert execute(app, uid, analyze=analyze)['counts'] == {'changed_or_claimed': 1}
    with connect(app) as db:
        assert db.execute('SELECT status,revision FROM samples').fetchone()[:] == ('pending', 1)


def test_max_budget_stop_keeps_completed_flash_decisions_for_audit(app, monkeypatch):
    owner = admin(app); row, uid = cascade(app, owner, monkeypatch)
    public_sample(app, owner, color='blue')
    app.config['REVIEW_AI_BUDGET_NANO'] = 40_000_000
    seen = []
    def analyze(*args, **kwargs):
        seen.append(kwargs['profile'].model)
        return ai.analyze(*args, api=transport(answer() if len(seen) == 1 else answer(decision='uncertain')), **kwargs)
    report = execute(app, uid, analyze=analyze)
    assert report['state'] == 'stopped' and report['error_code'] == 'persistent_budget_exhausted'
    assert seen == [triage.FLASH_MODEL, triage.FLASH_MODEL, triage.MAX_MODEL]
    with connect(app) as db:
        assert ai.usage_totals(db)[4] == 2
        assert triage.pending_approval_audits(db) == 1
        assert db.execute('SELECT COUNT(*) FROM samples WHERE status="pending"').fetchone()[0] == 1


def test_inflight_max_job_stays_max_after_default_changes(app, monkeypatch):
    owner = admin(app); row, uid = prepare(app, owner)
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    app.config['REVIEW_TRIAGE_PRIMARY_MODEL'] = triage.MAX_MODEL
    with connect(app) as db:
        db.isolation_level = None
        identity = triage.new_job(db, uid, 1, app.config)
        app.config.update(REVIEW_TRIAGE_POLICY=triage.CASCADE_POLICY, REVIEW_TRIAGE_PRIMARY_MODEL=triage.FLASH_MODEL)
        report = triage.run_job(db, Path(app.config['DATA_DIR']), categories(), app.config, identity,
                               lambda *a, **k: ai.analyze(*a, api=transport(), **k))
        assert report['policy'] == triage.MAX_POLICY and report['run_usage']['attempts'] == 1
        assert db.execute('SELECT model FROM ai_reviews').fetchone()[0] == triage.MAX_MODEL
