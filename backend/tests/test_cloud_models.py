import io
import json
from uuid import uuid4
from pathlib import Path

import pytest

from app.errors import ApiError
from inference_registry import LABELS, load_registry
from backend_support import ReadyModel


def entry(version='campus-gpu-v1'):
    return {'model_version': version, 'model_sha256': 'a' * 64, 'labels_sha256': 'b' * 64,
            'category_version': 'campus-10-v4', 'labels': LABELS, 'status': 'frozen',
            'display_name': '基准版', 'description': '固定基准', 'low_confidence_threshold': .6,
            'package': str(Path.cwd() / 'managed/models' / version)}


def test_registry_requires_unique_approved_compatible_models(tmp_path):
    path = tmp_path / 'models.json'
    data = {'schema_version': 1, 'default_model_version': 'campus-gpu-v1', 'models': [entry()]}
    path.write_text(json.dumps(data))
    assert load_registry(path) == data
    for change in ({'status': 'experimental'}, {'labels': LABELS[::-1]}, {'model_sha256': 'invalid'},
                   {'low_confidence_threshold': float('nan')}, {'package': '../escape'}):
        path.write_text(json.dumps(dict(data, models=[dict(entry(), **change)])))
        with pytest.raises(ValueError):
            load_registry(path)
    path.write_text(json.dumps(dict(data, models=[entry(), entry()])))
    with pytest.raises(ValueError):
        load_registry(path)


def test_catalog_requires_authentication_omits_paths_and_reports_unavailable(app, client):
    app.config['API_TOKEN'] = 'test-only-token'
    model = ReadyModel()
    app.extensions['inference_contracts'] = [{k: v for k, v in entry().items() if k != 'package'}]
    app.extensions['inference_client'] = model
    assert client.get('/api/models').status_code == 401
    response = client.get('/api/models', headers={'Authorization': 'Bearer test-only-token'})
    assert response.json['models'][0]['available'] is True
    assert 'package' not in response.json['models'][0]
    def failed():
        raise ApiError('MODEL_UNAVAILABLE', 'unavailable', 503)
    model.health = failed
    assert client.get('/api/models', headers={'Authorization': 'Bearer test-only-token'}).json['models'][0]['available'] is False


def test_selected_model_is_routed_without_changing_default_or_saving_records(app, client, monkeypatch):
    import app.services.records as records
    monkeypatch.setattr(records, 'save_record', lambda _: pytest.fail('Inference must not save records'))
    primary, alternate = ReadyModel(), ReadyModel()
    alternate.version = 'campus-evolve-v2'
    app.extensions['inference_client'] = primary
    app.extensions['inference_clients'] = {alternate.version: alternate}
    for selected in [alternate.version, primary.version, alternate.version]:
        response = client.post('/api/infer', data={'request_id': str(uuid4()), 'model_version': selected,
            'image': (io.BytesIO(b'image'), 'photo.jpg')})
        assert response.status_code == 200 and response.json['model_version'] == selected
    assert primary.images == [b'image'] and alternate.images == [b'image', b'image']
    assert client.get('/api/health').json['model_version'] == primary.version
    bad = client.post('/api/infer', data={'request_id': str(uuid4()), 'model_version': '../../model',
        'image': (io.BytesIO(b'image'), 'photo.jpg')})
    assert bad.status_code == 409


def test_registry_default_must_match_pinned_server_configuration(tmp_path):
    from app import create_app
    path = tmp_path / 'models.json'
    path.write_text(json.dumps({'schema_version': 1, 'default_model_version': 'campus-evolve-v2',
                               'models': [entry('campus-evolve-v2')]}))
    with pytest.raises(ValueError, match='default differs'):
        create_app({'INFERENCE_REGISTRY': str(path), 'INFERENCE_SOCKET': '/tmp/model.sock'}, env_file=tmp_path/'missing.env')
