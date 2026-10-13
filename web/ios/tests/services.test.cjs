const { test, before } = require('node:test');
const assert = require('node:assert/strict');
let createState, createPersistence, createApiClient, createRecords, createCapture;
before(async () => {
  ({ createState } = await import('../modules/state.js'));
  ({ createPersistence } = await import('../modules/storage.js'));
  ({ createApiClient } = await import('../modules/api.js'));
  ({ createRecords } = await import('../modules/records.js'));
  ({ createCapture } = await import('../modules/capture.js'));
});
const reply = (status, body) => ({ ok: status < 400, status, text: async () => JSON.stringify(body) });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const row = extra => ({ record_id: 'record-1', predicted_id: 0, corrected_id: null, corrected_at: null,
  revision: 0, synced: false, correction_synced: true, correction_conflict: false, ...extra });

test('storage restores the existing key and repairs legacy correction conflicts', () => {
  const state = createState();
  const saved = { version: 1, token: 'local-test', clientId: 'existing-client', modelVersion: 'existing-model',
    records: [row({ correction_conflict: true, correction_synced: true })] };
  const store = createPersistence(state, { getStorage: () => ({ getItem: key => {
    assert.equal(key, 'campus-ios-v1'); return JSON.stringify(saved);
  } }) });
  store.loadState();
  assert.equal(state.clientId, saved.clientId);
  assert.equal(state.token, saved.token);
  assert.equal(state.modelVersion, saved.modelVersion);
  assert.equal(state.records[0].correction_synced, false);
  assert.equal(state.records[0].correction_conflict, true);
});

test('persisted state excludes transient photos, requests and unconfirmed predictions', () => {
  const state = createState(); let written;
  state.records = [row()]; state.token = 'local-test';
  state.previewUrl = 'blob:only-this-session'; state.pendingConfirmation = row({ record_id: 'unconfirmed' });
  state.inferController = new AbortController();
  const store = createPersistence(state, { getStorage: () => ({ setItem: (_, data) => { written = JSON.parse(data); } }) });
  assert.equal(store.saveState(), true);
  assert.deepEqual(Object.keys(written).sort(), ['clientId', 'modelVersion', 'records', 'token', 'version']);
  assert.equal(written.records.length, 1);
  assert.equal(written.records[0].record_id, 'record-1');
});

test('a blocked storage accessor preserves session records and emits the save warning', () => {
  const state = createState(); const record = row(); state.records = [record]; let changes = 0;
  const store = createPersistence(state, { getStorage: () => { throw new Error('browser policy'); }, onChange: () => { changes++; } });
  assert.equal(store.saveState(), false);
  assert.match(state.storageError, /本次会话/);
  assert.equal(state.records[0], record);
  assert.equal(changes, 1);
});

test('the request client reads the current token and distinguishes public health requests', async () => {
  let token = 'first'; const requests = [];
  const request = createApiClient({ getToken: () => token, fetchImpl: async (path, options) => {
    requests.push({ path, options }); return reply(200, { ok: true });
  } });
  await request('/api/records', { method: 'POST', body: { record_id: 'local-test' } });
  token = 'second'; await request('/api/models'); await request('/api/health', { auth: false });
  assert.equal(requests[0].options.headers.Authorization, 'Bearer first');
  assert.equal(requests[1].options.headers.Authorization, 'Bearer second');
  assert.equal(requests[2].options.headers.Authorization, undefined);
  assert.equal(requests[0].options.body, '{"record_id":"local-test"}');
  assert.equal(requests[0].options.cache, 'no-store');
});

test('the request client preserves structured server errors and rejects invalid success data', async () => {
  const unauthorized = createApiClient({ getToken: () => '', fetchImpl: async () => reply(401, { error: { code: 'AUTH', message: 'local auth failure' } }) });
  await assert.rejects(unauthorized('/api/models'), error => error.code === 'AUTH' && error.status === 401);
  const invalid = createApiClient({ getToken: () => '', fetchImpl: async () => ({ ok: true, status: 200, text: async () => '<html>' }) });
  await assert.rejects(invalid('/api/models'), error => error.code === 'INVALID_RESPONSE');
});

test('caller cancellation and request timeout remain separate failures', async () => {
  const request = createApiClient({ getToken: () => '', fetchImpl: (_, { signal }) => new Promise((resolve, reject) => {
    const abort = () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' }));
    if (signal.aborted) abort(); else signal.addEventListener('abort', abort, { once: true });
  }) });
  const controller = new AbortController(); controller.abort();
  await assert.rejects(request('/api/infer', { signal: controller.signal }), error => error.code === 'CANCELLED');
  await assert.rejects(request('/api/models', { timeout: 1 }), error => error.code === 'TIMEOUT');
});

test('the record service syncs through injected callbacks without browser globals', async () => {
  const state = createState(); state.clientId = 'existing-client'; state.records = [row()];
  let saved = 0; const requests = [];
  const records = createRecords({ state, ui: new Proxy({}, { get: () => () => {} }),
    persistence: { trimRecords() {}, saveState() { saved++; } }, api: async (path, options) => {
      requests.push({ path, options }); return { record: { ...options.body, revision: 0, corrected_id: null, category_version: 'campus-10-v4' } };
    } });
  await records.syncAll({ silent: true });
  assert.equal(requests.length, 1);
  assert.equal(requests[0].options.body.client_id, 'existing-client');
  assert.equal(state.records[0].synced, true);
  assert.equal(state.syncing, false);
  assert.ok(saved > 0);
});

test('keeping a local conflict creates a new revision while retaining original prediction and scope', async () => {
  const state = createState(); const record = row({ synced: true, corrected_id: 2, corrected_at: '2026-10-13T12:00:00Z', revision: 3,
    correction_synced: false, correction_conflict: true, scope_decision: { status: 'uncertain' }, scope_manually_confirmed: true });
  state.records = [record]; state.ticket = record; const requests = [];
  const records = createRecords({ state, ui: new Proxy({}, { get: () => () => {} }), persistence: { trimRecords() {}, saveState() {} },
    api: async (path, options) => {
      requests.push({ path, ...options });
      return { record: options.method === 'POST'
        ? { ...record, corrected_id: 1, revision: 5 }
        : { ...record, ...options.body } };
    } });
  await records.resolveConflict(true);
  assert.equal(record.corrected_id, 2); assert.equal(record.revision, 6);
  assert.equal(record.correction_conflict, false); assert.equal(record.correction_synced, true);
  assert.equal(requests[0].body.predicted_id, 0);
  assert.equal(requests[0].body.scope_decision.manual_confirmed, true);
  assert.equal(requests[1].method, 'PATCH'); assert.equal(requests[1].body.revision, 6);
});

test('cancelling image preparation never sends a request or creates a record', async () => {
  const state = createState(); state.token = 'local-test'; state.categories = Array(10).fill({}); state.contract = {};
  const pending = deferred(); const statuses = [];
  const ui = new Proxy({}, { get: (_, name) => name === 'setBusy' ? busy => { state.busy = busy; }
    : name === 'setCaptureStatus' ? message => statuses.push(message) : () => {} });
  const capture = createCapture({ state, ui, api: () => assert.fail('Cancelled capture sent an API request'),
    images: { makeTransferCopy: () => pending.promise }, records: {} });
  const file = { name: 'local.png' }; const task = capture.recognize(file);
  state.inferController.abort(); pending.resolve(new Blob(['local photo'])); await task;
  assert.equal(state.records.length, 0); assert.equal(state.pendingConfirmation, null);
  assert.equal(state.busy, false); assert.equal(state.inferController, null); assert.equal(state.lastFile, file);
  assert.match(statuses.at(-1), /已取消/);
});
