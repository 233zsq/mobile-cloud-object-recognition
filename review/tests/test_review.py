import io
import json
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from campus_review import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING': True, 'SECRET_KEY': 'test-' * 10, 'DATA_DIR': str(tmp_path),
                       'SESSION_COOKIE_SECURE': False})


def csrf(client, path='/login'):
    response = client.get(path)
    assert response.status_code == 200
    with client.session_transaction() as state:
        return state['csrf']


def join(client, token, name):
    return client.post(token, data={'csrf': csrf(client, token), 'username': name, 'password': 'a-strong-test-password'})


def admin(app):
    result = app.test_cli_runner().invoke(args=['bootstrap'])
    assert result.exit_code == 0, result.output
    client = app.test_client()
    assert join(client, result.output.strip(), 'admin').status_code == 302
    assert client.post('/login', data={'csrf': csrf(client), 'username': 'admin', 'password': 'a-strong-test-password'}).status_code == 302
    return client


def photo():
    stream = io.BytesIO()
    Image.new('RGB', (200, 200), 'orange').save(stream, 'JPEG')
    stream.seek(0)
    return stream


def upload(client):
    response = client.post('/upload', data={'csrf': csrf(client, '/upload'), 'image': (photo(), '../../evil.jpg'),
                           'object_id': 'cup-01', 'session_id': 'lab-01', 'category': '0'})
    assert response.status_code == 302
    return response.headers['Location']


def review(client, path, revision='1'):
    return client.post(path, data={'csrf': csrf(client, path), 'revision': revision, 'category': '0', 'status': 'approved',
                                  'object_id': 'cup-01', 'session_id': 'lab-01', 'group_id': 'series-01', 'reason': 'clear cup'})


def test_invitation_is_single_use_and_roles_are_enforced(app):
    client = admin(app)
    response = client.post('/invites', data={'csrf': csrf(client, '/')})
    token = re.search(r'https?://[^/]+(/join/[^"<>]+)', response.text).group(1)
    member = app.test_client()
    assert join(member, token, 'member').status_code == 302
    other = app.test_client()
    assert other.post(token, data={'csrf': csrf(other), 'username': 'other', 'password': 'a-strong-test-password'}).status_code == 404
    member.post('/login', data={'csrf': csrf(member), 'username': 'member', 'password': 'a-strong-test-password'})
    assert member.post('/batches', data={'csrf': csrf(member, '/'), 'version': 'bad'}).status_code == 403
    assert member.post('/invites', data={'csrf': csrf(member, '/')}).status_code == 403
    assert app.test_cli_runner().invoke(args=['bootstrap']).exit_code != 0


def test_review_freeze_download_and_immutable_photos(app):
    client = admin(app)
    path = upload(client)
    assert review(client, path).status_code == 302
    assert review(client, path).status_code == 409  # stale member browser
    response = client.post('/batches', data={'csrf': csrf(client, '/'), 'version': 'field-001'})
    assert response.status_code == 302
    assert review(client, path, '3').status_code == 409
    response = client.get('/batches/field-001.zip')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as package:
        receipt = json.loads(package.read('batch.json'))
        assert receipt['purpose'] == 'training_only' and receipt['count'] == 1
        assert set(package.namelist()) == {'batch.json', *receipt['files']}
        assert 'series-01' in package.read('samples.csv').decode()
    assert app.test_client().get('/images/' + path.split('/')[-1]).status_code == 302
    assert client.get('/').status_code == 200
    assert '已冻结' in client.get(path).text


def test_hash_change_blocks_freeze_and_no_duplicate_upload(app):
    client = admin(app)
    path = upload(client)
    response = client.post('/upload', data={'csrf': csrf(client, '/upload'), 'image': (photo(), 'again.jpg'),
                           'object_id': 'cup-01', 'session_id': 'lab-01', 'category': '0'})
    assert response.status_code == 409
    review(client, path)
    images = Path(app.config['DATA_DIR']) / 'images'
    next(images.iterdir()).write_bytes(b'changed')
    assert client.post('/batches', data={'csrf': csrf(client, '/'), 'version': 'corrupt'}).status_code == 409
    assert not (Path(app.config['DATA_DIR']) / 'batches/corrupt.zip').exists()


def test_csrf_invalid_image_and_host_protection(app):
    client = admin(app)
    assert client.post('/invites').status_code == 400
    response = client.post('/upload', data={'csrf': csrf(client, '/upload'), 'image': (io.BytesIO(b'<svg>bad</svg>'), 'evil.jpg'),
                           'object_id': 'a', 'session_id': 'b', 'category': '0'})
    assert response.status_code == 400
    response = client.get('/health')
    assert response.status_code == 200
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert client.get('/health', headers={'Host': 'evil.example'}).status_code == 400


def test_candidate_is_immutable_and_human_decision_bound_to_hash(app, tmp_path):
    client = admin(app)
    from campus_review import ROOT
    baseline = json.loads((ROOT.parent / 'models/releases/campus-gpu-v1/metadata.json').read_text(encoding='utf-8'))
    report = {'purpose': 'evolution_comparison', 'status': 'pending_human_approval', 'baseline': baseline,
              'candidate': {'status': 'frozen', 'model_version': 'campus-evolve-test', 'sha256': 'b' * 64}, 'subsets': {}}
    path = tmp_path / 'comparison.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    runner = app.test_cli_runner()
    assert runner.invoke(args=['register-candidate', str(path)]).exit_code == 0
    assert client.get('/candidates/campus-evolve-test').status_code == 200
    conn = sqlite3.connect(tmp_path / 'review.sqlite3')
    digest = conn.execute('SELECT digest FROM candidates').fetchone()[0]
    conn.close()
    body = {'csrf': csrf(client, '/'), 'digest': digest, 'decision': 'approved', 'reason': 'checked evidence'}
    assert client.post('/candidates/campus-evolve-test/decision', data={**body, 'digest': 'wrong'}).status_code == 409
    assert client.post('/candidates/campus-evolve-test/decision', data=body).status_code == 302
    assert client.get('/candidates/campus-evolve-test/approval.json').json['model_sha256']=='b'*64
    assert client.post('/candidates/campus-evolve-test/decision', data=body).status_code == 409
    report['candidate']['sha256'] = 'c' * 64
    path.write_text(json.dumps(report), encoding='utf-8')
    assert runner.invoke(args=['register-candidate', str(path)]).exit_code != 0


def test_login_throttles_password_guessing(app):
    client = admin(app)
    client.post('/logout', data={'csrf': csrf(client, '/')})
    token = csrf(client)
    for _ in range(10):
        assert client.post('/login', data={'csrf': token, 'username': 'admin', 'password': 'wrong'}).status_code == 403
    assert client.post('/login', data={'csrf': token, 'username': 'admin', 'password': 'wrong'}).status_code == 429


def test_concurrent_reviewers_cannot_overwrite_each_other(app):
    from concurrent.futures import ThreadPoolExecutor
    first=admin(app); path=upload(first)
    second=app.test_client()
    second.post('/login',data={'csrf':csrf(second),'username':'admin','password':'a-strong-test-password'})
    bodies=[]
    for client in (first,second):
        bodies.append({'csrf':csrf(client,path),'revision':'1','category':'0','status':'approved',
                       'object_id':'cup-01','session_id':'lab-01','group_id':'series-01','reason':'checked'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(c.post,path,data=b) for c,b in zip((first,second),bodies)]
        assert sorted(job.result().status_code for job in jobs)==[302,409]
