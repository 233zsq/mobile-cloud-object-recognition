"""Small team photo review service. Training never runs in this process."""
import csv
import hashlib
import io
import json
import math
import os
import re
import secrets
import sqlite3
import time
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

import click
from flask import Flask, abort, current_app, flash, g, redirect, render_template, request, send_file, session, url_for
from PIL import Image, ImageOps
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.exceptions import SecurityError
from werkzeug.middleware.proxy_fix import ProxyFix
from .assets import PUBLIC_SOURCES, SOURCE_FIELDS, crop_box, renditions, source_metadata
from .decisions import CHOICES, initial_choice, resolve_choice
from .workflow import SCHEMA as WORKFLOW_SCHEMA, Workflow

ROOT = Path(__file__).resolve().parents[1]
Image.MAX_IMAGE_PIXELS = 16_000_000
IMAGE_LOCK = threading.Lock()
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
 password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','reviewer')), active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS invites(digest TEXT PRIMARY KEY, role TEXT NOT NULL, expires REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS samples(id TEXT PRIMARY KEY, owner INTEGER NOT NULL, filename TEXT NOT NULL,
 sha256 TEXT UNIQUE NOT NULL, category INTEGER NOT NULL, object_id TEXT NOT NULL, session_id TEXT NOT NULL,
 group_id TEXT NOT NULL, phash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', reason TEXT NOT NULL DEFAULT '',
 width INTEGER NOT NULL, height INTEGER NOT NULL, revision INTEGER NOT NULL DEFAULT 1, batch TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, actor INTEGER NOT NULL, action TEXT NOT NULL,
 subject TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY, receipt TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidates(version TEXT PRIMARY KEY, report TEXT NOT NULL, digest TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', decision TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts(key TEXT PRIMARY KEY, failures INTEGER NOT NULL, reset_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS egress(id INTEGER PRIMARY KEY CHECK(id=1), bytes INTEGER NOT NULL DEFAULT 0);
INSERT OR IGNORE INTO egress(id,bytes) VALUES(1,0);
"""


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def safe(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value or ''):
        abort(400, '名称仅限字母、数字、下划线和连字符（最多80位）')
    return value


def text(name, required=True):
    value = request.form.get(name, '').strip()
    if (required and not value) or len(value) > 160 or any(ord(c) < 32 for c in value):
        abort(400, f'{name} 必须填写，且不能超过160个字符')
    return value


def db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.extensions['review_data'] / 'review.sqlite3', timeout=30, isolation_level=None)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


def event(action, subject, details):
    db().execute('INSERT INTO events(actor,action,subject,details,created_at) VALUES(?,?,?,?,?)',
                 (g.user['id'], action, subject, json.dumps(details, ensure_ascii=False), stamp()))


def require(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not g.user:
                return redirect(url_for('login'))
            if role and g.user['role'] != role:
                abort(403, '此操作需要管理员权限')
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def perceptual(im):
    """DCT pHash compatible with recognition.data.phash, without NumPy on cloud."""
    a = list(ImageOps.exif_transpose(im).convert('L').resize((32, 32)).getdata())
    cosines = [[math.cos(math.pi * (n + .5) * k / 32) for n in range(32)] for k in range(8)]
    temp = [[sum(cosines[k][n] * a[n * 32 + x] for n in range(32)) for x in range(32)] for k in range(8)]
    low = [sum(temp[k][x] * cosines[j][x] for x in range(32)) for k in range(8) for j in range(8)]
    median = sorted(low[1:])[31]
    return f'{sum((v > median) << i for i, v in enumerate(low)):016x}'


def create_app(config=None):
    app = Flask(__name__)
    # The only production listener is loopback, behind our own Nginx site.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)
    app.config.update(SECRET_KEY=os.environ.get('REVIEW_SECRET_KEY'),
                      DATA_DIR=os.environ.get('REVIEW_DATA_DIR', str(ROOT / 'var')),
                      MAX_CONTENT_LENGTH=9 * 1024 * 1024,
                      SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Lax', PERMANENT_SESSION_LIFETIME=28800,
                      REVIEW_LEASE_SECONDS=900,
                      EGRESS_LIMIT_BYTES=int(float(os.environ.get('REVIEW_EGRESS_LIMIT_GIB', '20')) * 1024**3),
                      TRUSTED_HOSTS=['49.232.195.47', '127.0.0.1', 'localhost'])
    if config:
        app.config.update(config)
    if not app.secret_key or len(app.secret_key) < 32:
        raise ValueError('Set REVIEW_SECRET_KEY to at least 32 random characters')
    data = Path(app.config['DATA_DIR']).resolve()
    data.mkdir(parents=True, exist_ok=True)
    for name in ('images', 'previews', 'thumbs', 'details', 'batches'):
        (data / name).mkdir(exist_ok=True)
    categories_file = Path(app.config.get('CATEGORIES_FILE', ROOT.parent / 'shared/category-versions/campus-10-v4.json'))
    category_bytes = categories_file.read_bytes()
    cat = json.loads(category_bytes)
    queue_category_hashes = {sha(category_bytes)}
    mapping = lambda value: [(c['id'], c['label_key']) for c in value['categories']]
    # Old public queues contain suggestions only; all imported images need review.
    compatible = {('campus-10-v2', 'campus-10-v3'), ('campus-10-v2', 'campus-10-v4'),
                  ('campus-10-v3', 'campus-10-v4')}
    for legacy_file in (ROOT.parent / 'shared/categories.json', ROOT.parent / 'shared/category-versions/campus-10-v3.json'):
        legacy_bytes = legacy_file.read_bytes()
        legacy_cat = json.loads(legacy_bytes)
        if (legacy_cat['category_version'], cat['category_version']) in compatible and mapping(legacy_cat) == mapping(cat):
            queue_category_hashes.add(sha(legacy_bytes))
    baseline = json.loads((ROOT.parent / 'models/releases/campus-gpu-v1/metadata.json').read_text(encoding='utf-8'))
    base_metrics = json.loads((ROOT.parent / 'models/releases/campus-gpu-v1/evaluation-validation.json').read_text(encoding='utf-8'))['metrics']
    connection = sqlite3.connect(data / 'review.sqlite3')
    connection.execute('PRAGMA journal_mode=WAL')
    connection.executescript(SCHEMA + WORKFLOW_SCHEMA)
    connection.executemany('INSERT OR IGNORE INTO category_assignments(category) VALUES(?)', [(i,) for i in range(10)])
    columns = {r[1] for r in connection.execute('PRAGMA table_info(samples)')}
    for name, definition in (('source', "TEXT NOT NULL DEFAULT 'field'"),
                             ('source_meta', "TEXT NOT NULL DEFAULT '{}'"),
                             ('crop', "TEXT NOT NULL DEFAULT ''")):
        if name not in columns:
            connection.execute(f'ALTER TABLE samples ADD COLUMN {name} {definition}')
    connection.commit()
    connection.close()

    @app.before_request
    def context():
        g.app_data = data
        g.user = db().execute('SELECT * FROM users WHERE id=? AND active=1', (session.get('uid', -1),)).fetchone()
        session.setdefault('csrf', secrets.token_urlsafe(32))
        if request.method == 'POST' and not secrets.compare_digest(session['csrf'], request.form.get('csrf', '')):
            abort(400, '页面校验失败，请刷新后重试')

    @app.teardown_appcontext
    def close(_error):
        if conn := g.pop('db', None):
            conn.close()

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if request.endpoint == 'image' and response.status_code in (200, 304):
            response.headers['Cache-Control'] = 'private, no-cache'
            response.vary.add('Cookie')
        else:
            response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.context_processor
    def globals_():
        return {'categories': cat['categories'], 'csrf': session.get('csrf'),
                'baseline': baseline, 'base_metrics': base_metrics,
                'source_labels': {'field': '成员实拍', 'wikimedia_commons': 'Commons 网图', 'open_images': 'Open Images 网图'}}

    def workflow():
        return Workflow(db(), g.user, app.config['REVIEW_LEASE_SECONDS'])

    def budgeted_file(path, **kwargs):
        response = send_file(path, conditional=True, **kwargs)
        size = response.content_length or 0
        if request.method != 'HEAD' and response.status_code in (200, 206) and size:
            db().execute('BEGIN IMMEDIATE')
            changed = db().execute('UPDATE egress SET bytes=bytes+? WHERE id=1 AND bytes+?<=?',
                                   (size, size, app.config['EGRESS_LIMIT_BYTES'])).rowcount
            if not changed:
                db().rollback()
                response.close()
                abort(429, '审核资源累计流量预算已用完，请联系管理员核对服务器余量')
            db().commit()
        return response

    def store_photo(content, category, object_id, session_id, group_id, owner, meta=None):
        if len(content) > 8 * 1024**2:
            raise ValueError('单张照片最大8MiB')
        identity = sha(content)
        if db().execute('SELECT 1 FROM samples WHERE sha256=?', (identity,)).fetchone():
            raise ValueError('这张照片已经上传')
        sid = uuid.uuid4().hex
        with IMAGE_LOCK, Image.open(io.BytesIO(content)) as im:
            if im.format not in ('JPEG', 'PNG', 'WEBP') or getattr(im, 'n_frames', 1) != 1 or im.width * im.height > Image.MAX_IMAGE_PIXELS:
                raise ValueError('仅支持1600万像素以内的单帧 JPEG、PNG、WebP')
            im.load()
            corrected = ImageOps.exif_transpose(im).convert('RGB')
            width, height = corrected.size
            if min(width, height) < 128:
                raise ValueError('照片短边至少128像素')
            fingerprint = perceptual(im)
            ext = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}[im.format]
            renditions(corrected, data, sid)
        filename = sid + ext
        original = data / 'images' / filename
        original.write_bytes(content)
        try:
            db().execute('BEGIN IMMEDIATE')
            db().execute('INSERT INTO samples(id,owner,filename,sha256,category,object_id,session_id,group_id,phash,width,height,created_at,source,source_meta) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (sid, owner, filename, identity, category, object_id, session_id, group_id or sid,
                          fingerprint, width, height, stamp(), meta['source_dataset'] if meta else 'field',
                          json.dumps(meta or {}, ensure_ascii=False)))
            db().execute('INSERT INTO events(actor,action,subject,details,created_at) VALUES(?,?,?,?,?)',
                         (owner, 'public_import' if meta else 'upload', sid,
                          json.dumps({'sha256': identity, 'category': category}), stamp()))
            db().commit()
        except Exception:
            db().rollback()
            original.unlink(missing_ok=True)
            for name in ('thumbs', 'details'):
                (data / name / (sid + '.webp')).unlink(missing_ok=True)
            raise
        return sid

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(413)
    @app.errorhandler(429)
    def error(exc):
        if isinstance(exc, SecurityError):
            return 'Untrusted host', 400, {'Content-Type': 'text/plain; charset=utf-8'}
        if db().in_transaction:
            db().rollback()
        return render_template('error.html', message=exc.description, code=exc.code), exc.code

    @app.get('/health')
    def health():
        return {'status': 'ok', 'service': 'campus-review', 'baseline': baseline['model_version']}

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form.get('username', '')[:80]
            key = sha((request.remote_addr + ':' + username).encode())
            attempt = db().execute('SELECT * FROM login_attempts WHERE key=?', (key,)).fetchone()
            if attempt and attempt['reset_at'] > time.time() and attempt['failures'] >= 10:
                abort(429, '登录尝试过多，请15分钟后重试')
            user = db().execute('SELECT * FROM users WHERE username=? AND active=1', (username,)).fetchone()
            password = request.form.get('password', '')[:1024]
            if not user or not check_password_hash(user['password'], password):
                failures = attempt['failures'] + 1 if attempt and attempt['reset_at'] > time.time() else 1
                db().execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)', (key, failures, time.time() + 900))
                abort(403, '账号或密码错误')
            db().execute('DELETE FROM login_attempts WHERE key=?', (key,))
            session.clear()
            session.update(uid=user['id'], csrf=secrets.token_urlsafe(32))
            session.permanent = True
            return redirect(url_for('index'))
        return render_template('login.html')

    @app.post('/logout')
    def logout():
        if g.user:
            db().execute('DELETE FROM review_leases WHERE user_id=?', (g.user['id'],))
        session.clear()
        return redirect(url_for('login'))

    @app.route('/join/<token>', methods=['GET', 'POST'])
    def join(token):
        token_hash = sha(token.encode())
        invite = db().execute('SELECT * FROM invites WHERE digest=? AND consumed=0 AND expires>?', (token_hash, time.time())).fetchone()
        if not invite:
            abort(404, '邀请无效、已使用或已过期')
        if request.method == 'POST':
            username = safe(text('username'))
            password = text('password')
            if len(password) < 12:
                abort(400, '密码至少12个字符')
            db().execute('BEGIN IMMEDIATE')
            changed = db().execute('UPDATE invites SET consumed=1 WHERE digest=? AND consumed=0 AND expires>?', (token_hash, time.time())).rowcount
            if not changed:
                abort(409, '邀请已使用')
            try:
                db().execute('INSERT INTO users(username,password,role) VALUES(?,?,?)', (username, generate_password_hash(password), invite['role']))
            except sqlite3.IntegrityError:
                abort(409, '账号名已使用')
            db().commit()
            return redirect(url_for('login'))
        return render_template('join.html', role=invite['role'])

    @app.get('/')
    @require()
    def index():
        work = workflow()
        filters = work.filters(request.args)
        try:
            page = max(1, int(request.args.get('page', 1)))
        except ValueError:
            abort(400)
        samples, count, stats = work.listing(filters, page)
        return render_template('index.html', samples=samples, stats=stats, filters=filters, **filters,
                               assignments=work.assignments(), review_now=time.time(),
                               reviewers=db().execute('SELECT id,username FROM users WHERE active=1 ORDER BY username').fetchall(),
                               page=page, count=count, egress_bytes=db().execute('SELECT bytes FROM egress WHERE id=1').fetchone()[0],
                               egress_limit=app.config['EGRESS_LIMIT_BYTES'],
                               batches=db().execute('SELECT * FROM batches ORDER BY created_at DESC').fetchall(),
                               candidates=db().execute('SELECT * FROM candidates ORDER BY created_at DESC').fetchall())

    @app.get('/review/next')
    @require()
    def next_review():
        work = workflow()
        filters = work.filters(request.args)
        sid = work.next(filters, request.args.get('exclude', ''))
        if sid:
            return redirect(url_for('sample', sid=sid, **filters))
        flash('当前筛选下没有可领取的下一张照片：照片可能已审核、被占用或分配给其他成员。')
        return redirect(url_for('index', **filters))

    @app.post('/assignments/<int:category>')
    @require('admin')
    def assign_category(category):
        value = request.form.get('reviewer_id', '')
        try:
            reviewer_id = int(value) if value else None
        except ValueError:
            abort(400, '请选择有效的组员账号')
        workflow().assign(category, reviewer_id, request.form.get('revision', ''),
                          lambda old: event('assign_category', str(category), {'from': old, 'to': reviewer_id}))
        flash('品类分工已保存；改派后，原审核页面须重新领取。')
        return redirect(url_for('index') + '#assignments')

    @app.route('/upload', methods=['GET', 'POST'])
    @require()
    def upload():
        if request.method == 'POST':
            upload_file = request.files.get('image')
            if not upload_file:
                abort(400, '请选择照片')
            category = request.form.get('category', '')
            if category not in {str(i) for i in range(10)}:
                abort(400, '请选择类别')
            object_id, session_id = text('object_id'), text('session_id')
            content = upload_file.read(8 * 1024 * 1024 + 1)
            if len(content) > 8 * 1024 * 1024:
                abort(413, '单张照片最大8MiB')
            identity = sha(content)
            if db().execute('SELECT 1 FROM samples WHERE sha256=?', (identity,)).fetchone():
                abort(409, '这张照片已经上传，请在审核列表中查找')
            try:
                sid = store_photo(content, int(category), object_id, session_id, text('group_id', False), g.user['id'])
            except sqlite3.IntegrityError:
                abort(409, '这张照片已经上传')
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                abort(400, '照片无法接收：' + str(exc))
            return redirect(url_for('sample', sid=sid))
        return render_template('upload.html')

    @app.get('/images/<sid>')
    @require()
    def image(sid):
        row = db().execute('SELECT * FROM samples WHERE id=?', (sid,)).fetchone()
        if not row:
            abort(404)
        size = request.args.get('size', 'detail')
        if size not in ('thumb', 'detail'):
            abort(400)
        path = data / ('thumbs' if size == 'thumb' else 'details') / (safe(sid) + '.webp')
        if not path.exists():
            with IMAGE_LOCK, Image.open(data / 'images' / row['filename']) as im:
                renditions(ImageOps.exif_transpose(im).convert('RGB'), data, sid)
        return budgeted_file(path, mimetype='image/webp')

    @app.route('/samples/<sid>', methods=['GET', 'POST'])
    @require()
    def sample(sid):
        work = workflow()
        filters = work.filters(request.args)
        row = work.sample(sid)
        if request.method == 'POST':
            if row['batch']:
                abort(409, '照片已冻结，不能修改')
            if not work.allowed(row):
                abort(403, '该品类由其他成员负责，请联系管理员调整分工')
            intent = request.form.get('action', 'save')
            if intent not in ('save', 'next'):
                abort(400, '未知审核操作')
            status, reason = resolve_choice(request.form.get('decision'), request.form.get('status'), text('reason', False))
            category = request.form.get('category')
            if status not in ('pending', 'approved', 'rejected') or category not in {str(i) for i in range(10)}:
                abort(400)
            if status == 'rejected' and not reason:
                abort(400, '拒绝时请填写原因')
            object_id, session_id, group_id = text('object_id', row['source'] == 'field'), text('session_id'), text('group_id')
            crop = request.form.get('crop', row['crop'])
            if request.form.get('use_crop') and not crop:
                abort(400, '请先选择裁剪区域')
            try:
                crop_box(crop, row['width'], row['height'])
            except (ValueError, TypeError):
                abort(400, '裁剪坐标无效或原图裁剪区域小于128×128')
            work.save(sid, request.form.get('lease', ''), request.form.get('revision', ''),
                      (status, int(category), reason, object_id, session_id, group_id, crop),
                      lambda: event('review', sid, {'status': status, 'decision': request.form.get('decision'), 'category': category, 'category_version': cat['category_version'], 'reason': reason, 'object_id': object_id, 'session_id': session_id, 'group_id': group_id, 'crop': crop}))
            if intent == 'next':
                return redirect(url_for('next_review', exclude=sid, **filters))
            flash('审核已保存。')
            return redirect(url_for('sample', sid=sid, **filters))
        row, lease, notice = work.open(sid)
        related = [r for r in db().execute('SELECT * FROM samples WHERE id<>?', (sid,)) if (row['object_id'] and r['object_id'] == row['object_id']) or r['group_id'] == row['group_id'] or (int(r['phash'], 16) ^ int(row['phash'], 16)).bit_count() <= 6]
        history = db().execute('SELECT e.*,u.username FROM events e JOIN users u ON e.actor=u.id WHERE subject=? ORDER BY e.id DESC', (sid,)).fetchall()
        decision, review_note = initial_choice(row)
        return render_template('sample.html', sample=row, lease=lease, notice=notice, filters=filters,
                               decision=decision, decision_choices=CHOICES, review_note=review_note,
                               source_meta=json.loads(row['source_meta']), related=related[:20], history=history)

    @app.post('/samples/<sid>/skip')
    @require()
    def skip_sample(sid):
        filters = workflow().filters(request.args)
        workflow().release(sid, request.form.get('lease', ''))
        return redirect(url_for('next_review', exclude=sid, **filters))

    @app.post('/samples/<sid>/lease')
    @require()
    def renew_lease(sid):
        return {'expires': workflow().renew(sid, request.form.get('lease', ''))}

    @app.post('/samples/<sid>/release')
    @require()
    def release_lease(sid):
        workflow().release(sid, request.form.get('lease', ''))
        return '', 204

    @app.post('/batches')
    @require('admin')
    def freeze():
        batch_id = safe(text('version'))
        db().execute('BEGIN IMMEDIATE')
        rows = db().execute("SELECT s.*,u.username FROM samples s JOIN users u ON s.owner=u.id WHERE s.status='approved' AND s.batch IS NULL ORDER BY s.id").fetchall()
        if not rows:
            abort(400, '没有待冻结的已通过照片')
        if db().execute('SELECT 1 FROM batches WHERE id=?', (batch_id,)).fetchone():
            abort(409, '批次版本已存在')
        labels = {}
        for row in rows:
            for field in ('object_id', 'group_id'):
                if row[field]:
                    labels.setdefault((field, row[field]), set()).add(row['category'])
        if any(len(values)>1 for values in labels.values()):
            abort(409, '同一实物或重复组出现多个类别，请先复核标签')
        manifests = []
        for row in rows:
            if file_sha(data / 'images' / row['filename']) != row['sha256']:
                abort(409, '原照片哈希发生变化，冻结中止')
            manifests.append({'sample_id': row['id'], 'image_path': 'images/' + row['filename'], 'image_sha256': row['sha256'],
                              'category_id': row['category'], 'object_id': row['object_id'], 'session_id': row['session_id'],
                              'group_id': row['group_id'], 'phash': row['phash'], 'collector': row['username'], 'captured_at': row['created_at'] if row['source']=='field' else '',
                              'review_status': 'approved', 'review_reason': row['reason'],
                              **{key: json.loads(row['source_meta']).get(key, '') for key in SOURCE_FIELDS if key != 'previous_review_reason'},
                              'source_dataset': row['source'], 'source_sample_id': json.loads(row['source_meta']).get('sample_id', ''),
                              'crop_box': json.dumps(crop_box(row['crop'], row['width'], row['height'])) if row['crop'] else '',
                              'width': row['width'], 'height': row['height']})
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=list(manifests[0]))
        writer.writeheader(); writer.writerows(manifests)
        manifest_bytes = stream.getvalue().encode('utf-8')
        receipt = {'schema_version': 1, 'purpose': 'training_only', 'batch_id': batch_id, 'created_at': stamp(),
                   'category_version': cat['category_version'], 'categories_sha256': sha(category_bytes),
                   'count': len(rows), 'files': {'samples.csv': sha(manifest_bytes), **{r['image_path']: r['image_sha256'] for r in manifests}}}
        archive = data / 'batches' / (batch_id + '.zip')
        temp = archive.with_suffix('.tmp')
        with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_STORED) as package:
            package.writestr('batch.json', encode(receipt))
            package.writestr('samples.csv', manifest_bytes)
            for row in rows:
                package.write(data / 'images' / row['filename'], 'images/' + row['filename'])
        temp.replace(archive)
        receipt['archive_sha256'] = file_sha(archive)
        db().execute('INSERT INTO batches VALUES(?,?,?)', (batch_id, encode(receipt).decode(), stamp()))
        db().executemany('UPDATE samples SET batch=?,revision=revision+1 WHERE id=?', [(batch_id, r['id']) for r in rows])
        db().execute('DELETE FROM review_leases WHERE sample_id IN (SELECT id FROM samples WHERE batch=?)', (batch_id,))
        event('freeze', batch_id, receipt)
        db().commit()
        return redirect(url_for('index', status='approved'))

    @app.get('/batches/<version>.zip')
    @require('admin')
    def download(version):
        row = db().execute('SELECT * FROM batches WHERE id=?', (safe(version),)).fetchone()
        if not row:
            abort(404)
        archive = data / 'batches' / (version + '.zip')
        if file_sha(archive) != json.loads(row['receipt'])['archive_sha256']:
            abort(409, '批次包哈希错误')
        return budgeted_file(archive, as_attachment=True)

    @app.post('/invites')
    @require('admin')
    def invite():
        token = secrets.token_urlsafe(32)
        db().execute('INSERT INTO invites VALUES(?,?,?,0)', (sha(token.encode()), 'reviewer', time.time() + 7 * 86400))
        event('invite', 'reviewer', {'expires_days': 7})
        return render_template('invite.html', link=url_for('join', token=token, _external=True))

    @app.get('/candidates/<version>')
    @require()
    def candidate(version):
        row = db().execute('SELECT * FROM candidates WHERE version=?', (version,)).fetchone()
        if not row:
            abort(404)
        return render_template('candidate.html', candidate=row, report=json.loads(row['report']))

    @app.get('/candidates/<version>/report.json')
    @require()
    def candidate_report(version):
        row = db().execute('SELECT * FROM candidates WHERE version=?', (version,)).fetchone()
        if not row:
            abort(404)
        return send_file(io.BytesIO(row['report'].encode()), mimetype='application/json', as_attachment=True, download_name=version+'-comparison.json')

    @app.post('/candidates/<version>/decision')
    @require('admin')
    def decision(version):
        choice, reason = request.form.get('decision'), text('reason')
        if choice not in ('approved', 'rejected'):
            abort(400)
        db().execute('BEGIN IMMEDIATE')
        row = db().execute('SELECT * FROM candidates WHERE version=?', (version,)).fetchone()
        if not row or row['digest'] != request.form.get('digest') or row['status'] != 'pending':
            abort(409, '候选记录已变化或已经审批')
        db().execute('UPDATE candidates SET status=?,decision=? WHERE version=?', (choice, reason, version))
        event('model_' + choice, version, {'report_sha256': row['digest'], 'model_sha256': json.loads(row['report'])['candidate']['sha256'], 'reason': reason})
        db().commit()
        return redirect(url_for('candidate', version=version))

    @app.get('/candidates/<version>/approval.json')
    @require('admin')
    def approval(version):
        row = db().execute('SELECT * FROM candidates WHERE version=?', (version,)).fetchone()
        if not row or row['status'] != 'approved':
            abort(409, '此模型尚未批准')
        record = db().execute("SELECT e.*,u.username FROM events e JOIN users u ON e.actor=u.id WHERE action='model_approved' AND subject=? ORDER BY e.id DESC LIMIT 1", (version,)).fetchone()
        receipt = {'model_version': version, 'model_sha256': json.loads(row['report'])['candidate']['sha256'],
                   'status': 'approved', 'report_sha256': row['digest'], 'approved_by': record['username'],
                   'approved_at': record['created_at'], 'reason': row['decision']}
        return send_file(io.BytesIO(encode(receipt)), mimetype='application/json', as_attachment=True, download_name=version+'-approval.json')

    @app.cli.command('bootstrap')
    def bootstrap():
        """Create an initial admin invitation, never a hardcoded password."""
        if db().execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
            raise click.ClickException('Admin already exists')
        token = secrets.token_urlsafe(32)
        db().execute('INSERT INTO invites VALUES(?,?,?,0)', (sha(token.encode()), 'admin', time.time() + 86400))
        click.echo('/join/' + token)

    @app.cli.command('import-public')
    @click.argument('archive_file', type=click.Path(exists=True, path_type=Path))
    @click.option('--report', type=click.Path(path_type=Path))
    def import_public(archive_file, report):
        """Import bounded, locally collected sources as pending; no remote URL fetch."""
        summary = {'imported': 0, 'skipped_existing': 0, 'rejected': [], 'at': stamp()}
        with zipfile.ZipFile(archive_file) as package:
            infos = package.infolist()
            names = [i.filename for i in infos]
            if len(names) != len(set(names)) or len(names) > 3002 or sum(i.file_size for i in infos) > 3 * 1024**3:
                raise click.ClickException('Public archive budget exceeded')
            if any(i.file_size > 8 * 1024**2 or i.filename.startswith('/') or '\\' in i.filename or '..' in Path(i.filename).parts for i in infos):
                raise click.ClickException('Unsafe public archive path or size')
            receipt = json.loads(package.read('queue.json'))
            if receipt.get('purpose') != 'public_review_queue' or receipt.get('categories_sha256') not in queue_category_hashes:
                raise click.ClickException('Public queue purpose/categories differ')
            if set(names) != {'queue.json', *receipt['files']} or sha(package.read('samples.csv')) != receipt['files']['samples.csv']:
                raise click.ClickException('Public queue file identity differs')
            rows = list(csv.DictReader(io.StringIO(package.read('samples.csv').decode('utf-8-sig'))))
            if len(rows) != receipt['count'] or set(receipt['files']) != {'samples.csv', *[r['image_path'] for r in rows]}:
                raise click.ClickException('Public queue manifest differs')
            owner = db().execute("SELECT id FROM users WHERE username='@public-import' AND active=0").fetchone()
            if not owner:
                db().execute("INSERT INTO users(username,password,role,active) VALUES(?,?,'reviewer',0)",
                             ('@public-import', generate_password_hash(secrets.token_urlsafe(32))))
                owner = db().execute("SELECT id FROM users WHERE username='@public-import'").fetchone()
            for index, row in enumerate(rows):
                try:
                    path = Path(row['image_path'])
                    if len(path.parts) != 2 or path.parts[0] != 'images' or int(row['category_id']) not in range(10):
                        raise ValueError('Invalid image path/category')
                    content = package.read(row['image_path'])
                    if sha(content) != row['image_sha256'] or sha(content) != receipt['files'][row['image_path']]:
                        raise ValueError('Public photo hash differs')
                    if db().execute('SELECT 1 FROM samples WHERE sha256=?', (row['image_sha256'],)).fetchone():
                        summary['skipped_existing'] += 1
                        continue
                    meta = source_metadata(row)
                    meta['sample_id'] = safe(row['sample_id'])
                    object_id, group_id = row.get('object_id', ''), row.get('group_id') or row['sample_id']
                    if len(object_id) > 160 or len(group_id) > 160:
                        raise ValueError('Identity too long')
                    store_photo(content, int(row['category_id']), object_id, 'public-collection', group_id, owner['id'], meta)
                    summary['imported'] += 1
                except (OSError, ValueError, Image.DecompressionBombError) as exc:
                    summary['rejected'].append({'sample_id': row.get('sample_id'), 'reason': str(exc)[:180]})
                if (index + 1) % 100 == 0:
                    click.echo(f"Processed {index+1}/{len(rows)}")
        if report:
            report.write_bytes(encode(summary))
        click.echo(json.dumps(summary, ensure_ascii=False))

    @app.cli.command('register-candidate')
    @click.argument('report_file', type=click.Path(exists=True, path_type=Path))
    def register_candidate(report_file):
        """Import a locally verified comparison, never execute training on cloud."""
        report_bytes = report_file.read_bytes()
        report = json.loads(report_bytes)
        candidate_meta = report['candidate']
        version = safe(candidate_meta['model_version'])
        if report.get('purpose') != 'evolution_comparison' or report.get('status') != 'pending_human_approval' or report['baseline']['sha256'] != baseline['sha256'] or candidate_meta['status'] != 'frozen' or candidate_meta['sha256'] == baseline['sha256']:
            raise click.ClickException('A verified distinct frozen candidate and matching baseline are required')
        if not re.fullmatch('[0-9a-f]{64}', candidate_meta['sha256']):
            raise click.ClickException('Invalid candidate hash')
        existing = db().execute('SELECT digest FROM candidates WHERE version=?', (version,)).fetchone()
        if existing:
            if existing['digest'] != sha(report_bytes):
                raise click.ClickException('Candidate version is immutable')
            return
        db().execute('INSERT INTO candidates(version,report,digest,created_at) VALUES(?,?,?,?)', (version, report_bytes.decode(), sha(report_bytes), stamp()))
        click.echo('Registered pending candidate ' + version)

    # All callers, including Flask CLI, use the same persistent location.
    @app.teardown_request
    def rollback(_exc):
        if 'db' in g and g.db.in_transaction:
            g.db.rollback()

    app.extensions['review_data'] = data
    return app
