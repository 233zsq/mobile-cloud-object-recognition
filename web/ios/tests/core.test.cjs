const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const core = require('../core.js');

const record = (extra = {}) => ({ record_id: 'record-1', predicted_id: 0, corrected_id: null,
  corrected_at: null, revision: 0, synced: true, correction_synced: true, ...extra });
const edit = (id, revision) => ({ corrected_id: id, revision, corrected_at: `2026-10-12T10:00:0${revision}.000Z` });
const response = (item, correction = {}) => ({ record: { ...item, ...correction, category_version: 'campus-10-v4' } });
const deferred = () => { let resolve; let reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };

test('retention removes the oldest synced records and preserves order', () => {
  const records = Array.from({ length: 301 }, (_, index) => record({ record_id: String(300 - index) }));
  const kept = core.trimRecords(records, 300);
  assert.equal(kept[0].record_id, '300');
  assert.equal(kept.at(-1).record_id, '1');
  assert.equal(records.length, 301);
});

test('pending records, unsent corrections and conflicts survive retention', () => {
  const records = [record({ synced: false }), record({ ...edit(2, 1), correction_synced: false }),
    record({ correction_conflict: true }), record({ record_id: 'old-synced' })];
  assert.deepEqual(core.trimRecords(records, 1), records.slice(0, 3));
});

test('storage failure is reported without mutating the in-memory record', () => {
  const value = { records: [record()] };
  const result = core.writeState({ setItem() { throw new Error('quota exceeded'); } }, 'key', value);
  assert.equal(result.ok, false);
  assert.match(result.message, /导出/);
  assert.equal(value.records.length, 1);
});

test('a correction made while POST is uploading survives the original acknowledgement', async () => {
  const original = record({ synced: false });
  const gate = deferred();
  const requests = [];
  const sync = core.syncRecord(original, { uploadPayload: () => ({}), request: async (_, options) => {
    requests.push(options);
    if (options.method === 'POST') return gate.promise;
    return response(original, options.body);
  } });
  Object.assign(original, edit(3, 1), { correction_synced: false });
  gate.resolve(response(record()));
  await sync;
  assert.equal(requests[1].body.corrected_id, 3);
  assert.equal(requests[1].body.revision, 1);
  assert.equal(original.correction_synced, true);
});

test('an older PATCH acknowledgement cannot acknowledge or roll back a newer correction', async () => {
  const original = record({ ...edit(1, 1), correction_synced: false });
  const gate = deferred();
  let sent;
  const sync = core.syncRecord(original, { request: async (_, options) => { sent = options.body; return gate.promise; } });
  Object.assign(original, edit(2, 2));
  gate.resolve(response(original, sent));
  await sync;
  assert.equal(original.corrected_id, 2);
  assert.equal(original.revision, 2);
  assert.equal(original.correction_synced, false);
  assert.equal(original.server_revision, 1);
});

test('manual and automatic triggers share one queue; a new edit is drained after the current upload', async () => {
  const original = record({ ...edit(1, 1), correction_synced: false });
  const gate = deferred();
  const sent = [];
  let active = 0;
  let maximum = 0;
  const queue = core.createSyncQueue({ getRecords: () => [original], sync: (item) => core.syncRecord(item, {
    request: async (_, options) => {
      active += 1; maximum = Math.max(maximum, active);
      const payload = { ...options.body }; sent.push(payload);
      if (sent.length === 1) await gate.promise;
      active -= 1;
      return response(original, payload);
    },
  }) });
  // getRecords must return the same record identities, as the real state does.
  const first = queue.run();
  Object.assign(original, edit(2, 2));
  const second = queue.run();
  assert.equal(first, second);
  gate.resolve();
  await second;
  assert.equal(maximum, 1);
  assert.deepEqual(sent.map((item) => item.corrected_id), [1, 2]);
  assert.equal(original.correction_synced, true);
});

test('an existing server correction cannot overwrite an unsent local correction on POST retry', async () => {
  const original = record({ synced: false, ...edit(1, 1), correction_synced: false });
  let count = 0;
  await core.syncRecord(original, { uploadPayload: () => ({}), request: async () => {
    count += 1;
    return response(original, edit(3, 2));
  } });
  assert.equal(count, 1);
  assert.equal(original.corrected_id, 1);
  assert.equal(original.correction_synced, false);
  assert.equal(original.correction_conflict, true);
});

test('409 leaves a visible pending conflict; 404 schedules re-upload rather than false success', async () => {
  for (const status of [409, 404]) {
    const original = record({ ...edit(1, 1), correction_synced: false });
    const attempt = core.syncRecord(original, { request: async () => { throw Object.assign(new Error('failed'), { status }); } });
    if (status === 404) await assert.rejects(attempt);
    else await attempt;
    assert.equal(original.correction_synced, false);
    assert.equal(core.isPending(original), true);
    assert.equal(Boolean(original.correction_conflict), status === 409);
    assert.equal(original.synced, status !== 404);
  }
});

test('a failed queue can be retried and does not acknowledge the failed upload', async () => {
  const original = record({ synced: false });
  let fail = true;
  const queue = core.createSyncQueue({ getRecords: () => [original], sync: (item) => core.syncRecord(item, {
    uploadPayload: () => ({}), request: async () => { if (fail) throw new Error('offline'); return response(item); },
  }) });
  await assert.rejects(queue.run(), /offline/);
  assert.equal(original.synced, false);
  fail = false;
  await queue.run();
  assert.equal(original.synced, true);
});

test('conflicted records are not repeatedly uploaded by automatic retries', async () => {
  const original = record({ ...edit(1, 1), correction_synced: false, correction_conflict: true });
  const queue = core.createSyncQueue({ getRecords: () => [original], sync: () => assert.fail('conflict must wait for user') });
  await queue.run();
  assert.equal(core.isPending(original), true);
});

const contract = JSON.parse(fs.readFileSync(path.join(__dirname, '../model-contract.json')));
const categories = JSON.parse(fs.readFileSync(path.join(__dirname, '../categories.json'))).categories;
const expected = { requestId: 'request-1', contract, categories };
const inference = () => ({ request_id: 'request-1', model_version: contract.model_version,
  model_sha256: contract.model_sha256, scores: [0.91, ...Array(9).fill(0.01)], predicted_id: 0,
  label_key: 'cup', confidence: 0.91, preprocess_ms: 10, inference_ms: 20, low_confidence: false });

test('the valid pinned cloud response is accepted', () => {
  assert.equal(core.validateInference(inference(), expected).predicted_id, 0);
});

test('wrong request, model, hash, labels, scores, threshold and timings are rejected', () => {
  const mutations = [
    { request_id: 'other' }, { model_version: 'other' }, { model_sha256: '0'.repeat(64) },
    { label_key: 'mouse' }, { predicted_id: 1 }, { confidence: 0.5 },
    { scores: [1] }, { scores: Array(10).fill(0.2) }, { scores: [NaN, ...Array(9).fill(0)] },
    { low_confidence: true }, { inference_ms: -1 }, { preprocess_ms: Infinity },
  ];
  for (const mutation of mutations) assert.throws(() => core.validateInference({ ...inference(), ...mutation }, expected));
});

test('filters use effective labels and inclusive local dates consistently', () => {
  const start = new Date(2026, 9, 12, 0, 0).toISOString();
  const end = new Date(2026, 9, 13, 0, 0).toISOString();
  const records = [record({ model_version: 'v2', captured_at: start, ...edit(4, 1), correction_synced: false }),
    record({ record_id: 'next-day', model_version: 'v2', captured_at: end, predicted_id: 4 }),
    record({ record_id: 'old-model', model_version: 'v1', captured_at: start, predicted_id: 4 })];
  const filtered = core.filterRecords(records, { model: 'v2', category: '4', status: 'pending', start: '2026-10-12', end: '2026-10-12' });
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].record_id, 'record-1');
});

test('web model contract matches the frozen release and Android label order', () => {
  const root = path.resolve(__dirname, '../../..');
  const metadata = JSON.parse(fs.readFileSync(path.join(root, 'models/releases/campus-evolve-v2/metadata.json')));
  const android = JSON.parse(fs.readFileSync(path.join(root, 'android/app/src/main/assets/categories.json')));
  assert.equal(contract.model_sha256, metadata.sha256);
  assert.equal(contract.model_version, metadata.model_version);
  assert.equal(contract.low_confidence_threshold, metadata.low_confidence_threshold);
  assert.equal(contract.category_version, android.category_version);
  assert.deepEqual(contract.labels, android.categories.map((item) => item.label_key));
});
