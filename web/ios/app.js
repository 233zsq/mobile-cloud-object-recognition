// App composition and startup; business workflows and DOM views live in modules/.
import * as Core from './core.js';
import { createState } from './modules/state.js';
import { createPersistence } from './modules/storage.js';
import { createApiClient } from './modules/api.js';
import * as images from './modules/images.js';
import { createModels } from './modules/models.js';
import { createRecords } from './modules/records.js';
import { createCapture } from './modules/capture.js';
import { createEvents } from './modules/events.js';
import { createPageView } from './modules/views/page.js';
import { createCaptureView } from './modules/views/capture.js';
import { createRecordsView } from './modules/views/records.js';
import { createSettingsView } from './modules/views/settings.js';

const state = createState();
const dom = {};
const ui = {};
const handlers = {};
const api = createApiClient({getToken: () => state.token});
const persistence = createPersistence(state, {getStorage: () => localStorage, onChange: () => ui.renderStorageWarning()});
const context = {state, dom, ui, handlers, api, persistence, images};
Object.assign(ui, createPageView(context), createCaptureView(context), createRecordsView(context), createSettingsView(context));
const models = createModels(context);
const records = createRecords(context);
Object.assign(context, {models, records});
const capture = createCapture(context);
context.capture = capture;
const events = createEvents(context);
Object.assign(handlers, capture, records, models, events);

async function init() {
  ui.cacheDom();
  persistence.loadState();
  state.view = ui.viewFromHash();
  state.settingsPage = ui.settingsPageFromHash();
  events.bindEvents();
  dom.tokenInput.value = state.token;
  ui.showView(state.view, state.settingsPage, true);
  ui.renderStorageWarning();
  ui.renderModelInfo();
  ui.renderRecords();
  ui.renderTicket();
  try {
    await models.loadCategories();
    if (state.token) await models.refreshModels();
    else state.contract = null;
    ui.renderModelInfo();
  } catch (error) {
    ui.setStatus(dom.captureStatus, '模型或类别规格加载失败，请刷新页面重试。', true);
  }
  ui.renderTicket();
  models.refreshHealth().catch(() => {});
  if (navigator.onLine && state.records.some(Core.isPending)) records.syncAll({ silent: true });
}

// Native modules defer startup until the document has been parsed.
init();
