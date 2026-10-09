"""AI failures, stale suggestions and spend limits cannot alter human decisions."""
import json
import io
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from test_review import admin, app, review_body, upload
from test_workflow import connect
from campus_review import ai_review


def public_sample(app, owner, color='orange', crop=''):
    path = upload(owner, color=color)
    with connect(app) as db:
        db.execute('UPDATE samples SET source="open_images",crop=? WHERE id=?', (crop, path.rsplit('/', 1)[1]))
        return dict(db.execute('SELECT * FROM samples WHERE id=?', (path.rsplit('/', 1)[1],)).fetchone())


def categories():
    return json.loads((Path(__file__).resolve().parents[2] / 'shared/category-versions/campus-10-v4.json').read_text(encoding='utf-8'))


def answer(**changes):
    return json.dumps({'decision': 'pass', 'category_id': 0, 'subject': '水杯', 'reason': '主体清楚，类别一致',
                       'flags': [], 'bbox': None, **changes})


def fake_api(key, text, photo):
    assert key == 'test-private-key-1234' and 'JSON' in text and photo.startswith(b'\xff\xd8')
    assert 'reference_status' not in text and 'approved' not in text
    return answer(), [300, 80], len(photo) + 1500


def test_ai_cache_tracks_crop_label_model_prompt_and_preserves_human_decisions(app):
    owner = admin(app)
    row = public_sample(app, owner)
    data = Path(app.config['DATA_DIR'])
    with connect(app) as db:
        db.isolation_level = None
        original = dict(db.execute('SELECT * FROM samples').fetchone())
        state, result = ai_review.analyze(db, data, row, categories(), {}, 'test-private-key-1234', fake_api)
        assert state == 'done' and result['decision'] == 'pass'
        def forbidden_call(*args):
            pytest.fail('Cached image must not incur another API call')
        assert ai_review.analyze(db, data, row, categories(), {}, '', forbidden_call)[0] == 'done'
        assert dict(db.execute('SELECT * FROM samples').fetchone()) == original
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 1  # upload only
        assert ai_review.suggestion(db, row, categories())['label'] == '建议通过'
        assert ai_review.suggestion(db, {**row, 'crop': '[0,0,8000,8000]'}, categories()) is None
        assert ai_review.suggestion(db, {**row, 'category': 1}, categories()) is None
        newer = categories(); newer['category_version'] = 'new-test-version'
        assert ai_review.suggestion(db, row, newer) is None
    page = owner.get('/samples/' + row['id']).text
    assert 'AI初审 · 建议通过' in page and '不改动人工审核结果' in page
    assert 'test-private-key' not in page


@pytest.mark.parametrize('changes', [
    {'category_id': 3}, {'flags': ['multiple_subjects']}, {'category_id': None},
])
def test_ambiguous_pass_is_downgraded(changes):
    result = ai_review.validate(answer(**changes), {'category': 0}, (0, 0, 200, 200))
    assert result['decision'] == 'uncertain'


@pytest.mark.parametrize('changes', [
    {'decision': 'delete'}, {'category_id': True}, {'flags': ['unknown']},
    {'decision': 'crop', 'bbox': [100, 0, 0, 100]},
    {'decision': 'crop', 'bbox': [0, 0, 20000, 10000]},
    {'reason': ''},
])
def test_invalid_response_fails_closed(changes):
    with pytest.raises(ai_review.ReviewError, match='invalid_suggestion'):
        ai_review.validate(answer(**changes), {'category': 0, 'width': 200, 'height': 200}, (0, 0, 200, 200))


def test_suggested_crop_maps_existing_training_crop_to_original_pixels():
    result = ai_review.validate(answer(decision='crop', bbox=[0, 0, 1000, 1000]),
                               {'category': 0, 'width': 1000, 'height': 1000}, (100, 200, 800, 900))
    assert result['bbox'] == [1000, 2000, 8000, 9000]


def test_small_valid_crop_becomes_uncertain_without_a_usable_crop():
    result = ai_review.validate(answer(decision='crop', bbox=[0, 0, 100, 100]),
                               {'category': 0, 'width': 200, 'height': 200}, (0, 0, 200, 200))
    assert result['decision'] == 'uncertain' and result['bbox'] is None
    assert 'too_small' in result['flags'] and '不足128像素' in result['reason']


def test_unknown_usage_stays_reserved_and_auth_failure_is_not_retried(app):
    owner = admin(app); row = public_sample(app, owner)
    with connect(app) as db:
        db.isolation_level = None
        def failed(*args):
            raise ai_review.ReviewError('http_401')
        assert ai_review.analyze(db, Path(app.config['DATA_DIR']), row, categories(), {}, 'x', failed) == ('error', None)
        assert db.execute('SELECT charged_nano FROM ai_reviews').fetchone()[0] == ai_review.RESERVATION
        assert ai_review.analyze(db, Path(app.config['DATA_DIR']), row, categories(), {}, 'x', fake_api) == ('error', None)
        assert db.execute('SELECT status,revision FROM samples').fetchone()[:] == ('pending', 1)
        assert ai_review.analyze(db, Path(app.config['DATA_DIR']), row, categories(), {'REVIEW_AI_RETRY_ERRORS': True},
                                 'test-private-key-1234', fake_api)[0] == 'done'
        charged, attempts = db.execute('SELECT charged_nano,attempts FROM ai_reviews').fetchone()
        assert charged == ai_review.RESERVATION + 300 * ai_review.INPUT_RATE + 80 * ai_review.OUTPUT_RATE and attempts == 2


def test_budget_reservation_is_atomic_across_process_connections(app):
    owner = admin(app)
    rows = [public_sample(app, owner, color) for color in ('orange', 'blue')]
    data = Path(app.config['DATA_DIR'])
    def worker(row):
        with connect(app) as db:
            db.isolation_level = None
            try:
                return ai_review.analyze(db, data, row, categories(), {'REVIEW_AI_MAX_CALLS': 1},
                                         'test-private-key-1234', fake_api)[0]
            except ai_review.ReviewError as error:
                return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(worker, rows)) == ['done', 'persistent_budget_exhausted']


def test_field_photos_and_hash_changes_never_leave_server(app):
    owner = admin(app); path = upload(owner)
    data = Path(app.config['DATA_DIR'])
    with connect(app) as db:
        row = dict(db.execute('SELECT * FROM samples').fetchone())
    with pytest.raises(ai_review.ReviewError, match='public_photos_only'):
        ai_review.preview(data, row)
    row['source'] = 'open_images'
    (data / 'images' / row['filename']).write_bytes(b'changed')
    with pytest.raises(ai_review.ReviewError, match='photo_hash_or_path_changed'):
        ai_review.preview(data, row)


def test_key_file_is_opaque_private_and_invalid_key_is_not_echoed(app, monkeypatch, tmp_path):
    monkeypatch.delenv('DASHSCOPE_API_KEY', raising=False)
    secret = tmp_path / 'private.txt'; secret.write_text('test-private-key-1234')
    assert ai_review.read_key({'REVIEW_AI_KEY_FILE': str(secret)}) == 'test-private-key-1234'
    secret.write_text('a credential with spaces')
    with pytest.raises(ai_review.ReviewError, match='key_missing_or_invalid') as error:
        ai_review.read_key({'REVIEW_AI_KEY_FILE': str(secret)})
    assert 'credential' not in str(error.value)


def test_pilot_report_uses_hidden_human_reference_and_keeps_all_statuses(app, monkeypatch, tmp_path):
    owner = admin(app); row = public_sample(app, owner)
    assert owner.post('/samples/' + row['id'], data=review_body(owner, '/samples/' + row['id'], status='rejected')).status_code == 302
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    # Production default is bound at definition; inject only the transport boundary.
    original = ai_review.analyze
    monkeypatch.setattr(ai_review, 'analyze', lambda *args: original(*args, api=fake_api))
    result = app.test_cli_runner().invoke(args=['ai-review', '--limit', '100', '--report', str(tmp_path / 'pilot.json')])
    assert result.exit_code == 0, result.output
    report = json.loads((tmp_path / 'pilot.json').read_text(encoding='utf-8'))
    assert report['pass_precision'] == 0 and report['false_passes'] == [row['id']]
    assert not report['auto_approval_enabled'] and report['human_decisions_changed'] == 0
    assert 'test-private-key' not in result.output
    with connect(app) as db:
        assert db.execute('SELECT status,revision FROM samples').fetchone()[:] == ('rejected', 2)
    assert '与人工拒绝冲突 1 张' in owner.get('/').text
    pending = app.test_cli_runner().invoke(args=['ai-review', '--mode', 'pending'])
    assert pending.exit_code == 0
    with connect(app) as db:
        assert ai_review.latest_report(db)['mode'] == 'pending'
    assert '与人工拒绝冲突 1 张' in owner.get('/').text


def test_http_errors_never_echo_credentials_or_provider_body(monkeypatch):
    secret = 'test-private-key-1234'
    class FailedTransport:
        def open(self, request, timeout):
            assert request.full_url == ai_review.ENDPOINT and timeout == 90
            assert request.get_header('Authorization') == 'Bearer ' + secret
            body = json.loads(request.data)
            assert not body['enable_thinking'] and body['max_tokens'] == 500
            assert body['model'] == ai_review.MODEL
            raise urllib.error.HTTPError(request.full_url, 401, 'echo:' + secret, {}, io.BytesIO(secret.encode()))
    monkeypatch.setattr(ai_review.urllib.request, 'build_opener', lambda *args: FailedTransport())
    with pytest.raises(ai_review.ReviewError) as error:
        ai_review.call_api(secret, 'JSON', b'test-image')
    assert str(error.value) == 'http_401' and secret not in str(error.value)


def test_human_reference_is_not_ground_truth_and_reports_both_directions(app, monkeypatch, tmp_path):
    owner = admin(app)
    rows = [public_sample(app, owner, color) for color in ('orange', 'blue', 'green')]
    decisions = dict(zip((row['id'] for row in rows), ('pass', 'reject', 'crop')))
    with connect(app) as db:
        db.execute('UPDATE samples SET status="approved"')
        db.execute('UPDATE samples SET status="rejected" WHERE id=?', (rows[0]['id'],))
        before = [tuple(row) for row in db.execute('SELECT id,status,revision,crop FROM samples ORDER BY id')]
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    original = ai_review.analyze
    def analyze(*args):
        decision = decisions[args[2]['id']]
        return original(*args, api=lambda *unused: (answer(decision=decision,
                        bbox=[0, 0, 1000, 1000] if decision == 'crop' else None), [300, 80], 1000))
    monkeypatch.setattr(ai_review, 'analyze', analyze)
    report_path = tmp_path / 'reference.json'
    result = app.test_cli_runner().invoke(args=['ai-review', '--report', str(report_path)])
    assert result.exit_code == 0, result.output
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert report['reference_is_ground_truth'] is False
    assert report['pass_reference_agreement'] == 0
    assert report['pass_reference_disagreements'] == [rows[0]['id']]
    assert report['reject_reference_disagreements'] == [rows[1]['id']]
    assert report['approved_needing_crop_recheck'] == [rows[2]['id']]
    assert '一致率不是审核准确率' in owner.get('/').text
    assert '人工已通过但AI建议拒绝 1 张、建议裁剪 1 张' in owner.get('/').text
    with connect(app) as db:
        assert [tuple(row) for row in db.execute('SELECT id,status,revision,crop FROM samples ORDER BY id')] == before


def test_redirects_do_not_forward_api_key():
    assert ai_review.NoRedirect().redirect_request(None, None, None, None, None, 'https://untrusted.invalid') is None


def test_truncated_completion_preserves_observed_usage_and_leaves_photo_for_human(app, monkeypatch):
    owner = admin(app); row = public_sample(app, owner)
    response = {'model': ai_review.MODEL, 'usage': {'prompt_tokens': 900, 'completion_tokens': 500},
                'choices': [{'finish_reason': 'length', 'message': {'content': answer()}}]}
    class Transport:
        def open(self, request, timeout):
            return io.BytesIO(json.dumps(response).encode())
    monkeypatch.setattr(ai_review.urllib.request, 'build_opener', lambda *args: Transport())
    with connect(app) as db:
        db.isolation_level = None
        assert ai_review.analyze(db, Path(app.config['DATA_DIR']), row, categories(), {},
                                 'test-private-key-1234', ai_review.call_api) == ('error', None)
        record = db.execute('SELECT error_code,prompt_tokens,completion_tokens,charged_nano FROM ai_reviews').fetchone()
        assert record[:] == ('invalid_suggestion', 900, 500, 900 * ai_review.INPUT_RATE + 500 * ai_review.OUTPUT_RATE)
        assert db.execute('SELECT status,revision FROM samples').fetchone()[:] == ('pending', 1)


def test_unsolicited_localization_box_cannot_change_training_crop():
    result = ai_review.validate(answer(bbox=[80, 52, 926, 914]), {'category': 0}, (0, 0, 200, 200))
    assert result['decision'] == 'pass' and result['bbox'] is None


def test_collection_label_is_not_disclosed_to_the_vision_model():
    assert ai_review.prompt(categories(), 0) == ai_review.prompt(categories(), 9)
    assert '未向你提供抓取标签' in ai_review.prompt(categories(), 3)


def test_pending_batches_progress_without_recharging_cached_photos(app, monkeypatch, tmp_path):
    owner = admin(app)
    rows = [public_sample(app, owner, color) for color in ('orange', 'blue')]
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    original = ai_review.analyze
    monkeypatch.setattr(ai_review, 'analyze', lambda *args: original(*args, api=fake_api))
    visited = []
    for expected in (1, 1, 0):
        report_file = tmp_path / 'pending.json'
        result = app.test_cli_runner().invoke(args=['ai-review', '--mode', 'pending', '--limit', '1', '--report', str(report_file)])
        assert result.exit_code == 0, result.output
        report = json.loads(report_file.read_text(encoding='utf-8'))
        assert report['count'] == expected
        visited += [row['sample_id'] for row in report['samples']]
    assert set(visited) == {row['id'] for row in rows} and len(visited) == 2
    with connect(app) as db:
        assert db.execute('SELECT SUM(attempts) FROM ai_reviews').fetchone()[0] == 2
        assert db.execute('SELECT COUNT(*) FROM samples WHERE status="pending" AND revision=1').fetchone()[0] == 2
    assert 'AI · 建议通过' in owner.get('/').text


def test_plus_uses_its_own_prices_and_separate_cache(app, monkeypatch):
    owner = admin(app); row = public_sample(app, owner)
    flash_identity = ai_review.cache_key(row, categories())
    monkeypatch.setattr(ai_review, 'MODEL', 'qwen3-vl-plus-2025-12-19')
    rates = ai_review.MODEL_RATES[ai_review.MODEL]
    monkeypatch.setattr(ai_review, 'INPUT_RATE', rates[0])
    monkeypatch.setattr(ai_review, 'OUTPUT_RATE', rates[1])
    reserve = 32000 * rates[0] + 500 * rates[1]
    monkeypatch.setattr(ai_review, 'RESERVATION', reserve)
    assert reserve == 37_000_000 and flash_identity != ai_review.cache_key(row, categories())
    with connect(app) as db:
        db.isolation_level = None
        with pytest.raises(ai_review.ReviewError, match='persistent_budget_exhausted'):
            ai_review.analyze(db, Path(app.config['DATA_DIR']), row, categories(), {'REVIEW_AI_BUDGET_NANO': reserve - 1},
                             'test-private-key-1234', fake_api)
        assert ai_review.analyze(db, Path(app.config['DATA_DIR']), row, categories(), {}, 'test-private-key-1234', fake_api)[0] == 'done'
        assert db.execute('SELECT charged_nano FROM ai_reviews').fetchone()[0] == 300 * 1000 + 80 * 10000


def test_stricter_prompt_remains_blind_and_invalidates_older_suggestions(app, monkeypatch):
    owner = admin(app); row = public_sample(app, owner)
    identity = ai_review.cache_key(row, categories())
    monkeypatch.setattr(ai_review, 'PROMPT_VERSION', 'campus-ai-review-v4')
    assert ai_review.prompt(categories(), 0) == ai_review.prompt(categories(), 9)
    assert '主要主体之一' in ai_review.prompt(categories(), 0)
    assert ai_review.cache_key(row, categories()) != identity


def test_v5_keeps_object_identity_and_does_not_treat_cropping_as_repair(monkeypatch):
    monkeypatch.setattr(ai_review, 'PROMPT_VERSION', 'campus-ai-review-v5')
    text = ai_review.prompt(categories(), 0)
    assert text == ai_review.prompt(categories(), 9)
    assert '马克杯即使插花或装笔仍是杯子' in text
    assert '裁剪不能补回遮挡或出画部分' in text


def test_home_summary_and_calibration_use_only_active_model_and_prompt(app, monkeypatch):
    owner = admin(app); public_sample(app, owner)
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    original = ai_review.analyze
    monkeypatch.setattr(ai_review, 'analyze', lambda *args: original(*args, api=fake_api))
    runner = app.test_cli_runner()
    assert runner.invoke(args=['ai-review']).exit_code == 0
    with connect(app) as db:
        active = ai_review.latest_report(db)
        other = {**active, 'run_id': 'other-profile', 'model': 'qwen3-vl-plus-2025-12-19',
                 'prompt_version': 'campus-ai-review-v5'}
        db.execute('INSERT INTO ai_runs VALUES(?,?,?)', ('other-profile', json.dumps(other), active['at']))
        assert ai_review.latest_report(db)['run_id'] == active['run_id']
        assert ai_review.latest_report(db, 'pilot')['run_id'] == active['run_id']
        monkeypatch.setattr(ai_review, 'MODEL', other['model'])
        monkeypatch.setattr(ai_review, 'PROMPT_VERSION', other['prompt_version'])
        assert ai_review.latest_report(db)['run_id'] == 'other-profile'
        assert ai_review.latest_report(db, 'pilot')['run_id'] == 'other-profile'


def test_fixed_cohort_preserves_order_and_stops_changed_reference_before_api(app, monkeypatch, tmp_path):
    owner = admin(app); public_sample(app, owner)
    with connect(app) as db:
        db.execute('UPDATE samples SET status="approved"')
    monkeypatch.setenv('DASHSCOPE_API_KEY', 'test-private-key-1234')
    original = ai_review.analyze
    monkeypatch.setattr(ai_review, 'analyze', lambda *args: original(*args, api=fake_api))
    report_path = tmp_path / 'cohort.json'
    runner = app.test_cli_runner()
    assert runner.invoke(args=['ai-review', '--report', str(report_path)]).exit_code == 0
    baseline = json.loads(report_path.read_text(encoding='utf-8'))
    second = tmp_path / 'second.json'
    assert runner.invoke(args=['ai-review', '--cohort', str(report_path), '--report', str(second)]).exit_code == 0
    comparison = json.loads(second.read_text(encoding='utf-8'))
    assert comparison['cohort_source_sha256'] == ai_review.digest(report_path.read_bytes())
    assert comparison['run_usage']['attempts'] == 0 and comparison['cohort_usage']['attempts'] == 1
    assert comparison['samples'][0]['photo_sha256'] == baseline['samples'][0]['photo_sha256']
    with connect(app) as db:
        db.execute('UPDATE samples SET revision=revision+1')
    rejected = runner.invoke(args=['ai-review', '--cohort', str(report_path)])
    assert rejected.exit_code != 0 and 'cohort_reference_changed' in rejected.output
    with connect(app) as db:
        assert db.execute('SELECT SUM(attempts) FROM ai_reviews').fetchone()[0] == 1


def test_explicit_profile_does_not_mutate_global_model_prompt_or_prices(app):
    owner = admin(app); row = public_sample(app, owner)
    before = (ai_review.MODEL, ai_review.PROMPT_VERSION, ai_review.INPUT_RATE, ai_review.RESERVATION)
    profile = ai_review.Profile('qwen3.8-flash', 'campus-ai-review-v4')
    def transport(key, text, photo):
        assert '复核门槛' in text
        return answer(), [300, 80], 1000
    with connect(app) as db:
        db.isolation_level = None
        assert ai_review.analyze(db, Path(app.config['DATA_DIR']), row, categories(), {}, 'test-private-key-1234',
                                 api=transport, profile=profile)[0] == 'done'
        assert db.execute('SELECT model,charged_nano FROM ai_reviews').fetchone()[:] == ('qwen3.8-flash', 300 * 800 + 80 * 2700)
        assert ai_review.suggestion(db, row, categories()) is None
        assert ai_review.suggestion(db, row, categories(), profile)['decision'] == 'pass'
    assert before == (ai_review.MODEL, ai_review.PROMPT_VERSION, ai_review.INPUT_RATE, ai_review.RESERVATION)


def test_explicit_transport_requires_matching_model_and_alias_cache_generation(monkeypatch):
    class Transport:
        def open(self, request, timeout):
            assert json.loads(request.data)['model'] == 'qwen3.8-flash'
            return io.BytesIO(json.dumps({'model': 'qwen3.8-flash', 'usage': {'prompt_tokens': 300, 'completion_tokens': 80},
                   'choices': [{'finish_reason': 'stop', 'message': {'content': answer()}}]}).encode())
    monkeypatch.setattr(ai_review.urllib.request, 'build_opener', lambda *args: Transport())
    assert ai_review.call_api('private', 'JSON', b'preview', model='qwen3.8-flash')[1] == [300, 80]
    row = {'sha256': 'photo', 'crop': '', 'category': 0}
    profile = ai_review.Profile('qwen3.8-flash', 'campus-ai-review-v3')
    identity = ai_review.cache_key(row, categories(), profile)
    monkeypatch.setitem(ai_review.ALIAS_GENERATIONS, 'qwen3.8-flash', 'new-provider-review-cycle')
    assert identity != ai_review.cache_key(row, categories(), profile)
