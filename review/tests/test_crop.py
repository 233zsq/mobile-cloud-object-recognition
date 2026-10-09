"""Direct drawing must not require cropping or change immutable source photos."""
import csv
import hashlib
import io
import json
import re
import zipfile

import pytest

from test_review import admin, app, csrf, review_body, upload
from test_workflow import connect


@pytest.mark.parametrize(('draw', 'selection', 'expected'), [
    ('on', '', ''),
    ('on', '[0,0,8000,8000]', '[0,0,8000,8000]'),
    ('', '[0,0,8000,8000]', ''),
])
def test_direct_drawing_save_and_freeze(app, draw, selection, expected):
    owner = admin(app)
    path = upload(owner)
    page = owner.get(path).text
    assert re.search(r'id="crop-enabled"[^>]*name="draw_crop"[^>]*checked', page)
    assert 'name="crop_mode" type="hidden" value="direct"' in page
    assert 'id="crop-clear"' in page
    with connect(app) as db:
        original_hash = db.execute('SELECT sha256 FROM samples').fetchone()[0]
    response = owner.post(path, data=review_body(owner, path, crop_mode='direct', draw_crop=draw, crop=selection))
    assert response.status_code == 302
    with connect(app) as db:
        row = db.execute('SELECT crop,sha256 FROM samples').fetchone()
        assert row['crop'] == expected and row['sha256'] == original_hash
    assert owner.post('/batches', data={'csrf': csrf(owner, '/'), 'version': 'direct-crop'}).status_code == 302
    with zipfile.ZipFile(io.BytesIO(owner.get('/batches/direct-crop.zip').data)) as package:
        row = next(csv.DictReader(io.StringIO(package.read('samples.csv').decode())))
        assert (json.loads(row['crop_box']) if row['crop_box'] else None) == ([0, 0, 160, 160] if expected else None)
        assert hashlib.sha256(package.read(row['image_path'])).hexdigest() == original_hash
    frozen = owner.get(path).text
    assert '<fieldset disabled>' in frozen and 'data-editable="false"' in frozen


def test_invalid_crops_and_legacy_empty_selection_still_rejected(app):
    owner = admin(app)
    path = upload(owner)
    for changes in (
        {'use_crop': 'on', 'crop': ''},
        {'crop_mode': 'unknown', 'crop': ''},
        {'crop_mode': 'direct', 'draw_crop': 'on', 'crop': '[0,0,100,100]'},
    ):
        assert owner.post(path, data=review_body(owner, path, **changes)).status_code == 400
    with connect(app) as db:
        row = db.execute('SELECT status,revision,crop FROM samples').fetchone()
        assert (row['status'], row['revision'], row['crop']) == ('pending', 1, '')
