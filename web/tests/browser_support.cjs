/* Only repository runtime assets are served, on an ephemeral loopback port. */
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');

async function startBrowserFixture() {
  const assets = new Map([['/', 'index.html']]);
  const walk = directory => {
    for (const entry of fs.readdirSync(path.join(root, directory), { withFileTypes: true })) {
      const relative = `${directory}/${entry.name}`;
      if (entry.isDirectory()) walk(relative);
      else if (relative.endsWith('.js')) assets.set('/' + relative, relative);
    }
  };
  walk('assets/js');
  for (const file of ['assets/css/dashboard.css', 'assets/images/brand-mark.png', 'assets/images/favicon.png', 'assets/images/apple-touch-icon.png']) assets.set('/' + file, file);
  const ios = JSON.parse(fs.readFileSync(path.join(root, 'ios/runtime-files.json')));
  for (const file of ios) assets.set('/ios/' + file, 'ios/' + file);
  assets.set('/ios/', 'ios/index.html');
  const server = http.createServer((request, response) => {
    const file = assets.get(new URL(request.url, 'http://localhost').pathname);
    if (!file) { response.writeHead(404).end(); return; }
    const types = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png' };
    response.setHeader('Content-Type', types[path.extname(file)] || 'application/manifest+json');
    response.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; manifest-src 'self'; base-uri 'none'");
    response.end(fs.readFileSync(path.join(root, file)));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
  } catch (error) {
    await new Promise(resolve => server.close(resolve));
    throw error;
  }
  return { browser, origin: `http://127.0.0.1:${server.address().port}`,
    async close() { await browser.close(); await new Promise(resolve => server.close(resolve)); } };
}

module.exports = { startBrowserFixture };
