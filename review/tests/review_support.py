"""HTTP, SQLite and AI fakes shared by review tests, independent of collection order."""
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import zipfile

from PIL import Image
from campus_review import ai_review as ai, ai_triage as triage


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

def photo(color='orange'):
    stream = io.BytesIO()
    Image.new('RGB', (200, 200), color).save(stream, 'JPEG')
    stream.seek(0)
    return stream

def upload(client, category='0', color='orange'):
    response = client.post('/upload', data={'csrf': csrf(client, '/upload'), 'image': (photo(color), '../../evil.jpg'),
                           'object_id': 'cup-01', 'session_id': 'lab-01', 'category': category})
    assert response.status_code == 302
    return response.headers['Location']

def lease(client, path):
    return re.search(r'name="lease"[^>]*value="([^"]*)"', client.get(path).text).group(1)

def review_body(client, path, revision='1', **changes):
    return {'csrf': csrf(client, path), 'lease': lease(client, path), 'revision': revision,
            'category': '0', 'status': 'approved', 'object_id': 'cup-01', 'session_id': 'lab-01',
            'group_id': 'series-01', 'reason': 'clear cup', **changes}

def review(client, path, revision='1'):
    return client.post(path, data=review_body(client, path, revision))

def public_archive(app, path, category_version='campus-10-v2', source='wikimedia_commons'):
    content = photo().getvalue()
    row = {'sample_id': 'commons-test', 'image_path': 'images/test.jpg',
           'image_sha256': hashlib.sha256(content).hexdigest(), 'category_id': '0', 'group_id': 'web-group',
           'source_dataset': 'wikimedia_commons', 'source_id': 'test', 'source_url': 'https://commons.wikimedia.org/wiki/File:Test.jpg',
           'original_url': 'https://upload.wikimedia.org/test.jpg', 'license': 'CC BY-SA 4.0', 'author': 'Test author'}
    if source == 'web_product':
        row.update(source_dataset=source, source_url='https://detail.1688.com/offer/123.html',
                   original_url='https://cbu01.alicdn.com/test.jpg', author='',
                   license='unverified (product photo; permission not established)')
    stream = io.StringIO(newline=''); writer = csv.DictWriter(stream, fieldnames=list(row))
    writer.writeheader(); writer.writerow(row); payload = stream.getvalue().encode()
    from campus_review import ROOT
    receipt = {'purpose': 'public_review_queue', 'count': 1,
               'categories_sha256': hashlib.sha256((ROOT.parent / ('shared/categories.json' if category_version=='campus-10-v2' else 'shared/category-versions/'+category_version+'.json')).read_bytes()).hexdigest(),
               'files': {'samples.csv': hashlib.sha256(payload).hexdigest(), row['image_path']: row['image_sha256']}}
    with zipfile.ZipFile(path, 'w') as package:
        package.writestr('queue.json', json.dumps(receipt)); package.writestr('samples.csv', payload)
        package.writestr(row['image_path'], content)
    return content


def member(app, owner, name):
    response = owner.post('/invites', data={'csrf': csrf(owner, '/')})
    invite = re.search(r'https?://[^/]+(/join/[^"<>]+)', response.text).group(1)
    client = app.test_client()
    assert join(client, invite, name).status_code == 302
    assert client.post('/login', data={'csrf': csrf(client), 'username': name,
                                      'password': 'a-strong-test-password'}).status_code == 302
    return client

def connect(app):
    connection = sqlite3.connect(Path(app.config['DATA_DIR']) / 'review.sqlite3')
    connection.row_factory = sqlite3.Row
    return connection


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


def prepare(app, owner):
    row = public_sample(app, owner)
    app.config.update(REVIEW_TRIAGE_PRIMARY_MODEL='qwen3.8-flash', REVIEW_TRIAGE_POLICY='', REVIEW_AI_BUDGET_NANO=30_000_000_000,
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
