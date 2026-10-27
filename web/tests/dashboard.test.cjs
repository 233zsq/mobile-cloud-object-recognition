const { test, before } = require('node:test');
const assert = require('node:assert/strict');
let buildFilters, createDashboardApi, createDashboardState;
before(async () => {
  ({ buildFilters } = await import('../assets/js/dashboard/filters.js'));
  ({ createDashboardApi } = await import('../assets/js/dashboard/api.js'));
  ({ createDashboardState } = await import('../assets/js/dashboard/state.js'));
});

test('dashboard filters preserve versioned categories, source, status and effective label basis', () => {
  const result = buildFilters({ start: '2026-10-12T00:00:00+08:00', end: '2026-10-13T00:00:00+08:00',
    model: 'campus-evolve-v3', source: 'cloud', 'recognition-status': 'uncertain', category: 'campus-10-v4:5', basis: 'effective' });
  assert.equal(result.get('start'), '2026-10-11T16:00:00.000Z');
  assert.equal(result.get('end'), '2026-10-12T16:00:00.000Z');
  assert.equal(result.get('category_version'), 'campus-10-v4'); assert.equal(result.get('category_id'), '5');
  assert.equal(result.get('recognition_status'), 'uncertain'); assert.equal(result.get('category_basis'), 'effective');
});

test('other always uses effective-label filtering without inventing a category version', () => {
  const result = buildFilters({ category: 'other', basis: 'predicted' });
  assert.equal(result.get('category_id'), 'other');
  assert.equal(result.get('category_basis'), 'effective');
  assert.equal(result.has('category_version'), false);
});

test('invalid and empty time ranges do not become server queries', () => {
  for (const start of ['2026-10-13T12:00:00Z', '2026-10-14T00:00:00Z']) {
    assert.throws(() => buildFilters({ start, end: '2026-10-13T12:00:00Z' }), /开始时间/);
  }
  assert.throws(() => buildFilters({ start: 'invalid date' }), RangeError);
});

test('dashboard API keeps credentials in memory and omits browser credentials', async () => {
  const state = createDashboardState(); state.token = 'local-test'; const calls = [];
  const api = createDashboardApi(() => state.token, async (url, options) => {
    calls.push({ url, options }); return { ok: true, json: async () => ({ records: [] }) };
  });
  await api('records', new URLSearchParams({ page: '1' })); state.token = ''; await api('health');
  assert.equal(calls[0].url, '/api/records?page=1');
  assert.equal(calls[0].options.headers.Authorization, 'Bearer local-test');
  assert.equal(calls[0].options.credentials, 'omit'); assert.equal(calls[0].options.cache, 'no-store');
  assert.deepEqual(calls[1].options.headers, {});
});

test('dashboard authorization failures keep their actionable message', async () => {
  const api = createDashboardApi(() => 'test', async () => ({ ok: false, status: 401 }));
  await assert.rejects(api('stats'), /访问口令无效或已过期/);
});
