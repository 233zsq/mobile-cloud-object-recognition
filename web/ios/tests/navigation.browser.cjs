const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { startBrowserFixture } = require('../../tests/browser_support.cjs');
const contract = JSON.parse(fs.readFileSync(path.join(__dirname, '../model-contract.json')));
const clientId = '22222222-2222-4222-8222-222222222222';
const original = { record_id: '11111111-1111-4111-8111-111111111111', model_version: contract.model_version,
  predicted_id: 0, label_key: 'cup', confidence: .95, inference_source: 'cloud', latency_ms: 30, total_ms: 40,
  captured_at: '2026-10-13T12:00:00Z', corrected_id: null, corrected_at: null, revision: 0,
  synced: true, correction_synced: true, correction_conflict: false };
let fixture;
before(async () => { fixture = await startBrowserFixture(); });
after(async () => { if (fixture) await fixture.close(); });

async function openPage(t, record = original) {
  const context = await fixture.browser.newContext({ viewport: { width: 390, height: 844 }, acceptDownloads: true });
  t.after(() => context.close());
  const page = await context.newPage(); const errors = []; const posts = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(({ record, clientId }) => localStorage.setItem('campus-ios-v1', JSON.stringify({
    version: 1, token: 'local-private-test', clientId, records: [record],
  })), { record, clientId });
  await page.route('**/api/**', async route => {
    const request = route.request(); const pathname = new URL(request.url()).pathname;
    if (pathname === '/api/models') await route.fulfill({ json: { default_model_version: contract.model_version,
      models: [{ ...contract, display_name: '本地模拟模型', description: '仅用于回归', status: 'frozen', available: true,
        scope_policy: { ...contract.scope_policy, policy_sha256: contract.scope_policy_sha256 } }] } });
    else if (pathname === '/api/health') await route.fulfill({ json: { model_loaded: true, model_version: contract.model_version } });
    else if (request.method() === 'POST' && pathname === '/api/records') {
      posts.push(request.postDataJSON());
      await route.fulfill({ json: { record: { ...record, corrected_id: 3, corrected_at: '2026-10-13T12:03:00Z', revision: 4 } } });
    } else await route.fulfill({ status: 404, json: {} });
  });
  await page.goto(fixture.origin + '/ios/');
  await page.waitForFunction(() => !document.getElementById('cloud-model').disabled);
  return { page, errors, posts };
}

test('navigation preserves unsaved settings and historical records across view changes', async t => {
  const { page, errors } = await openPage(t);
  await page.locator('.tabbar button[data-view="records"]:visible').click();
  assert.match(await page.locator('#record-list').textContent(), /水杯/);
  await page.locator('.tabbar button[data-view="settings"]:visible').click();
  await page.locator('[data-settings="cloud"]:visible').click(); await page.locator('#token').fill('unsaved-input');
  await page.locator('#settings-back').click(); await page.locator('[data-settings="model"]:visible').click();
  await page.locator('#settings-back').click(); await page.locator('[data-settings="cloud"]:visible').click();
  assert.equal(await page.locator('#token').inputValue(), 'unsaved-input');
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('campus-ios-v1')));
  assert.equal(saved.token, 'local-private-test'); assert.equal(saved.clientId, clientId); assert.equal(saved.records.length, 1);
  assert.deepEqual(errors, []);
});

test('record backup excludes credentials and clearing local data preserves the client identity', async t => {
  const { page, errors, posts } = await openPage(t);
  await page.locator('.tabbar button[data-view="records"]:visible').click();
  const downloadTask = page.waitForEvent('download'); await page.locator('[data-export-records]:visible').first().click();
  const download = await downloadTask; const backup = JSON.parse(fs.readFileSync(await download.path(), 'utf8'));
  assert.equal(backup.schema_version, 1); assert.equal(backup.records.length, 1);
  assert.equal(backup.token, undefined); assert.equal(backup.clientId, undefined);
  await page.locator('.tabbar button[data-view="settings"]:visible').click(); await page.locator('[data-settings="data"]:visible').click();
  page.once('dialog', dialog => dialog.accept()); await page.locator('#clear-storage').click();
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('campus-ios-v1')));
  assert.equal(saved.clientId, clientId); assert.equal(saved.token, ''); assert.deepEqual(saved.records, []);
  assert.equal(posts.length, 0); assert.deepEqual(errors, []);
});

test('a restored conflict can adopt the cloud correction without creating another local record', async t => {
  const { page, errors, posts } = await openPage(t, { ...original, corrected_id: 2, corrected_at: '2026-10-13T12:01:00Z', revision: 3,
    correction_conflict: true, correction_synced: true });
  await page.locator('.tabbar button[data-view="records"]:visible').click();
  await page.locator('#filter-status').selectOption('conflict'); await page.getByRole('button', { name: '处理冲突', exact: true }).click();
  await page.locator('#conflict-cloud').click();
  await page.waitForFunction(() => !JSON.parse(localStorage.getItem('campus-ios-v1')).records[0].correction_conflict);
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('campus-ios-v1')));
  assert.equal(saved.records.length, 1); assert.equal(saved.records[0].record_id, original.record_id);
  assert.equal(saved.records[0].revision, 4); assert.equal(saved.records[0].corrected_id, 3); assert.equal(saved.records[0].correction_synced, true);
  assert.equal(posts.length, 1); assert.equal(posts[0].record_id, original.record_id); assert.deepEqual(errors, []);
});
