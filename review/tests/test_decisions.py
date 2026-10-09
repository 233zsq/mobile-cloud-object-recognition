"""Exercise quick review choices through the real page, database and audit log."""
import json
import re

import pytest

from test_review import admin, app, review_body, upload
from test_workflow import connect


def test_pending_page_defaults_to_approval_without_saving_and_keeps_controls_above_photo(app):
    client = admin(app)
    path = upload(client)
    page = client.get(path).text
    assert re.search(r'name="decision" value="approved" checked', page)
    assert page.index('aria-label="审核操作"') < page.index('class="crop-stage"')
    assert page.index('保存并审核下一个') < page.index('class="crop-stage"')
    assert '<details class="panel review-grouping">' in page
    with connect(app) as db:
        assert db.execute('SELECT status,revision FROM samples').fetchone()[:] == ('pending', 1)
        assert db.execute('SELECT COUNT(*) FROM events WHERE action="review"').fetchone()[0] == 0
    body = review_body(client, path, decision='approved', reason='')
    body.pop('status')  # The new native radio controls do not depend on JS or a hidden status.
    assert client.post(path, data=body).status_code == 302
    with connect(app) as db:
        assert db.execute('SELECT status,reason FROM samples').fetchone()[:] == ('approved', '')


@pytest.mark.parametrize('choice,note,expected', [
    ('occluded', '', '被遮挡'),
    ('wrong_item', '', '此物品不是对应物品'),
    ('occluded', '主体被包挡住', '被遮挡：主体被包挡住'),
    ('other', '主体过小，无法辨认', '主体过小，无法辨认'),
])
def test_quick_rejection_records_reason_and_preserves_choice_on_reopen(app, choice, note, expected):
    client = admin(app)
    path = upload(client)
    body = review_body(client, path, decision=choice, reason=note, action='next')
    assert client.post(path, data=body).status_code == 302
    with connect(app) as db:
        assert db.execute('SELECT status,reason FROM samples').fetchone()[:] == ('rejected', expected)
        record = json.loads(db.execute('SELECT details FROM events WHERE action="review"').fetchone()[0])
        assert record['decision'] == choice and record['reason'] == expected
    page = client.get(path).text
    assert f'name="decision" value="{choice}" checked' in page
    if note:
        assert note in page
    if choice == 'other':
        assert re.search(r'<textarea name="reason"[^>]* required', page)


def test_other_requires_reason_invalid_choices_fail_and_skip_does_not_save(app):
    client = admin(app)
    path = upload(client)
    body = review_body(client, path, decision='other', reason='')
    assert client.post(path, data=body).status_code == 400
    assert client.post(path, data={**body, 'decision': 'invalid'}).status_code == 400
    assert client.post(path, data={**body, 'decision': 'wrong_item', 'reason': '长' * 160}).status_code == 400
    assert client.post(path + '/skip', data=body).status_code == 302
    with connect(app) as db:
        assert db.execute('SELECT status,revision FROM samples').fetchone()[:] == ('pending', 1)
        assert db.execute('SELECT COUNT(*) FROM events WHERE action="review"').fetchone()[0] == 0


def test_old_rejection_is_preserved_and_defer_remains_pending(app):
    client = admin(app)
    path = upload(client)
    # Compatibility with pages opened before deployment.
    assert client.post(path, data=review_body(client, path, status='rejected', reason='旧版手工审核说明')).status_code == 302
    page = client.get(path).text
    assert 'name="decision" value="other" checked' in page and '旧版手工审核说明' in page
    assert client.post(path, data=review_body(client, path, '2', decision='pending', reason='需要复核')).status_code == 302
    with connect(app) as db:
        assert db.execute('SELECT status,reason,revision FROM samples').fetchone()[:] == ('pending', '需要复核', 3)
