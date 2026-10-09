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
from flask import Flask, abort, current_app, g, redirect, render_template, request, send_file, session, url_for
from PIL import Image, ImageOps
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.exceptions import SecurityError
from werkzeug.middleware.proxy_fix import ProxyFix

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
                      TRUSTED_HOSTS=['49.232.195.47', '127.0.0.1', 'localhost'])
    if config:
        app.config.update(config)
    if not app.secret_key or len(app.secret_key) < 32:
        raise ValueError('Set REVIEW_SECRET_KEY to at least 32 random characters')
    data = Path(app.config['DATA_DIR']).resolve()
    data.mkdir(parents=True, exist_ok=True)
    for name in ('images', 'previews', 'batches'):
        (data / name).mkdir(exist_ok=True)
    categories_file = Path(app.config.get('CATEGORIES_FILE', ROOT.parent / 'shared/categories.json'))
    category_bytes = categories_file.read_bytes()
    cat = json.loads(category_bytes)
    baseline = json.loads((ROOT.parent / 'models/releases/campus-gpu-v1/metadata.json').read_text(encoding='utf-8'))
    base_metrics = json.loads((ROOT.parent / 'models/releases/campus-gpu-v1/evaluation-validation.json').read_text(encoding='utf-8'))['metrics']
    connection = sqlite3.connect(data / 'review.sqlite3')
    connection.execute('PRAGMA journal_mode=WAL')
    connection.executescript(SCHEMA)
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
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.context_processor
    def globals_():
        return {'categories': cat['categories'], 'csrf': session.get('csrf'),
                'baseline': baseline, 'base_metrics': base_metrics}

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
        status = request.args.get('status', 'pending')
        if status not in ('pending', 'approved', 'rejected', 'all'):
            abort(400, '未知筛选')
        try:
            page = max(1, int(request.args.get('page', 1)))
        except ValueError:
            abort(400)
        where = '' if status == 'all' else 'WHERE status=?'
        args = () if status == 'all' else (status,)
        count = db().execute(f'SELECT COUNT(*) FROM samples {where}', args).fetchone()[0]
        samples = db().execute(f'SELECT * FROM samples {where} ORDER BY created_at DESC,id LIMIT 24 OFFSET ?', (*args, (page - 1) * 24)).fetchall()
        stats = dict(db().execute('SELECT status,COUNT(*) FROM samples GROUP BY status').fetchall())
        return render_template('index.html', samples=samples, stats=stats, status=status, page=page, count=count,
                               batches=db().execute('SELECT * FROM batches ORDER BY created_at DESC').fetchall(),
                               candidates=db().execute('SELECT * FROM candidates ORDER BY created_at DESC').fetchall())

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
                with IMAGE_LOCK, Image.open(io.BytesIO(content)) as im:
                    if im.format not in ('JPEG', 'PNG', 'WEBP') or getattr(im, 'n_frames', 1) != 1:
                        raise ValueError('仅支持单帧 JPEG、PNG、WebP')
                    if im.width * im.height > Image.MAX_IMAGE_PIXELS:
                        raise ValueError('照片超过1600万像素')
                    im.load()
                    corrected = ImageOps.exif_transpose(im).convert('RGB')
                    width, height = corrected.size
                    if min(width, height) < 128:
                        raise ValueError('照片短边至少128像素')
                    fingerprint = perceptual(im)
                    corrected.thumbnail((960, 960))
                    preview = io.BytesIO()
                    corrected.save(preview, 'JPEG', quality=85)
                    ext = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}[im.format]
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                abort(400, '照片无法接收：' + str(exc))
            sid = uuid.uuid4().hex
            filename = sid + ext
            original = data / 'images' / filename
            thumb = data / 'previews' / (sid + '.jpg')
            original.write_bytes(content)
            thumb.write_bytes(preview.getvalue())
            try:
                db().execute('BEGIN IMMEDIATE')
                db().execute('INSERT INTO samples(id,owner,filename,sha256,category,object_id,session_id,group_id,phash,width,height,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                             (sid, g.user['id'], filename, identity, int(category), object_id, session_id, text('group_id', False) or sid, fingerprint, width, height, stamp()))
                event('upload', sid, {'sha256': identity, 'category': int(category)})
                db().commit()
            except Exception:
                db().rollback()
                original.unlink(missing_ok=True)
                thumb.unlink(missing_ok=True)
                if db().execute('SELECT 1 FROM samples WHERE sha256=?', (identity,)).fetchone():
                    abort(409, '这张照片已经上传')
                raise
            return redirect(url_for('sample', sid=sid))
        return render_template('upload.html')

    @app.get('/images/<sid>')
    @require()
    def image(sid):
        if not db().execute('SELECT 1 FROM samples WHERE id=?', (sid,)).fetchone():
            abort(404)
        return send_file(data / 'previews' / (safe(sid) + '.jpg'), mimetype='image/jpeg')

    @app.route('/samples/<sid>', methods=['GET', 'POST'])
    @require()
    def sample(sid):
        row = db().execute('SELECT * FROM samples WHERE id=?', (sid,)).fetchone()
        if not row:
            abort(404)
        if request.method == 'POST':
            if row['batch']:
                abort(409, '照片已冻结，不能修改')
            status = request.form.get('status')
            category = request.form.get('category')
            reason = text('reason', False)
            if status not in ('pending', 'approved', 'rejected') or category not in {str(i) for i in range(10)}:
                abort(400)
            if status == 'rejected' and not reason:
                abort(400, '拒绝时请填写原因')
            object_id, session_id, group_id = text('object_id'), text('session_id'), text('group_id')
            db().execute('BEGIN IMMEDIATE')
            changed = db().execute('UPDATE samples SET status=?,category=?,reason=?,object_id=?,session_id=?,group_id=?,revision=revision+1 WHERE id=? AND revision=? AND batch IS NULL',
                                   (status, int(category), reason, object_id, session_id, group_id, sid, request.form.get('revision', ''))).rowcount
            if not changed:
                abort(409, '其他成员已更新照片，刷新页面后再审核')
            event('review', sid, {'status': status, 'category': category, 'reason': reason, 'object_id': object_id, 'session_id': session_id, 'group_id': group_id})
            db().commit()
            return redirect(url_for('sample', sid=sid))
        related = [r for r in db().execute('SELECT * FROM samples WHERE id<>?', (sid,)) if r['object_id'] == row['object_id'] or r['group_id'] == row['group_id'] or (int(r['phash'], 16) ^ int(row['phash'], 16)).bit_count() <= 6]
        history = db().execute('SELECT e.*,u.username FROM events e JOIN users u ON e.actor=u.id WHERE subject=? ORDER BY e.id DESC', (sid,)).fetchall()
        return render_template('sample.html', sample=row, related=related[:20], history=history)

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
                labels.setdefault((field, row[field]), set()).add(row['category'])
        if any(len(values)>1 for values in labels.values()):
            abort(409, '同一实物或重复组出现多个类别，请先复核标签')
        manifests = []
        for row in rows:
            if file_sha(data / 'images' / row['filename']) != row['sha256']:
                abort(409, '原照片哈希发生变化，冻结中止')
            manifests.append({'sample_id': row['id'], 'image_path': 'images/' + row['filename'], 'image_sha256': row['sha256'],
                              'category_id': row['category'], 'object_id': row['object_id'], 'session_id': row['session_id'],
                              'group_id': row['group_id'], 'phash': row['phash'], 'collector': row['username'], 'captured_at': row['created_at'],
                              'review_status': 'approved', 'review_reason': row['reason'], 'source_dataset': 'field',
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
        return send_file(archive, as_attachment=True)

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
