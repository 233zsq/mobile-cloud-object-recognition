"""New scope, immutable prior decisions and legacy public queue compatibility."""
import hashlib
import json
import re

import pytest

from test_review import admin, app, csrf, public_archive, review_body, upload
from test_workflow import connect
from campus_review import ROOT, create_app


@pytest.mark.parametrize('version', ['campus-10-v2', 'campus-10-v3'])
def test_v4_accepts_legacy_public_queue_only_as_pending(app, tmp_path, version):
    client = admin(app)
    archive = tmp_path / 'old-queue.zip'
    public_archive(app, archive, version)
    result = app.test_cli_runner().invoke(args=['import-public', str(archive)])
    assert result.exit_code == 0, result.output
    with connect(app) as db:
        assert db.execute('SELECT status,revision FROM samples').fetchone()[:] == ('pending', 1)
    page = client.get('/').text
    assert '<strong>伞</strong>' in page
    assert re.search(r'<option value="1"[^>]*>伞</option>', page)


def test_new_umbrella_scope_retains_old_rejection_until_manual_review_and_freezes_v4(app):
    archives = [ROOT.parent / 'shared/categories.json', ROOT.parent / 'shared/category-versions/campus-10-v3.json']
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in archives}
    legacy = create_app({key: app.config[key] for key in ('TESTING', 'SECRET_KEY', 'DATA_DIR', 'SESSION_COOKIE_SECURE')} |
                        {'CATEGORIES_FILE': archives[1]})
    old_client = admin(legacy)
    path = upload(old_client, '1')
    assert old_client.post(path, data=review_body(old_client, path, category='1', status='rejected', reason='庭院遮阳伞')).status_code == 302
    client = app.test_client()
    assert client.post('/login', data={'csrf': csrf(client), 'username': 'admin', 'password': 'a-strong-test-password'}).status_code == 302
    page = client.get(path).text
    assert re.search(r'<option value="1" selected>伞</option>', page)
    assert '手持遮阳伞及庭院或沙滩遮阳伞' in page
    with connect(app) as db:
        assert db.execute('SELECT status,reason,revision FROM samples').fetchone()[:] == ('rejected', '庭院遮阳伞', 2)
    assert client.post(path, data=review_body(client, path, '2', category='1', decision='approved', reason='按v4重新审核')).status_code == 302
    assert client.post('/batches', data={'csrf': csrf(client, '/'), 'version': 'umbrella-v4'}).status_code == 302
    with connect(app) as db:
        receipt = json.loads(db.execute('SELECT receipt FROM batches').fetchone()[0])
        reviews = [json.loads(r[0]) for r in db.execute('SELECT details FROM events WHERE action="review" ORDER BY id')]
    assert receipt['category_version'] == 'campus-10-v4'
    assert receipt['categories_sha256'] == hashlib.sha256((ROOT.parent / 'shared/category-versions/campus-10-v4.json').read_bytes()).hexdigest()
    assert reviews[0]['category_version'] == 'campus-10-v3' and reviews[0]['reason'] == '庭院遮阳伞'
    assert reviews[1]['category_version'] == 'campus-10-v4' and reviews[1]['status'] == 'approved'
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == value for p, value in hashes.items())
