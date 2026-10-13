/* Local browser regression: mocked API only; never writes to the group server. */
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const runtimeFiles = new Set(JSON.parse(fs.readFileSync(path.join(root, 'runtime-files.json'))));
const contract = JSON.parse(fs.readFileSync(path.join(root, 'model-contract.json')));
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jV3sAAAAASUVORK5CYII=', 'base64');
const models = [
  { ...contract, scope_policy: { ...contract.scope_policy, policy_sha256: contract.scope_policy_sha256 }, display_name: '进阶版', description: '当前冻结模型', status: 'frozen', available: true },
  { ...contract, scope_policy: null, model_version: 'campus-gpu-v1', model_sha256: 'b'.repeat(64), display_name: '基准版', description: '旧版模型', status: 'frozen', available: true },
];
let server;
let browser;
let origin;

before(async () => {
  server = http.createServer((request, response) => {
    const file = decodeURIComponent(new URL(request.url, 'http://localhost').pathname).replace(/^\/ios\//, '');
    if (!runtimeFiles.has(file)) {
      response.writeHead(404).end(); return;
    }
    const types = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.json': 'application/json' };
    response.setHeader('Content-Type', types[path.extname(file)] || 'application/json');
    response.end(fs.readFileSync(path.join(root, file)));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
});

after(async () => {
  if (browser) await browser.close();
  if (server) await new Promise((resolve) => server.close(resolve));
});

async function fixture(t, { scores = [.56, .44, ...Array(8).fill(0)], corruptPolicy = false, learned = false, width = 390 } = {}) {
  const context = await browser.newContext({ viewport: { width, height: 844 } });
  t.after(() => context.close());
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const posts = [];
  const patches = [];
  const rows = new Map();
  let catalog = corruptPolicy ? models.map(({ scope_policy, ...legacy }) => legacy) : models;
  if (learned) catalog = catalog.map((model, i) => i ? model : { ...model, scope_policy: {
    ...model.scope_policy, policy_version: 'scope-knownness-v1', rule: 'learned_knownness_v1', knownness_threshold: .85,
    policy_sha256: 'c'.repeat(64),
  } });
  await page.addInitScript(() => localStorage.setItem('campus-ios-v1', JSON.stringify({
    version: 1, token: 'local-test-only', clientId: 'browser-test', records: [],
  })));
  if (corruptPolicy) {
    await page.route('**/ios/model-contract.json', (route) => route.fulfill({ json: { ...contract, scope_policy_sha256: '0'.repeat(64) } }));
  }
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === '/api/health') {
      await route.fulfill({ json: { model_loaded: true, model_version: contract.model_version, model_status: 'ready', version: 'local-test' } });
    } else if (url.pathname === '/api/models') {
      await route.fulfill({ json: { default_model_version: contract.model_version, models: catalog } });
    } else if (url.pathname === '/api/infer') {
      const multipart = request.postDataBuffer().toString('utf8');
      const field = (name) => new RegExp(`name="${name}"\\r\\n\\r\\n([^\\r]+)`).exec(multipart)[1];
      const model = catalog.find((item) => item.model_version === field('model_version'));
      const top = scores.indexOf(Math.max(...scores));
      await route.fulfill({ json: { request_id: field('request_id'), model_version: model.model_version,
        model_sha256: model.model_sha256, scores, predicted_id: top, label_key: model.labels[top],
        confidence: scores[top], low_confidence: scores[top] < model.low_confidence_threshold,
        preprocess_ms: 10, inference_ms: 20, ...(learned ? {
          recognition_status: 'uncertain', scope_decision: { status: 'uncertain', needs_confirmation: true,
            policy_version: model.scope_policy.policy_version, policy_sha256: model.scope_policy.policy_sha256, knownness: .429 },
        } : {}) } });
    } else if (url.pathname === '/api/records' && request.method() === 'POST') {
      const sent = request.postDataJSON();
      posts.push(sent);
      const record = { ...sent, category_version: contract.category_version, corrected_id: null, corrected_at: null, revision: 0 };
      rows.set(record.record_id, record);
      await route.fulfill({ json: { record } });
    } else if (request.method() === 'PATCH') {
      const id = url.pathname.split('/')[3];
      const sent = request.postDataJSON();
      patches.push(sent);
      const record = { ...rows.get(id), ...sent };
      rows.set(id, record);
      await route.fulfill({ json: { record } });
    } else {
      await route.fulfill({ status: 404, json: { message: 'Unexpected local test request' } });
    }
  });
  await page.goto(`${origin}/ios/index.html`);
  await page.waitForFunction(() => !document.getElementById('cloud-model').disabled);
  const choose = async () => {
    await page.locator('#input-library').setInputFiles({ name: 'sample.png', mimeType: 'image/png', buffer: png });
    await page.locator('#ticket').waitFor({ state: 'visible' });
    await page.waitForFunction(() => document.getElementById('cancel-infer').hidden);
  };
  const saved = () => page.evaluate(() => JSON.parse(localStorage.getItem('campus-ios-v1')).records);
  t.after(() => assert.deepEqual(errors, []));
  return { page, choose, saved, posts, patches };
}

test('uncertain result stays out of storage and upload until the candidate is confirmed', async (t) => {
  const f = await fixture(t);
  await f.choose();
  assert.equal(await f.page.locator('#ticket-name').textContent(), '暂不确定');
  assert.equal(await f.page.locator('#scope-actions').isVisible(), true);
  assert.equal(await f.page.locator('#cloud-model').isDisabled(), true);
  assert.equal((await f.saved()).length, 0);
  assert.equal(f.posts.length, 0);
  if (process.env.SCOPE_SCREENSHOT_DIR) {
    fs.mkdirSync(process.env.SCOPE_SCREENSHOT_DIR, { recursive: true });
    await f.page.screenshot({ path: path.join(process.env.SCOPE_SCREENSHOT_DIR, 'web-scope-confirmation.png'), fullPage: true });
  }
  await f.page.locator('#scope-confirm').click();
  await f.page.waitForFunction(() => document.getElementById('ticket-sync').textContent.includes('已上报'));
  const [record] = await f.saved();
  assert.equal(record.predicted_id, 0);
  assert.equal(record.corrected_id, null);
  assert.equal(record.scope_manually_confirmed, true);
  assert.equal(f.posts.length, 1);
  assert.equal(f.patches.length, 0);
});

test('learned cloud rule rejects a 100 percent class guess and uploads only after manual confirmation', async (t) => {
  const f = await fixture(t, { learned: true, scores: [...Array(8).fill(0), 1, 0] });
  await f.choose();
  assert.equal(await f.page.locator('#ticket-name').textContent(), '暂不确定');
  assert.equal((await f.saved()).length, 0);
  assert.equal(f.posts.length, 0);
  await f.page.locator('#scope-confirm').click();
  await f.page.waitForFunction(() => document.getElementById('ticket-sync').textContent.includes('已上报'));
  assert.equal(f.posts[0].predicted_id, 8);
  assert.equal(f.posts[0].confidence, 1);
  assert.deepEqual(f.posts[0].scope_decision, { status: 'uncertain', policy_version: 'scope-knownness-v1',
    policy_sha256: 'c'.repeat(64), knownness: .429, manual_confirmed: true });
});

test('choosing another category uploads the original prediction and then its correction', async (t) => {
  const f = await fixture(t);
  await f.choose();
  await f.page.locator('#scope-choose').click();
  await f.page.locator('#category-grid button').nth(4).click();
  await f.page.waitForFunction(() => document.getElementById('ticket-sync').textContent.includes('已上报'));
  const [record] = await f.saved();
  assert.equal(record.predicted_id, 0);
  assert.equal(record.corrected_id, 4);
  assert.equal(record.confidence, .56);
  assert.equal(record.scores.length, 10);
  assert.equal(f.posts[0].predicted_id, 0);
  assert.equal(f.patches[0].corrected_id, 4);
});

test('discard releases the photo and makes no record or upload', async (t) => {
  const f = await fixture(t);
  await f.choose();
  await f.page.locator('#scope-discard').click();
  assert.equal(await f.page.locator('#ticket').isVisible(), false);
  assert.equal(await f.page.locator('#photo-preview').getAttribute('src'), null);
  assert.equal(await f.page.locator('#input-library').isEnabled(), true);
  assert.equal((await f.saved()).length, 0);
  assert.equal(f.posts.length, 0);
});

test('accepted results retain the existing automatic save flow on a desktop viewport', async (t) => {
  const f = await fixture(t, { scores: [.91, ...Array(9).fill(.01)], width: 1440 });
  await f.choose();
  await f.page.waitForFunction(() => document.getElementById('ticket-sync').textContent.includes('已上报'));
  assert.equal(await f.page.locator('#scope-actions').isVisible(), false);
  assert.equal((await f.saved()).length, 1);
  assert.equal(f.posts.length, 1);
  assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
});

test('an alternate model requires confirmation instead of borrowing the v2 rule', async (t) => {
  const f = await fixture(t, { scores: [.91, ...Array(9).fill(.01)] });
  await f.page.locator('#cloud-model').selectOption('campus-gpu-v1');
  await f.choose();
  assert.match(await f.page.locator('#ticket-flag').textContent(), /没有匹配/);
  assert.equal(f.posts.length, 0);
  assert.equal((await f.saved()).length, 0);
});

test('a corrupted policy hash falls back to manual confirmation', async (t) => {
  const f = await fixture(t, { scores: [.91, ...Array(9).fill(.01)], corruptPolicy: true });
  await f.choose();
  assert.match(await f.page.locator('#ticket-flag').textContent(), /没有匹配/);
  assert.equal(f.posts.length, 0);
  await f.page.locator('#scope-discard').click();
  assert.equal((await f.saved()).length, 0);
});

test('confirmation controls fit narrow phones and tablets', async (t) => {
  for (const width of [320, 820]) {
    const f = await fixture(t, { width });
    await f.choose();
    assert.equal(await f.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.equal(await f.page.locator('#scope-discard').isVisible(), true);
  }
});
