'use strict';

/*
 * iPhone 网页版：拍照/选图 → 云端 /api/infer → 本机记录 → /api/records 上报 → 纠错 /api/records/{id}/label
 * 与安卓端共用同一云端发布；网页端没有端侧推理，识别必须联网。
 */

/* ---------------- 常量（与 docs/ui-style.md 的云端副本规格一致） ---------------- */
const CATEGORY_FILE = 'categories.json';
const STORAGE_KEY = 'campus-ios-v1';
const MAX_RECORDS = 300;                        // 本机保留上限，超出时先清理已同步的最旧记录
const MAX_SOURCE_BYTES = 32 * 1024 * 1024;      // 导入原图上限
const TRANSFER_MAX_SIDE = 2048;                 // 传输副本最长边
const TRANSFER_QUALITY = 0.92;
const TRANSFER_MAX_BYTES = 8 * 1024 * 1024;     // 传输副本上限
const INFER_TIMEOUT_MS = 40000;
const REQUEST_TIMEOUT_MS = 15000;
const RETRY_INTERVAL_MS = 45000;                // 存在待传记录时的自动补传间隔
const Core = window.RecognitionCore;
const PAGE_SIZE = 24;

/* ---------------- 运行状态与持久化 ---------------- */
const state = {
  token: '',
  clientId: '',
  modelVersion: '',
  records: [],
  categories: [],
  view: 'capture',
  busy: false,
  ticket: null,
  lastFile: null,
  health: null,
  contract: null,
  storageError: '',
  syncing: false,
  settingsPage: '',
  visibleRecords: PAGE_SIZE,
  previewUrl: '',
  previewRecordId: '',
  inferController: null,
};

const dom = {};

function loadState() {
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
  } catch (error) {
    saved = null;
    state.storageError = '无法读取本机数据。请不要清除浏览器数据；如已有备份，请保留备份。';
  }
  if (saved && typeof saved === 'object') {
    state.token = typeof saved.token === 'string' ? saved.token : '';
    state.clientId = typeof saved.clientId === 'string' ? saved.clientId : '';
    state.modelVersion = typeof saved.modelVersion === 'string' ? saved.modelVersion : '';
    state.records = Array.isArray(saved.records) ? saved.records : [];
    // Old clients marked conflicts as synced. Keep these edits pending for explicit resolution.
    for (const record of state.records) {
      if (record.correction_conflict) record.correction_synced = false;
    }
  }
  if (!state.clientId) state.clientId = uuidv4();
  state.view = viewFromHash();
  state.settingsPage = settingsPageFromHash();
}

function saveState() {
  let result;
  try {
    result = Core.writeState(localStorage, STORAGE_KEY, {
      version: 1,
      token: state.token,
      clientId: state.clientId,
      modelVersion: state.modelVersion,
      records: state.records,
    });
  } catch (error) {
    result = { ok: false, message: '浏览器禁止本机存储，记录仅在本次会话保留。请立即同步或导出，暂时不要关闭页面。' };
  }
  state.storageError = result.ok ? '' : result.message;
  renderStorageWarning();
  return result.ok;
}

function trimRecords() {
  state.records = Core.trimRecords(state.records, MAX_RECORDS);
}

/* ---------------- 基础工具 ---------------- */
function uuidv4() {
  if (window.crypto && typeof window.crypto.randomUUID === 'function') {
    try {
      return window.crypto.randomUUID();
    } catch (error) {
      /* 继续走手写实现 */
    }
  }
  const bytes = new Uint8Array(16);
  if (window.crypto && window.crypto.getRandomValues) {
    window.crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [];
  for (let index = 0; index < bytes.length; index += 1) {
    hex.push(bytes[index].toString(16).padStart(2, '0'));
  }
  const text = hex.join('');
  return `${text.slice(0, 8)}-${text.slice(8, 12)}-${text.slice(12, 16)}-${text.slice(16, 20)}-${text.slice(20)}`;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function percent(value) {
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function durationText(milliseconds) {
  const value = Math.max(0, Number(milliseconds) || 0);
  return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(2)} s`;
}

function localTime(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso || '');
  const pad = (value) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} `
    + `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function categoryName(id, fallbackKey) {
  const found = state.categories.find((item) => item.id === id);
  if (found) return found.display_name;
  return fallbackKey || `类别 ${id}`;
}

function viewFromHash() {
  const name = (location.hash || '').replace('#', '').split('/')[0];
  return ['capture', 'records', 'settings'].includes(name) ? name : 'capture';
}

function settingsPageFromHash() {
  const page = (location.hash || '').split('/')[1];
  return ['cloud', 'model', 'data', 'help'].includes(page) ? page : '';
}

/* ---------------- 接口调用 ---------------- */
class ApiFailure extends Error {
  constructor(code, message, status) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

function httpMessage(status) {
  if (status === 401) return '口令无效或未设置，请在「我的 → 云端连接」填写访问口令。';
  if (status === 403) return '服务器拒绝了这个请求。';
  if (status === 404) return '接口不存在，请确认服务器版本。';
  if (status === 413) return '图片太大，服务器拒绝接收。';
  if (status === 429) return '请求过于频繁，请稍后再试。';
  if (status === 503) return '服务暂不可用，请稍后重试。';
  return `请求失败（HTTP ${status}）。`;
}

/** 同源接口：页面与 /api/ 在同一服务器，无需跨域配置。 */
async function api(path, options = {}) {
  const { method = 'GET', body, timeout = REQUEST_TIMEOUT_MS, auth = true, signal } = options;
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (signal) {
    signal.addEventListener('abort', cancel, { once: true });
    if (signal.aborted) controller.abort();
  }
  const timer = setTimeout(() => controller.abort(), timeout);
  const headers = {};
  if (auth && state.token) headers.Authorization = `Bearer ${state.token}`;
  const isForm = body instanceof FormData;
  if (body && !isForm) headers['Content-Type'] = 'application/json';
  try {
    const response = await fetch(path, {
      method,
      headers,
      body: isForm ? body : (body ? JSON.stringify(body) : undefined),
      signal: controller.signal,
      cache: 'no-store',
    });
    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (error) {
        data = null;
      }
    }
    if (!response.ok) {
      const detail = data && data.error;
      throw new ApiFailure(
        detail ? detail.code : `HTTP_${response.status}`,
        detail ? detail.message : httpMessage(response.status),
        response.status,
      );
    }
    if (!data || typeof data !== 'object') throw new ApiFailure('INVALID_RESPONSE', '服务器响应格式无效，请稍后重试。', response.status);
    return data;
  } catch (error) {
    if (error instanceof ApiFailure) throw error;
    if (error && error.name === 'AbortError') {
      if (signal && signal.aborted) throw new ApiFailure('CANCELLED', '本次识别已取消，未保存识别记录。', 0);
      throw new ApiFailure('TIMEOUT', '请求超时，请确认网络后重试。', 0);
    }
    throw new ApiFailure('NETWORK', '无法连接服务器，请确认网络与访问口令。', 0);
  } finally {
    clearTimeout(timer);
    if (signal) signal.removeEventListener('abort', cancel);
  }
}

/** /api/health 不需要口令，用于显示模型状态并取回当前模型版本。 */
async function refreshHealth() {
  try {
    const data = await api('/api/health', { auth: false, timeout: 8000 });
    state.health = data;
    renderHealthBadge();
    renderModelInfo();
    return data;
  } catch (error) {
    state.health = null;
    renderHealthBadge();
    renderModelInfo();
    throw error;
  }
}

/* ---------------- 图片：直立、缩放、去元数据（传输副本） ---------------- */
/** 返回可绘制的图片（EXIF 方向已按 image-orientation: from-image 应用）；对象 URL 由调用方绘制后释放。 */
function loadImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => resolve({ image, url });
    // 不使用 image.decode()：在部分浏览器/WebView 上该 Promise 不返回，会让识别流程整体卡住；
    // onload 已保证图片可绘制。
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new ApiFailure('IMAGE_DECODE', '无法读取这张图片，请重新拍照，或在相册中导出 JPEG / PNG 后重试。', 0));
    };
    image.src = url;
  });
}

function canvasToBlob(canvas, quality) {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new ApiFailure('IMAGE_DECODE', '图片处理失败，请重试。', 0));
    }, 'image/jpeg', quality);
  });
}

/** 与安卓端云端模式一致：最长边不超过 2048 的 JPEG，重编码同时丢弃 EXIF 与位置信息。 */
async function makeTransferCopy(file) {
  if (file.size > MAX_SOURCE_BYTES) {
    throw new ApiFailure('IMAGE_TOO_LARGE', '原图超过 32 MiB，请重新拍摄或选择更小的图片。', 0);
  }
  const { image, url } = await loadImage(file);
  let canvas;
  try {
    const width = image.naturalWidth || image.width;
    const height = image.naturalHeight || image.height;
    if (!width || !height) {
      throw new ApiFailure('IMAGE_DECODE', '无法读取这张图片，请重新拍照或换一张。', 0);
    }
    const scale = Math.min(1, TRANSFER_MAX_SIDE / Math.max(width, height));
    canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const context = canvas.getContext('2d');
    if (!context) throw new ApiFailure('IMAGE_DECODE', '这个浏览器无法处理图片，请换用系统浏览器打开。', 0);
    context.fillStyle = '#808080';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
  } finally {
    URL.revokeObjectURL(url);          // 绘制完成后即可释放，避免 Safari 重新取图失败
  }
  let quality = TRANSFER_QUALITY;
  let blob = await canvasToBlob(canvas, quality);
  while (blob.size > TRANSFER_MAX_BYTES && quality > 0.5) {
    quality = Math.round((quality - 0.1) * 100) / 100;
    blob = await canvasToBlob(canvas, quality);
  }
  if (blob.size > TRANSFER_MAX_BYTES) {
    throw new ApiFailure('IMAGE_TOO_LARGE', '图片压缩后仍然过大，请换一张更小的图片。', 0);
  }
  return blob;
}

/* ---------------- 识别 ---------------- */
async function inferOnce(blob, signal) {
  const requestId = uuidv4();
  const body = new FormData();
  body.append('request_id', requestId);
  body.append('model_version', state.contract.model_version);
  body.append('image', blob, 'photo.jpg');
  const result = await api('/api/infer', { method: 'POST', body, timeout: INFER_TIMEOUT_MS, signal });
  return Core.validateInference(result, { requestId, contract: state.contract, categories: state.categories });
}

async function recognize(file) {
  if (state.busy) return;
  state.lastFile = file;
  if (!state.contract || state.categories.length !== 10) {
    setStatus(dom.captureStatus, '模型规格尚未加载，请刷新页面重试。', true);
    return;
  }
  if (!state.token) {
    setStatus(dom.captureStatus, '请先在「我的 → 云端连接」保存组内访问口令。', true);
    renderRetryButton();
    showView('settings', 'cloud');
    return;
  }
  state.ticket = null;
  renderTicket();
  const controller = new AbortController();
  state.inferController = controller;
  setPreview(null);
  const capturedAt = new Date().toISOString();
  setBusy(true, '正在准备图片…');
  setPhase('prepare');
  const started = Date.now();
  try {
    const blob = await makeTransferCopy(file);
    if (controller.signal.aborted) throw new ApiFailure('CANCELLED', '本次识别已取消，未保存识别记录。', 0);
    setPreview(blob);
    setBusy(true, '正在上传并识别…');
    setPhase('infer');
    const health = await refreshHealth();
    if (controller.signal.aborted) throw new ApiFailure('CANCELLED', '本次识别已取消，未保存识别记录。', 0);
    if (!health.model_loaded) {
      throw new ApiFailure('MODEL_UNAVAILABLE', '云端模型未就绪，请联系维护人员。', 503);
    }
    if (health.model_version !== state.contract.model_version) {
      throw new ApiFailure('MODEL_VERSION_MISMATCH', '云端模型已变更，请更新网页后重试。本次未切换模型。', 409);
    }
    const result = await inferOnce(blob, controller.signal);
    if (controller.signal.aborted) throw new ApiFailure('CANCELLED', '本次识别已取消，未保存识别记录。', 0);
    setPhase('save');
    const totalMs = Date.now() - started;
    const record = recordFromResult(result, totalMs);
    record.captured_at = capturedAt;
    rememberRecord(record);
    state.ticket = record;
    state.previewRecordId = record.record_id;
    state.lastFile = null;
    renderTicket();
    setStatus(dom.captureStatus, `识别完成，用时 ${durationText(totalMs)}。${state.storageError ? '本机保存失败，请立即同步或导出。' : ''}`, Boolean(state.storageError));
    if (state.view === 'capture' && window.innerWidth < 700) {
      dom.ticket.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    }
    syncAll({ silent: true });
  } catch (error) {
    if (controller.signal.aborted) error = new ApiFailure('CANCELLED', '本次识别已取消，未保存识别记录。', 0);
    setStatus(dom.captureStatus, `${error.message} ${error.code === 'CANCELLED' ? '可重新选择图片或重试。' : '可以点「再试一次」重发这张图片。'}`, error.code !== 'CANCELLED');
    renderRetryButton();
  } finally {
    state.inferController = null;
    setBusy(false);
  }
}

function recordFromResult(result, totalMs) {
  return {
    // 上报字段（与 /api/records 的 8 个字段一致）
    record_id: result.request_id,
    inference_source: 'cloud',
    model_version: result.model_version,
    model_sha256: result.model_sha256,
    predicted_id: result.predicted_id,
    confidence: result.confidence,
    latency_ms: Math.round(result.preprocess_ms + result.inference_ms),
    captured_at: new Date().toISOString(),
    // 仅本机展示与同步状态
    label_key: result.label_key,
    low_confidence: result.low_confidence === true,
    preprocess_ms: result.preprocess_ms,
    inference_ms: result.inference_ms,
    total_ms: totalMs,
    corrected_id: null,
    corrected_at: null,
    revision: 0,
    correction_synced: true,
    correction_conflict: false,
    synced: false,
    created_at: new Date().toISOString(),
  };
}

function rememberRecord(record) {
  state.records.unshift(record);
  trimRecords();
  saveState();
  renderRecords();
}

function findRecord(recordId) {
  return state.records.find((record) => record.record_id === recordId) || null;
}

/* ---------------- 上报与纠错 ---------------- */
function uploadPayload(record) {
  return {
    record_id: record.record_id,
    client_id: state.clientId,
    inference_source: record.inference_source,
    model_version: record.model_version,
    predicted_id: record.predicted_id,
    confidence: record.confidence,
    latency_ms: record.latency_ms,
    captured_at: record.captured_at,
  };
}

function isPending(record) {
  return Core.isPending(record);
}

async function syncRecord(record) {
  return Core.syncRecord(record, { request: api, uploadPayload });
}

const syncQueue = Core.createSyncQueue({
  getRecords: () => state.records,
  sync: syncRecord,
  onChange: () => {
    trimRecords();
    saveState();
    renderRecords();
    if (state.ticket) updateTicketSync();
  },
});

async function syncAll(options = {}) {
  const pending = state.records.filter((record) => isPending(record) && !record.correction_conflict);
  if (!pending.length) {
    if (!options.silent) {
      const conflict = state.records.some((record) => record.correction_conflict);
      setStatus(dom.recordsStatus, conflict ? '有修订冲突，请点记录中的「处理冲突」。' : (state.records.length ? '全部记录都已上报。' : '还没有需要上报的记录。'), conflict);
    }
    return;
  }
  state.syncing = true;
  renderRecords();
  try {
    const done = await syncQueue.run();
    const conflicts = state.records.filter((record) => record.correction_conflict).length;
    if (!options.silent || conflicts) {
      setStatus(dom.recordsStatus, `本轮已处理 ${done} 次同步。${conflicts ? `另有 ${conflicts} 条修订冲突需要处理。` : ''}`, conflicts > 0);
    }
  } catch (error) {
    setStatus(dom.recordsStatus, `还有 ${state.records.filter(isPending).length} 条待同步：${error.message}`, true);
  } finally {
    state.syncing = false;
    saveState();
    renderRecords();
    if (state.ticket) updateTicketSync();
  }
}

function correctRecord(recordId, correctedId) {
  const record = findRecord(recordId);
  if (!record) return;
  record.corrected_id = correctedId;
  record.corrected_at = new Date().toISOString();
  record.revision = Math.max(Number(record.revision) || 0, Number(record.server_revision) || 0) + 1;
  record.correction_synced = false;
  record.correction_conflict = false;
  saveState();
  renderRecords();
  if (state.ticket && state.ticket.record_id === recordId) {
    state.ticket = record;
    renderTicket();
  }
  syncAll({ silent: true });
}

/* ---------------- 渲染 ---------------- */
function setStatus(node, message, isError) {
  if (!node) return;
  node.textContent = message || '';
  node.classList.toggle('error', Boolean(isError));
}

function setBusy(busy, message) {
  state.busy = busy;
  dom.inputCamera.disabled = busy;
  dom.inputLibrary.disabled = busy;
  dom.btnCamera.classList.toggle('busy', busy);
  dom.btnLibrary.classList.toggle('busy', busy);
  dom.cancelInfer.hidden = !busy;
  dom.processingSteps.hidden = !busy;
  dom.ticketAgain.disabled = busy;
  dom.clearStorage.disabled = busy || state.syncing;
  if (message) setStatus(dom.captureStatus, message, false);
}

function renderRetryButton() {
  if (!state.lastFile) return;
  const node = el('button', 'secondary', '再试一次');
  node.type = 'button';
  node.addEventListener('click', () => {
    const file = state.lastFile;
    if (file) recognize(file);
  });
  dom.captureStatus.appendChild(document.createTextNode(' '));
  dom.captureStatus.appendChild(node);
}

function renderHealthBadge() {
  const badge = dom.healthBadge;
  badge.classList.remove('ok', 'warn');
  if (!state.health) {
    badge.textContent = '无法连接';
    badge.classList.add('warn');
    badge.title = '无法读取 /api/health';
    return;
  }
  if (state.health.model_loaded && state.health.model_version) {
    if (state.contract && state.health.model_version !== state.contract.model_version) {
      badge.textContent = '模型需更新';
      badge.classList.add('warn');
      badge.title = `网页 ${state.contract.model_version}；云端 ${state.health.model_version}`;
      return;
    }
    // 手机顶栏空间有限：徽章只显示版本尾号（如 v2），完整版本放 tooltip 与票据里
    const tail = /(v\d+(?:\.\d+)*)$/.exec(state.health.model_version);
    badge.textContent = `云端 ${tail ? tail[1] : '就绪'}`;
    badge.classList.add('ok');
    badge.title = `模型 ${state.health.model_version}（${state.health.model_status}）；服务版本 ${state.health.version}`;
  } else {
    badge.textContent = '模型未就绪';
    badge.classList.add('warn');
    badge.title = `模型状态：${state.health.model_status}`;
  }
}

function renderTicket() {
  const ticket = state.ticket;
  dom.resultEmpty.hidden = Boolean(ticket);
  const showPhoto = Boolean(state.previewUrl && (!ticket || state.previewRecordId === ticket.record_id));
  dom.photoPreview.hidden = !showPhoto;
  dom.photoEmpty.hidden = showPhoto;
  if (!ticket) {
    dom.ticket.hidden = true;
    return;
  }
  dom.ticket.hidden = false;
  const shownId = ticket.corrected_id !== null && ticket.corrected_id !== undefined
    ? ticket.corrected_id
    : ticket.predicted_id;
  dom.ticketName.textContent = categoryName(shownId, ticket.label_key);
  dom.ticketConfidence.textContent = percent(ticket.confidence);
  dom.ticketFlag.hidden = !ticket.low_confidence;
  if (ticket.corrected_id !== null && ticket.corrected_id !== undefined) {
    dom.ticketOriginal.hidden = false;
    dom.ticketOriginal.textContent = `原预测：${categoryName(ticket.predicted_id, ticket.label_key)}（已保留）`;
  } else {
    dom.ticketOriginal.hidden = true;
  }
  dom.ticketMeta.textContent = '';
  const rows = [
    ['来源', '云端识别'],
    ['模型', ticket.model_version],
    ['模型耗时', `预处理 ${Math.round(ticket.preprocess_ms)} ms + 推理 ${Math.round(ticket.inference_ms)} ms`],
    ['本次总等待', durationText(ticket.total_ms)],
    ['编号', ticket.record_id],
  ];
  for (const [label, value] of rows) {
    const row = el('div');
    row.appendChild(el('dt', null, label));
    row.appendChild(el('dd', null, value));
    dom.ticketMeta.appendChild(row);
  }
  renderCorrectionGrid(ticket);
  updateTicketSync();
}

function updateTicketSync() {
  const ticket = state.ticket;
  if (!ticket) return;
  const record = findRecord(ticket.record_id) || ticket;
  dom.ticketConflictActions.hidden = !record.correction_conflict;
  if (record.correction_conflict) {
    setStatus(dom.ticketSync, '修订冲突：本机修正尚未上报，请选择如何处理。', true);
  } else if (state.storageError && isPending(record)) {
    setStatus(dom.ticketSync, '本机保存失败，请立即同步或导出；关闭页面可能丢失这条待同步记录。', true);
  } else if (record.synced && (record.corrected_id === null || record.corrected_id === undefined || record.correction_synced)) {
    setStatus(dom.ticketSync, '已上报到云端。', false);
  } else if (navigator.onLine) {
    setStatus(dom.ticketSync, '等待上报，会自动重试，也可以在「记录」里立即同步。', false);
  } else {
    setStatus(dom.ticketSync, '当前离线：记录已保存在本机，联网后自动补传。', false);
  }
}

function renderCorrectionGrid(ticket) {
  dom.categoryGrid.textContent = '';
  const current = ticket.corrected_id !== null && ticket.corrected_id !== undefined
    ? ticket.corrected_id
    : ticket.predicted_id;
  for (const category of state.categories) {
    const button = el('button', category.id === current ? 'current' : null, category.display_name);
    button.type = 'button';
    button.addEventListener('click', () => {
      if (category.id === current) return;
      correctRecord(ticket.record_id, category.id);
    });
    dom.categoryGrid.appendChild(button);
  }
}

function recordRow(record) {
  const item = el('li');
  const head = el('div', 'head');
  const name = record.corrected_id !== null && record.corrected_id !== undefined
    ? categoryName(record.corrected_id, record.label_key)
    : categoryName(record.predicted_id, record.label_key);
  const title = el('span', 'title', name);
  if (record.corrected_id !== null && record.corrected_id !== undefined) {
    title.appendChild(el('em', null, `原预测 ${categoryName(record.predicted_id, record.label_key)}`));
  }
  head.appendChild(title);
  head.appendChild(el('span', 'conf', percent(record.confidence)));
  item.appendChild(head);
  item.appendChild(el('div', 'sub', `${localTime(record.captured_at)} · 模型 ${record.model_version} · 云端识别 · 耗时 ${durationText(record.total_ms)}`));

  const badges = el('div', 'badges');
  badges.appendChild(el('span', 'tag', record.synced ? '已上报' : '待上报'));
  if (record.corrected_id !== null && record.corrected_id !== undefined) {
    badges.appendChild(el('span', 'tag fixed', record.correction_synced && !record.correction_conflict ? '修正已上报' : '修正待上报'));
  }
  if (record.correction_conflict) badges.appendChild(el('span', 'tag pending', '修订冲突'));
  if (record.low_confidence) badges.appendChild(el('span', 'tag pending', '需要确认'));
  item.appendChild(badges);

  const actions = el('div', 'row-actions');
  const correctButton = el('button', 'secondary', record.correction_conflict ? '处理冲突' : '纠正类别');
  correctButton.type = 'button';
  correctButton.addEventListener('click', () => {
    state.ticket = record;
    showView('capture');
    dom.correction.hidden = false;
    renderTicket();
  });
  const syncButton = el('button', 'secondary', '同步');
  syncButton.type = 'button';
  syncButton.disabled = !isPending(record) || record.correction_conflict || state.syncing;
  // Every trigger shares one queue, including row buttons, online events and retries.
  syncButton.title = '通过统一队列同步待传记录';
  syncButton.addEventListener('click', () => syncAll({ silent: false }));
  const deleteButton = el('button', 'secondary danger', '删除本机');
  deleteButton.type = 'button';
  deleteButton.disabled = state.syncing;
  deleteButton.addEventListener('click', () => {
    const confirmText = record.synced
      ? '这条记录已上报到云端，删除只影响本机显示，云端记录仍然保留。确定删除吗？'
      : '这条记录还没有上报，删除后就无法补传了。确定删除吗？';
    if (!window.confirm(confirmText)) return;
    state.records = state.records.filter((item2) => item2.record_id !== record.record_id);
    if (state.ticket && state.ticket.record_id === record.record_id) {
      state.ticket = null;
      setPreview(null);
    }
    saveState();
    renderRecords();
    renderTicket();
  });
  actions.appendChild(correctButton);
  actions.appendChild(syncButton);
  actions.appendChild(deleteButton);
  item.appendChild(actions);
  return item;
}

function renderRecords() {
  if (!dom.recordList) return;
  renderFilterOptions();
  const filters = currentFilters();
  const invalidRange = filters.start && filters.end && filters.start > filters.end;
  const records = invalidRange ? [] : Core.filterRecords(state.records, filters);
  const total = records.length;
  const pending = records.filter(isPending).length;
  const corrected = records.filter(Core.hasCorrection).length;
  dom.mTotal.textContent = String(total);
  dom.mPending.textContent = String(pending);
  dom.mCorrected.textContent = String(corrected);
  dom.recordList.textContent = '';
  for (const record of records.slice(0, state.visibleRecords)) {
    dom.recordList.appendChild(recordRow(record));
  }
  dom.recordsEmpty.hidden = total > 0;
  dom.recordsEmpty.textContent = invalidRange ? '开始日期不能晚于结束日期。' : (state.records.length ? '没有符合筛选条件的记录，试试重置筛选。' : '还没有记录，去识别一件物品吧。');
  dom.filterCount.textContent = `${total} / ${state.records.length} 条`;
  dom.loadMore.hidden = total <= state.visibleRecords;
  dom.loadMore.textContent = `加载更多（还剩 ${Math.max(0, total - state.visibleRecords)} 条）`;
  dom.syncNow.disabled = state.syncing || !state.records.some((record) => isPending(record) && !record.correction_conflict);
  dom.syncNow.textContent = state.syncing ? '正在同步…' : '同步全部';
  dom.clearAll.disabled = !state.records.length || state.syncing;
  dom.clearStorage.disabled = state.syncing || state.busy;
  renderStorageInfo();
}

function renderStorageInfo() {
  const pending = state.records.filter(isPending).length;
  dom.storageInfo.textContent = `${state.storageError ? '当前会话暂存' : '本机保存'} ${state.records.length} 条记录，其中 ${pending} 条待同步；`
    + `口令${state.token ? (state.storageError ? '仅本次会话可用' : '已保存') : '未设置'}。记录与口令不会自动同步到其他设备。`;
}

function showView(name, settingsPage = '', replace = false) {
  state.view = name;
  state.settingsPage = name === 'settings' ? settingsPage : '';
  const hash = `#${name}${state.settingsPage ? `/${state.settingsPage}` : ''}`;
  if (location.hash !== hash) {
    history[replace ? 'replaceState' : 'pushState'](null, '', hash);
  }
  for (const button of dom.tabButtons) {
    const active = button.dataset.view === name;
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  dom.viewCapture.hidden = name !== 'capture';
  dom.viewRecords.hidden = name !== 'records';
  dom.viewSettings.hidden = name !== 'settings';
  dom.settingsOverview.hidden = Boolean(state.settingsPage);
  dom.settingsDetail.hidden = !state.settingsPage;
  const titles = { cloud: '云端连接', model: '识别模型', data: '数据与隐私', help: '使用说明' };
  dom.settingsTitle.textContent = titles[state.settingsPage] || '我的手册';
  for (const panel of dom.settingsPages) panel.hidden = panel.dataset.settingsPage !== state.settingsPage;
  document.body.classList.toggle('detail-open', name === 'settings' && Boolean(state.settingsPage));
  if (name === 'records') renderRecords();
  if (name === 'settings') renderStorageInfo();
  window.scrollTo(0, 0);
}

function currentFilters() {
  return { model: dom.filterModel.value, category: dom.filterCategory.value, status: dom.filterStatus.value,
    start: dom.filterStart.value, end: dom.filterEnd.value };
}

function renderFilterOptions() {
  const models = [...new Set(state.records.map((record) => record.model_version))].sort();
  const key = models.join('|');
  if (dom.filterModel.dataset.options !== key) {
    const previous = dom.filterModel.value;
    dom.filterModel.replaceChildren(new Option('全部模型', ''));
    for (const model of models) dom.filterModel.add(new Option(model, model));
    dom.filterModel.value = models.includes(previous) ? previous : '';
    dom.filterModel.dataset.options = key;
  }
}

function renderStorageWarning() {
  if (!dom.storageWarning) return;
  dom.storageWarning.hidden = !state.storageError;
  dom.storageWarningText.textContent = state.storageError;
}

function appendRows(target, rows) {
  target.textContent = '';
  for (const [label, value] of rows) {
    const row = el('div');
    row.append(el('dt', null, label), el('dd', null, value || '—'));
    target.appendChild(row);
  }
}

function renderModelInfo() {
  const contract = state.contract;
  dom.modelSummary.textContent = contract ? contract.model_version : '规格未加载';
  appendRows(dom.connectionMeta, [
    ['服务地址', location.origin], ['云端模型', state.health?.model_version || '尚未连接'],
    ['连接状态', state.health?.model_loaded ? '模型已就绪' : '未就绪'],
    ['访问口令', state.token ? '已设置（需测试认证）' : '未设置'],
  ]);
  if (contract) appendRows(dom.modelMeta, [
    ['网页登记模型', contract.model_version], ['类别版本', contract.category_version],
    ['模型 SHA-256', contract.model_sha256], ['低置信阈值', percent(contract.low_confidence_threshold)],
    ['输入规格', 'RGB 224 × 224 · 模型内部归一化'],
    ['传输副本', '最长边 2048 · JPEG · 灰底 · 清除 EXIF'],
  ]);
  dom.connectShortcut.hidden = Boolean(state.token);
  dom.connectionHint.textContent = !state.token ? '首次使用，请先保存组内访问口令。'
    : (state.health && contract && state.health.model_version !== contract.model_version ? '云端与网页模型不同，请更新网页后重试。' : '');
}

function exportRecords() {
  const data = { schema_version: 1, exported_at: new Date().toISOString(), records: state.records };
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `campus-records-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function setPhase(name) {
  const phases = ['prepare', 'infer', 'save'];
  for (const item of dom.processingSteps.children) {
    item.classList.toggle('active', item.dataset.step === name);
    item.classList.toggle('done', phases.indexOf(item.dataset.step) < phases.indexOf(name));
    if (item.dataset.step === name) item.setAttribute('aria-current', 'step');
    else item.removeAttribute('aria-current');
  }
}

function setPreview(blob) {
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = blob ? URL.createObjectURL(blob) : '';
  state.previewRecordId = '';
  if (state.previewUrl) dom.photoPreview.src = state.previewUrl;
  else dom.photoPreview.removeAttribute('src');
  dom.photoPreview.hidden = !state.previewUrl;
  dom.photoEmpty.hidden = Boolean(state.previewUrl);
}

async function resolveConflict(useLocal) {
  const record = state.ticket && findRecord(state.ticket.record_id);
  if (!record || !record.correction_conflict || state.syncing) return;
  const wanted = { corrected_id: record.corrected_id, revision: record.revision, corrected_at: record.corrected_at };
  dom.conflictCloud.disabled = true;
  dom.conflictLocal.disabled = true;
  try {
    // Re-uploading an existing UUID returns its current server state without inserting a duplicate.
    const server = Core.serverRecord(await api('/api/records', { method: 'POST', body: uploadPayload(record) }), record);
    if (record.revision !== wanted.revision || record.corrected_id !== wanted.corrected_id || record.corrected_at !== wanted.corrected_at) {
      throw new Error('本机修正刚有更新，请重新选择冲突处理方式。');
    }
    if (useLocal) {
      record.server_revision = server.revision;
      record.revision = Math.max(record.revision, server.revision) + 1;
      record.correction_conflict = false;
      record.correction_synced = false;
    } else {
      Core.adoptServerCorrection(record, server);
    }
    record.synced = true;
    saveState();
    renderTicket();
    renderRecords();
    if (useLocal) await syncAll({ silent: true });
  } catch (error) {
    setStatus(dom.ticketSync, error.message, true);
  } finally {
    dom.conflictCloud.disabled = false;
    dom.conflictLocal.disabled = false;
  }
}

/* ---------------- 启动 ---------------- */
async function loadCategories() {
  const responses = await Promise.all([CATEGORY_FILE, 'model-contract.json'].map((path) => fetch(path, { cache: 'no-cache' })));
  if (responses.some((response) => !response.ok)) throw new Error('模型或类别规格加载失败');
  const [data, contract] = await Promise.all(responses.map((response) => response.json()));
  const categories = Array.isArray(data.categories) ? data.categories.slice().sort((a, b) => a.id - b.id) : [];
  if (categories.length !== 10 || data.category_version !== contract.category_version
    || !Array.isArray(contract.labels) || !categories.every((category, index) => category.id === index && category.label_key === contract.labels[index])
    || !/^[a-f0-9]{64}$/.test(contract.model_sha256) || !Number.isFinite(contract.low_confidence_threshold)) throw new Error('模型与类别规格不一致');
  state.categories = categories;
  state.contract = contract;
  state.modelVersion = contract.model_version;
  dom.filterCategory.replaceChildren(new Option('全部类别', ''));
  dom.modelCategories.textContent = '';
  for (const category of categories) {
    dom.filterCategory.add(new Option(category.display_name, String(category.id)));
    dom.modelCategories.appendChild(el('li', null, category.display_name));
  }
  renderModelInfo();
  renderRecords();
}

function bindEvents() {
  document.querySelector('.skip-link').addEventListener('click', (event) => {
    event.preventDefault();
    document.getElementById('main').focus();
  });
  dom.inputCamera.addEventListener('change', onFileChosen);
  dom.inputLibrary.addEventListener('change', onFileChosen);

  dom.ticketAgain.addEventListener('click', () => {
    state.ticket = null;
    state.lastFile = null;
    setPreview(null);
    renderTicket();
    setStatus(dom.captureStatus, '', false);
  });

  dom.ticketCorrect.addEventListener('click', () => {
    dom.correction.hidden = !dom.correction.hidden;
  });

  dom.syncNow.addEventListener('click', () => syncAll({ silent: false }));
  dom.cancelInfer.addEventListener('click', () => state.inferController?.abort());
  dom.conflictCloud.addEventListener('click', () => resolveConflict(false));
  dom.conflictLocal.addEventListener('click', () => resolveConflict(true));
  for (const button of document.querySelectorAll('[data-export-records]')) button.addEventListener('click', exportRecords);
  for (const button of document.querySelectorAll('[data-settings]')) button.addEventListener('click', () => showView('settings', button.dataset.settings));
  dom.settingsBack.addEventListener('click', () => showView('settings'));
  const filters = [dom.filterModel, dom.filterCategory, dom.filterStatus, dom.filterStart, dom.filterEnd];
  for (const input of filters) input.addEventListener('change', () => { state.visibleRecords = PAGE_SIZE; renderRecords(); });
  dom.filterReset.addEventListener('click', () => {
    for (const input of filters) input.value = '';
    state.visibleRecords = PAGE_SIZE;
    renderRecords();
  });
  dom.loadMore.addEventListener('click', () => { state.visibleRecords += PAGE_SIZE; renderRecords(); });

  dom.clearAll.addEventListener('click', () => {
    if (!state.records.length) return;
    const pending = state.records.filter(isPending).length;
    const confirmText = pending
      ? `本机有 ${pending} 条记录还没上报，清空后就无法补传；已上报的记录在云端仍然保留。确定清空本机 ${state.records.length} 条记录吗？`
      : `清空本机 ${state.records.length} 条记录，云端已入库的记录不受影响。确定清空吗？`;
    if (!window.confirm(confirmText)) return;
    state.records = [];
    state.ticket = null;
    state.lastFile = null;
    setPreview(null);
    saveState();
    renderRecords();
    renderTicket();
    setStatus(dom.recordsStatus, '本机记录已清空，云端记录不受影响。', false);
  });

  dom.tokenForm.addEventListener('submit', (event) => {
    event.preventDefault();
    state.token = dom.tokenInput.value.trim();
    const saved = saveState();
    setStatus(dom.settingsStatus, saved ? (state.token ? '口令已保存在本机。' : '口令已清空。') : state.storageError, !saved);
    renderStorageInfo();
    renderModelInfo();
  });

  dom.testConnection.addEventListener('click', async () => {
    setStatus(dom.settingsStatus, '正在检查…', false);
    try {
      const data = await refreshHealth();
      if (data.model_loaded) {
        setStatus(dom.settingsStatus, `服务器正常，模型 ${data.model_version} 已就绪。`, false);
      } else {
        setStatus(dom.settingsStatus, `服务器可访问，但模型状态为 ${data.model_status}。`, true);
      }
      if (!state.token) {
        setStatus(dom.settingsStatus, '服务可访问；请先保存口令，再测试认证。', true);
        return;
      }
      if (state.token) {
        try {
          await api('/api/records?page=0&page_size=1');
          setStatus(dom.settingsStatus, `${dom.settingsStatus.textContent} 口令校验通过。`, false);
        } catch (error) {
          setStatus(dom.settingsStatus, `${dom.settingsStatus.textContent} 但口令校验失败：${error.message}`, true);
        }
      }
    } catch (error) {
      setStatus(dom.settingsStatus, error.message, true);
    }
  });

  dom.clearStorage.addEventListener('click', () => {
    const pending = state.records.filter(isPending).length;
    if (!window.confirm(`清除本机口令与全部 ${state.records.length} 条记录？其中 ${pending} 条待同步，建议先导出。云端已入库记录仍保留。`)) return;
    // 只保留设备标识，避免下次上报被当成新设备
    const clientId = state.clientId;
    state.token = '';
    state.records = [];
    state.ticket = null;
    state.lastFile = null;
    setPreview(null);
    state.clientId = clientId;
    saveState();
    dom.tokenInput.value = '';
    renderRecords();
    renderTicket();
    renderModelInfo();
    setStatus(dom.settingsStatus, state.storageError || '本机数据已清除。', Boolean(state.storageError));
  });

  for (const button of dom.tabButtons) {
    button.addEventListener('click', () => showView(button.dataset.view));
  }

  window.addEventListener('hashchange', () => showView(viewFromHash(), settingsPageFromHash(), true));
  window.addEventListener('popstate', () => showView(viewFromHash(), settingsPageFromHash(), true));
  window.addEventListener('online', () => {
    refreshHealth().catch(() => {});
    syncAll({ silent: true });
  });
  window.addEventListener('offline', () => updateTicketSync());

  setInterval(() => {
    if (!document.hidden && navigator.onLine && state.records.some((record) => isPending(record) && !record.correction_conflict)) syncAll({ silent: true });
  }, RETRY_INTERVAL_MS);

  setInterval(() => { if (!document.hidden && navigator.onLine) refreshHealth().catch(() => {}); }, 120000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && navigator.onLine) {
      refreshHealth().catch(() => {});
      syncAll({ silent: true });
    }
  });
}

function onFileChosen(event) {
  const input = event.target;
  const file = input.files && input.files[0];
  input.value = '';                    // 允许再次选择同一张图片
  if (!file) return;
  dom.correction.hidden = true;
  recognize(file);
}

function cacheDom() {
  dom.healthBadge = document.getElementById('health-badge');
  dom.viewCapture = document.getElementById('view-capture');
  dom.viewRecords = document.getElementById('view-records');
  dom.viewSettings = document.getElementById('view-settings');
  dom.inputCamera = document.getElementById('input-camera');
  dom.inputLibrary = document.getElementById('input-library');
  dom.btnCamera = dom.inputCamera.closest('label');
  dom.btnLibrary = dom.inputLibrary.closest('label');
  dom.captureStatus = document.getElementById('capture-status');
  dom.ticket = document.getElementById('ticket');
  dom.ticketName = document.getElementById('ticket-name');
  dom.ticketConfidence = document.getElementById('ticket-confidence');
  dom.ticketFlag = document.getElementById('ticket-flag');
  dom.ticketOriginal = document.getElementById('ticket-original');
  dom.ticketMeta = document.getElementById('ticket-meta');
  dom.ticketCorrect = document.getElementById('ticket-correct');
  dom.ticketAgain = document.getElementById('ticket-again');
  dom.correction = document.getElementById('correction');
  dom.categoryGrid = document.getElementById('category-grid');
  dom.ticketSync = document.getElementById('ticket-sync');
  dom.mTotal = document.getElementById('m-total');
  dom.mPending = document.getElementById('m-pending');
  dom.mCorrected = document.getElementById('m-corrected');
  dom.recordList = document.getElementById('record-list');
  dom.recordsEmpty = document.getElementById('records-empty');
  dom.recordsStatus = document.getElementById('records-status');
  dom.syncNow = document.getElementById('sync-now');
  dom.clearAll = document.getElementById('clear-all');
  dom.tokenForm = document.getElementById('token-form');
  dom.tokenInput = document.getElementById('token');
  dom.testConnection = document.getElementById('test-connection');
  dom.storageInfo = document.getElementById('storage-info');
  dom.clearStorage = document.getElementById('clear-storage');
  dom.tabButtons = Array.from(document.querySelectorAll('.tabbar button'));
  for (const [key, id] of Object.entries({
    settingsStatus: 'settings-status', resultEmpty: 'result-empty', storageWarning: 'storage-warning',
    storageWarningText: 'storage-warning-text', photoPreview: 'photo-preview', photoEmpty: 'photo-empty',
    cancelInfer: 'cancel-infer', processingSteps: 'processing-steps', ticketConflictActions: 'ticket-conflict-actions',
    conflictCloud: 'conflict-cloud', conflictLocal: 'conflict-local', filterModel: 'filter-model',
    filterCategory: 'filter-category', filterStatus: 'filter-status', filterStart: 'filter-start',
    filterEnd: 'filter-end', filterReset: 'filter-reset', filterCount: 'filter-count', loadMore: 'load-more',
    settingsOverview: 'settings-overview', settingsDetail: 'settings-detail', settingsTitle: 'settings-title',
    settingsBack: 'settings-back', modelSummary: 'model-summary', modelMeta: 'model-meta',
    connectionMeta: 'connection-meta', modelCategories: 'model-categories', connectionHint: 'connection-hint',
    connectShortcut: 'connect-shortcut',
  })) dom[key] = document.getElementById(id);
  dom.settingsPages = Array.from(document.querySelectorAll('[data-settings-page]'));
}

async function init() {
  cacheDom();
  loadState();
  bindEvents();
  dom.tokenInput.value = state.token;
  showView(state.view, state.settingsPage, true);
  renderStorageWarning();
  renderModelInfo();
  renderRecords();
  renderTicket();
  try {
    await loadCategories();
  } catch (error) {
    setStatus(dom.captureStatus, '模型或类别规格加载失败，请刷新页面重试。', true);
  }
  renderTicket();
  refreshHealth().catch(() => {});
  if (navigator.onLine && state.records.some(isPending)) syncAll({ silent: true });
}

/* 脚本以 defer 加载，此时 DOM 已解析完成 */
init();
