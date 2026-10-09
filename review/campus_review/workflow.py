"""Category ownership and expiring, atomic photo claims for human review."""
import secrets
import time
from contextlib import contextmanager

from werkzeug.exceptions import BadRequest, Conflict, Forbidden, NotFound

SCHEMA = '''
CREATE TABLE IF NOT EXISTS category_assignments(
 category INTEGER PRIMARY KEY CHECK(category BETWEEN 0 AND 9),
 reviewer_id INTEGER REFERENCES users(id), revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS review_leases(
 sample_id TEXT PRIMARY KEY REFERENCES samples(id), user_id INTEGER NOT NULL REFERENCES users(id),
 token TEXT NOT NULL, expires REAL NOT NULL);
CREATE INDEX IF NOT EXISTS review_leases_expiry ON review_leases(expires);
'''
JOIN = '''FROM samples s
LEFT JOIN category_assignments a ON a.category=s.category
LEFT JOIN users assigned ON assigned.id=a.reviewer_id
LEFT JOIN review_leases l ON l.sample_id=s.id
LEFT JOIN users holder ON holder.id=l.user_id'''


class Workflow:
    def __init__(self, connection, user, ttl=900):
        self.db, self.user, self.ttl = connection, user, ttl

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def filters(self, params):
        assigned = self.db.execute('SELECT 1 FROM category_assignments WHERE reviewer_id=?',
                                   (self.user['id'],)).fetchone()
        default_scope = 'mine' if assigned and self.user['role'] != 'admin' else 'all'
        value = {key: params.get(key, default) for key, default in (
            ('status', 'pending'), ('source', 'all'), ('category', ''), ('scope', default_scope))}
        if (value['status'] not in ('pending', 'approved', 'rejected', 'all') or
                value['source'] not in ('all', 'field', 'wikimedia_commons', 'open_images') or
                value['category'] not in ('', *map(str, range(10))) or
                value['scope'] not in ('mine', 'all', 'unassigned')):
            raise BadRequest('未知筛选条件')
        return value

    def selection(self, filters, ignore_status=False):
        clauses, args = [], []
        for field, default in (('status', 'all'), ('source', 'all'), ('category', '')):
            if (field != 'status' or not ignore_status) and filters[field] != default:
                clauses.append('s.' + field + '=?')
                args.append(filters[field])
        if filters['scope'] == 'mine':
            clauses.append('a.reviewer_id=?'); args.append(self.user['id'])
        elif filters['scope'] == 'unassigned':
            clauses.append('a.reviewer_id IS NULL')
        return clauses, args

    def listing(self, filters, page):
        clauses, args = self.selection(filters)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        count = self.db.execute('SELECT COUNT(*) ' + JOIN + where, args).fetchone()[0]
        rows = self.db.execute('''SELECT s.*,assigned.username AS assigned_to,
            a.reviewer_id,l.user_id AS lease_user,holder.username AS lease_owner,l.expires AS lease_expires ''' +
            JOIN + where + ' ORDER BY s.created_at DESC,s.id LIMIT 24 OFFSET ?',
            (*args, (page - 1) * 24)).fetchall()
        clauses, args = self.selection(filters, ignore_status=True)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        stats = dict(self.db.execute('SELECT s.status,COUNT(*) ' + JOIN + where + ' GROUP BY s.status', args).fetchall())
        return rows, count, stats

    def assignments(self):
        return self.db.execute('''SELECT a.*,u.username,
            (SELECT COUNT(*) FROM samples s WHERE s.category=a.category AND s.status='pending') AS pending
            FROM category_assignments a LEFT JOIN users u ON u.id=a.reviewer_id ORDER BY a.category''').fetchall()

    def allowed(self, row):
        return self.user['role'] == 'admin' or row['reviewer_id'] in (None, self.user['id'])

    def sample(self, sid):
        row = self.db.execute('SELECT s.*,a.reviewer_id,assigned.username AS assigned_to ' +
                              JOIN + ' WHERE s.id=?', (sid,)).fetchone()
        if not row:
            raise NotFound('照片不存在')
        return row

    def _claim(self, sid):
        existing = self.db.execute('SELECT l.*,u.username FROM review_leases l JOIN users u ON u.id=l.user_id WHERE sample_id=?',
                                    (sid,)).fetchone()
        now = time.time()
        if existing and existing['expires'] > now and existing['user_id'] != self.user['id']:
            return None, '正在由 ' + existing['username'] + ' 审核，请选择其他照片。'
        token = existing['token'] if existing and existing['user_id'] == self.user['id'] and existing['expires'] > now else secrets.token_urlsafe(24)
        expires = now + self.ttl
        self.db.execute('INSERT OR REPLACE INTO review_leases VALUES(?,?,?,?)',
                        (sid, self.user['id'], token, expires))
        return {'token': token, 'expires': expires}, ''

    def open(self, sid):
        with self.transaction():
            row = self.sample(sid)
            if row['batch']:
                return row, None, '照片已冻结，仅供查看。'
            if not self.allowed(row):
                return row, None, '该品类由 ' + row['assigned_to'] + ' 负责，你可以查看；修改请联系管理员调整分工。'
            lease, notice = self._claim(sid)
            return row, lease, notice

    def next(self, filters, exclude=''):
        with self.transaction():
            clauses, args = self.selection(filters)
            clauses += ['s.batch IS NULL', '(l.sample_id IS NULL OR l.expires<=?)', 's.id<>?']
            args += [time.time(), exclude]
            if self.user['role'] != 'admin':
                clauses.append('(a.reviewer_id IS NULL OR a.reviewer_id=?)'); args.append(self.user['id'])
            row = self.db.execute('SELECT s.id ' + JOIN + ' WHERE ' + ' AND '.join(clauses) +
                                   ' ORDER BY s.created_at DESC,s.id LIMIT 1', args).fetchone()
            if row:
                self._claim(row['id'])
                return row['id']
            return None

    def owned(self, sid, token):
        row = self.sample(sid)
        if row['batch']:
            raise Conflict('照片已冻结，不能修改')
        if not self.allowed(row):
            raise Forbidden('该品类已经分配给其他成员，请刷新查看分工')
        lease = self.db.execute('SELECT * FROM review_leases WHERE sample_id=?', (sid,)).fetchone()
        if not lease or lease['expires'] <= time.time() or lease['user_id'] != self.user['id'] or not secrets.compare_digest(lease['token'], token):
            raise Conflict('审核占用已失效或由其他成员持有，请刷新后重新领取；未保存的内容请先复制')
        return row

    def save(self, sid, token, revision, values, audit):
        with self.transaction():
            row = self.owned(sid, token)
            if str(row['revision']) != revision:
                raise Conflict('照片已更新，请刷新后再审核')
            self.db.execute('''UPDATE samples SET status=?,category=?,reason=?,object_id=?,session_id=?,group_id=?,crop=?,
                revision=revision+1 WHERE id=?''', (*values, sid))
            audit()
            self.db.execute('DELETE FROM review_leases WHERE sample_id=?', (sid,))

    def renew(self, sid, token):
        with self.transaction():
            self.owned(sid, token)
            expires = time.time() + self.ttl
            self.db.execute('UPDATE review_leases SET expires=? WHERE sample_id=?', (expires, sid))
            return expires

    def release(self, sid, token):
        self.db.execute('DELETE FROM review_leases WHERE sample_id=? AND user_id=? AND token=?',
                        (sid, self.user['id'], token))

    def assign(self, category, reviewer_id, revision, audit):
        if self.user['role'] != 'admin':
            raise Forbidden('只有管理员可以调整分工')
        with self.transaction():
            old = self.db.execute('SELECT * FROM category_assignments WHERE category=?', (category,)).fetchone()
            if not old:
                raise NotFound('未知类别')
            if str(old['revision']) != revision:
                raise Conflict('品类分工已被更新，请刷新后重试')
            if reviewer_id is not None and not self.db.execute('SELECT 1 FROM users WHERE id=? AND active=1', (reviewer_id,)).fetchone():
                raise BadRequest('请选择有效的组员账号')
            if reviewer_id != old['reviewer_id']:
                self.db.execute('UPDATE category_assignments SET reviewer_id=?,revision=revision+1 WHERE category=?',
                                (reviewer_id, category))
                self.db.execute('DELETE FROM review_leases WHERE sample_id IN (SELECT id FROM samples WHERE category=?)', (category,))
                audit(old['reviewer_id'])
