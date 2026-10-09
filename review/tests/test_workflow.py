"""Real HTTP/SQLite checks for division of work and simultaneous reviewers."""
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from test_review import admin, app, csrf, join, lease, public_archive, review_body, upload


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


def assign(app, owner, category, username, revision='1'):
    with connect(app) as db:
        uid = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()[0]
    return owner.post('/assignments/' + str(category), data={
        'csrf': csrf(owner, '/'), 'reviewer_id': str(uid), 'revision': revision})


def test_assigned_members_default_to_their_category_and_cannot_edit_others(app):
    owner = admin(app)
    cups = member(app, owner, 'cup_reviewer')
    keyboards = member(app, owner, 'keyboard_reviewer')
    cup = upload(owner)
    keyboard = upload(owner, '5', 'blue')
    assert assign(app, owner, 0, 'cup_reviewer').status_code == 302
    assert assign(app, owner, 5, 'keyboard_reviewer').status_code == 302
    page = cups.get('/')
    assert cup in page.text and keyboard not in page.text
    assert 'scope=mine' in page.text and '物品类别' in page.text
    readonly = cups.get(keyboard)
    assert 'keyboard_reviewer' in readonly.text and '<fieldset disabled>' in readonly.text
    assert cups.post(keyboard, data=review_body(cups, keyboard, category='5')).status_code == 403
    assert cups.post('/assignments/0', data={'csrf': csrf(cups, '/'), 'reviewer_id': '', 'revision': '2'}).status_code == 403
    assert owner.post('/assignments/0', data={'csrf': csrf(owner, '/'), 'reviewer_id': '99999', 'revision': '2'}).status_code == 400
    assert cups.post(cup, data=review_body(cups, cup)).status_code == 302
    assert lease(keyboards, keyboard)


def test_active_claim_blocks_other_accounts_and_expired_claim_cannot_save(app):
    owner = admin(app)
    first = member(app, owner, 'first')
    second = member(app, owner, 'second')
    path = upload(owner)
    first_body = review_body(first, path)
    assert first_body['lease']
    page = second.get(path)
    assert '正在由 first 审核' in page.text and '<fieldset disabled>' in page.text
    assert second.post(path, data={**first_body, 'csrf': csrf(second, '/')}).status_code == 409
    with connect(app) as db:
        db.execute('UPDATE review_leases SET expires=?', (time.time() - 1,))
    second_body = review_body(second, path)
    assert second_body['lease'] != first_body['lease']
    assert first.post(path, data=first_body).status_code == 409
    assert second.post(path, data=second_body).status_code == 302
    with connect(app) as db:
        assert db.execute('SELECT revision FROM samples').fetchone()[0] == 2
        assert db.execute('SELECT COUNT(*) FROM events WHERE action="review"').fetchone()[0] == 1


def test_save_next_and_skip_keep_filters_even_after_relabeling(app, tmp_path):
    owner = admin(app)
    cups = member(app, owner, 'cups')
    field = {upload(owner, '0', color) for color in ('blue', 'green')}
    keyboard = upload(owner, '5', 'red')
    public = tmp_path / 'public.zip'; public_archive(app, public)
    assert app.test_cli_runner().invoke(args=['import-public', str(public)]).exit_code == 0
    assert assign(app, owner, 0, 'cups').status_code == 302
    query = '?category=0&source=field&scope=mine&status=pending'
    first = cups.get('/review/next' + query).headers['Location']
    assert urlparse(first).path in field
    response = cups.post(first, data=review_body(cups, first, category='5', action='next'))
    filters = parse_qs(urlparse(response.headers['Location']).query)
    assert {key: filters[key] for key in ('category', 'source', 'scope', 'status')} == {
        'category': ['0'], 'source': ['field'], 'scope': ['mine'], 'status': ['pending']}
    second = cups.get(response.headers['Location']).headers['Location']
    assert urlparse(second).path in field and urlparse(second).path != urlparse(first).path
    token = lease(cups, second)
    skipped = cups.post(urlparse(second).path + '/skip' + query,
                         data={'csrf': csrf(cups, '/'), 'lease': token, 'crop': 'invalid draft'})
    final = cups.get(skipped.headers['Location'], follow_redirects=True)
    assert '没有可领取的下一张' in final.text and keyboard not in final.text
    with connect(app) as db:
        assert db.execute('SELECT status FROM samples WHERE id=?', (urlparse(second).path.split('/')[-1],)).fetchone()[0] == 'pending'
        assert db.execute('SELECT COUNT(*) FROM review_leases').fetchone()[0] == 0


@pytest.mark.parametrize('count', [1, 2])
def test_parallel_next_requests_never_claim_the_same_photo(app, count):
    owner = admin(app)
    first = member(app, owner, 'first')
    second = member(app, owner, 'second')
    for color in ('blue', 'green')[:count]:
        upload(owner, color=color)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda client: client.get('/review/next?category=0'), (first, second)))
    claimed = [r.headers['Location'] for r in replies if r.headers['Location'].startswith('/samples/')]
    assert len(claimed) == len(set(claimed)) == count
    with connect(app) as db:
        assert db.execute('SELECT COUNT(*) FROM review_leases').fetchone()[0] == count


def test_reassignment_invalidates_drafts_without_admin_stealing_an_active_claim(app):
    owner = admin(app)
    first = member(app, owner, 'first')
    second = member(app, owner, 'second')
    path = upload(owner)
    assign(app, owner, 0, 'first')
    draft = review_body(first, path)
    assert assign(app, owner, 0, 'second', '2').status_code == 302
    assert first.post(path, data=draft).status_code == 403
    assert first.post(path + '/lease', data={'csrf': csrf(first, '/'), 'lease': draft['lease']}).status_code == 403
    second_body = review_body(second, path)
    assert '正在由 second 审核' in owner.get(path).text
    assert owner.post(path, data={**second_body, 'csrf': csrf(owner, '/')}).status_code == 409
    assert assign(app, owner, 0, 'first', '2').status_code == 409
    # Re-saving an unchanged assignment must not revoke an in-progress draft.
    assert assign(app, owner, 0, 'second', '3').status_code == 302
    assert second.post(path, data=second_body).status_code == 302


def test_heartbeat_release_and_logout_preserve_photo_content(app):
    owner = admin(app)
    other = member(app, owner, 'other')
    path = upload(owner)
    token = lease(owner, path)
    with connect(app) as db:
        db.execute('UPDATE review_leases SET expires=?', (time.time() + 1,))
    renewed = owner.post(path + '/lease', data={'csrf': csrf(owner, '/'), 'lease': token})
    assert renewed.status_code == 200 and renewed.json['expires'] > time.time() + 800
    assert other.post(path + '/release', data={'csrf': csrf(other, '/'), 'lease': token}).status_code == 204
    assert owner.post(path + '/release', data={'lease': token}).status_code == 400
    assert owner.post(path + '/release', data={'csrf': csrf(owner, '/'), 'lease': token}).status_code == 204
    replacement = lease(other, path)
    assert replacement and replacement != token
    assert other.post('/logout', data={'csrf': csrf(other, '/')}).status_code == 302
    with connect(app) as db:
        row = db.execute('SELECT revision,status FROM samples').fetchone()
        assert (row['revision'], row['status']) == (1, 'pending')
        assert db.execute('SELECT COUNT(*) FROM review_leases').fetchone()[0] == 0
