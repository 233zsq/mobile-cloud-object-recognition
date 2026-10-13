from uuid import uuid4
import pytest
from test_records import database_app, upload


def evidence(status='uncertain'):
    return {'status': status, 'policy_version': 'scope-knownness-v1', 'policy_sha256': 'a'*64,
            'knownness': .1 if status == 'uncertain' else .9, 'manual_confirmed': status != 'accepted'}


def test_scope_evidence_is_preserved_and_legacy_retries_cannot_erase_it(database_app, upload):
    client = database_app.test_client()
    body = dict(upload, scope_decision=evidence())
    first = client.post('/api/records', json=body)
    assert first.status_code == 201
    assert first.json['record']['scope_decision'] == body['scope_decision']
    assert first.json['record']['predicted_id'] == upload['predicted_id']
    assert client.post('/api/records', json=body).status_code == 200
    legacy_retry = client.post('/api/records', json=upload)
    assert legacy_retry.status_code == 200
    assert legacy_retry.json['record']['scope_decision'] == body['scope_decision']
    changed = dict(body, scope_decision=dict(evidence(), knownness=.2))
    assert client.post('/api/records', json=changed).status_code == 409


def test_uncertain_filters_and_counts_do_not_guess_status_for_old_records(database_app, upload):
    client = database_app.test_client()
    for status in ['uncertain', 'accepted', None]:
        body = dict(upload, record_id=str(uuid4()))
        if status is not None:
            body['scope_decision'] = evidence(status)
        assert client.post('/api/records', json=body).status_code == 201
    stats = client.get('/api/stats').json
    assert stats['total_count'] == 3 and stats['uncertain_count'] == 1
    assert stats['recognition_status_counts'] == {'accepted': 1, 'uncertain': 1, 'unreported': 1}
    for status in ['uncertain', 'accepted', 'unreported']:
        result = client.get('/api/records?recognition_status=' + status).json
        assert result['total'] == 1
        filtered_stats = client.get('/api/stats?recognition_status=' + status).json
        assert filtered_stats['total_count'] == 1
    assert client.get('/api/stats?recognition_status=other').status_code == 400


def test_explicit_scope_evidence_can_fill_a_legacy_upload_once(database_app, upload):
    client = database_app.test_client()
    assert client.post('/api/records', json=upload).status_code == 201
    enriched = client.post('/api/records', json=dict(upload, scope_decision=evidence()))
    assert enriched.status_code == 200
    assert enriched.json['record']['scope_decision'] == evidence()
    changed = dict(upload, scope_decision=dict(evidence(), knownness=.8))
    assert client.post('/api/records', json=changed).status_code == 409


@pytest.mark.parametrize('change', [
    {'manual_confirmed': False}, {'knownness': 1.1}, {'policy_sha256': 'bad'}, {'manual_confirmed': 1},
])
def test_unconfirmed_or_invalid_uncertain_results_cannot_be_uploaded(database_app, upload, change):
    body = dict(upload, scope_decision=dict(evidence(), **change))
    assert database_app.test_client().post('/api/records', json=body).status_code == 400


def test_mysql_additive_migration_preserves_legacy_records(database_app, upload):
    if database_app.config['TEST_DATABASE_KIND'] != 'mysql':
        pytest.skip('Actual MySQL DDL only')
    from pathlib import Path
    from sqlalchemy import text
    from app.extensions import db
    from app.config import PROJECT_ROOT
    client = database_app.test_client()
    assert client.post('/api/records', json=upload).status_code == 201
    with database_app.app_context():
        with db.engine.begin() as connection:
            connection.execute(text('DROP TABLE inference_decision'))
            script = '\n'.join(line for line in (PROJECT_ROOT/'database/schema/002_inference_decision.sql').read_text(encoding='utf8').splitlines()
                               if not line.lstrip().startswith('--'))
            for statement in script.split(';'):
                if statement.strip():
                    connection.execute(text(statement))
    legacy = client.get('/api/records').json['records'][0]
    assert legacy['record_id'] == upload['record_id'] and legacy['scope_decision'] is None
    enriched = client.post('/api/records', json=dict(upload, scope_decision=evidence()))
    assert enriched.status_code == 200 and enriched.json['record']['scope_decision'] == evidence()
