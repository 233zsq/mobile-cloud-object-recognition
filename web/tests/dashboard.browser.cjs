const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { startBrowserFixture } = require('./browser_support.cjs');
const categories = JSON.parse(fs.readFileSync(path.join(__dirname, '../ios/categories.json')));
let fixture;
before(async () => { fixture = await startBrowserFixture(); });
after(async () => { if (fixture) await fixture.close(); });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };

async function pageFixture(t) {
  const context = await fixture.browser.newContext({ viewport: { width: 390, height: 844 } });
  t.after(() => context.close());
  const page = await context.newPage(); const errors = []; page.on('pageerror', error => errors.push(error.message));
  const requests = []; let failure = false; let hold = null; let started = null;
  await page.route('**/api/**', async route => {
    const request = route.request(); const url = new URL(request.url()); requests.push({ url, auth: request.headers().authorization });
    if (url.pathname === '/api/categories') {
      await route.fulfill({ json: { catalogs: { [categories.category_version]: categories.categories },
        models: [{ model_version: 'campus-evolve-v3', category_version: categories.category_version }] } }); return;
    }
    if (hold) { if (started) started.resolve(); await hold.promise; }
    if (failure && url.pathname === '/api/stats') { await route.fulfill({ status: 500, json: { error: { message: '本地模拟故障' } } }); return; }
    if (url.pathname === '/api/stats') {
      await route.fulfill({ json: { generated_at: '2026-10-13T12:00:00Z', total_count: 40, corrected_count: 3, other_count: 2, low_confidence_count: 2,
        uncertain_count: 3, device_count: 10, cloud_count: 30, latency_ms: { average: 32, min: 10, max: 120 },
        categories: categories.categories.map(item => ({ ...item, category_version: categories.category_version, effective_count: 4, predicted_count: 4 })),
        daily_counts: [{ date: '2026-10-13', count: 40 }] } });
    } else if (url.pathname === '/api/records') {
      const current = Number(url.searchParams.get('page') || 0);
      await route.fulfill({ json: { page: current, pages: 2, total: 40, records: [{ record_id: 'local-page-' + current,
        category_version: categories.category_version, predicted_id: current, corrected_id: null, captured_at: '2026-10-13T12:00:00Z',
        confidence: .95, latency_ms: 32, inference_source: 'cloud', model_version: 'campus-evolve-v3', scope_decision: { status: 'accepted' } }] } });
    } else if (url.pathname === '/api/health') {
      await route.fulfill({ json: { model_loaded: true, model_version: 'campus-evolve-v3' } });
    } else await route.fulfill({ status: 404, json: {} });
  });
  await page.goto(fixture.origin + '/');
  await page.locator('#auto-refresh').uncheck();
  await page.locator('#token').fill('local-dashboard-test'); await page.locator('#connect-form button').click();
  await page.waitForFunction(() => document.querySelector('#record-rows').textContent.includes('local-page-0'));
  return { page, errors, requests, fail: value => { failure = value; },
    pause: () => { hold = deferred(); started = deferred(); return { started: started.promise, release: () => { hold.resolve(); hold = null; } }; } };
}

test('dashboard native modules connect, paginate and apply versioned filters', async t => {
  const { page, errors, requests } = await pageFixture(t);
  assert.equal(await page.locator('#total').textContent(), '40');
  await page.locator('#next').click();
  await page.waitForFunction(() => document.querySelector('#record-rows').textContent.includes('local-page-1'));
  await page.locator('details summary').click();
  await page.locator('#model').selectOption('campus-evolve-v3');
  await page.locator('#category').selectOption(categories.category_version + ':5');
  await page.locator('#basis').selectOption('effective');
  await page.locator('#recognition-status').selectOption('uncertain'); await page.locator('#apply').click();
  await page.waitForFunction(() => document.querySelector('#record-rows').textContent.includes('local-page-0'));
  const query = requests.filter(item => item.url.pathname === '/api/records').at(-1).url.searchParams;
  assert.equal(query.get('category_version'), categories.category_version); assert.equal(query.get('category_id'), '5');
  assert.equal(query.get('category_basis'), 'effective'); assert.equal(query.get('recognition_status'), 'uncertain');
  assert.equal(query.get('page'), '0'); assert.equal(query.get('page_size'), '20');
  await page.locator('#category').selectOption('other'); await page.locator('#basis').selectOption('predicted');
  await page.locator('#apply').click();
  await page.waitForFunction(() => document.querySelector('#record-rows').textContent.includes('local-page-0'));
  const otherQuery = requests.filter(item => item.url.pathname === '/api/records').at(-1).url.searchParams;
  assert.equal(otherQuery.get('category_id'), 'other'); assert.equal(otherQuery.get('category_version'), null);
  assert.equal(otherQuery.get('category_basis'), 'effective');
  assert.match(await page.locator('#category-chart').textContent(), /其他/);
  assert.ok(requests.every(item => item.auth === 'Bearer local-dashboard-test'));
  assert.equal(await page.evaluate(() => localStorage.length), 0);
  assert.deepEqual(errors, []);
});

test('dashboard request failures retain the last successful data and can be retried', async t => {
  const { page, errors, fail } = await pageFixture(t); fail(true);
  await page.locator('#refresh').click(); await page.waitForFunction(() => document.getElementById('status').textContent.includes('本地模拟故障'));
  assert.equal(await page.locator('#total').textContent(), '40');
  assert.match(await page.locator('#record-rows').textContent(), /local-page-0/);
  fail(false); await page.locator('#refresh').click();
  await page.waitForFunction(() => document.getElementById('status').textContent.startsWith('最近刷新'));
  assert.deepEqual(errors, []);
});

test('disconnect ignores in-flight responses and clears credentials and visible records', async t => {
  const { page, errors, pause } = await pageFixture(t); const blocked = pause();
  await page.locator('#refresh').click(); await blocked.started; await page.locator('#disconnect').click(); blocked.release();
  await page.waitForFunction(() => document.getElementById('refresh').disabled);
  assert.equal(await page.locator('#total').textContent(), '—');
  assert.equal(await page.locator('#record-rows').textContent(), '');
  assert.equal(await page.locator('#health').textContent(), '已断开');
  assert.deepEqual(errors, []);
});
