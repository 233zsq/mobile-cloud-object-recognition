import { el } from './dom.js';
import { percent, durationText } from '../format.js';
import * as Core from '../../core.js';

export function createCaptureView({ state, dom, ui, handlers }) {
  const isPending = Core.isPending;
  function setBusy(busy, message) {
    state.busy = busy;
    const blocked = busy || Boolean(state.pendingConfirmation);
    dom.inputCamera.disabled = blocked;
    dom.inputLibrary.disabled = blocked;
    dom.btnCamera.classList.toggle('busy', blocked);
    dom.btnLibrary.classList.toggle('busy', blocked);
    dom.cancelInfer.hidden = !busy;
    dom.processingSteps.hidden = !busy;
    dom.ticketAgain.disabled = busy;
    dom.cloudModel.disabled = blocked || state.modelsLoading || !state.cloudModels.length;
    dom.refreshModels.disabled = blocked || state.modelsLoading;
    dom.clearStorage.disabled = busy || state.syncing;
    if (message) ui.setStatus(dom.captureStatus, message, false);
  }

  function renderRetryButton() {
    if (!state.lastFile) return;
    const node = el('button', 'secondary', '再试一次');
    node.type = 'button';
    node.addEventListener('click', () => {
      const file = state.lastFile;
      if (file) handlers.recognize(file);
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
      // 手机顶栏空间有限：徽章只显示版本尾号（如 v2），完整版本放 tooltip 与票据里
      const tail = /(v\d+(?:\.\d+)*)$/.exec(state.contract?.model_version || state.health.model_version);
      badge.textContent = `云端 ${tail ? tail[1] : '就绪'}`;
      badge.classList.add('ok');
      badge.title = `所选模型 ${state.contract?.model_version || '尚未选择'}；默认 ${state.health.model_version}；服务版本 ${state.health.version}`;
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
    const pending = state.pendingConfirmation === ticket;
    dom.scopeActions.hidden = !pending;
    dom.ticketActions.hidden = pending;
    const shownId = ticket.corrected_id !== null && ticket.corrected_id !== undefined
      ? ticket.corrected_id
      : ticket.predicted_id;
    dom.ticketName.textContent = pending ? '暂不确定' : ui.categoryName(shownId, ticket.label_key);
    dom.ticketConfidence.textContent = percent(ticket.confidence);
    dom.ticketFlag.hidden = !pending && !ticket.low_confidence && !ticket.scope_manually_confirmed;
    dom.ticketFlag.textContent = pending ? ticket.scope_decision.reason
      : (ticket.scope_manually_confirmed ? '已人工确认；原始分类分数保留。' : '低于模型阈值，需要确认');
    if (pending) {
      dom.ticketOriginal.hidden = false;
      dom.ticketOriginal.textContent = `候选：${ui.categoryName(ticket.predicted_id, ticket.label_key)} · 上方为候选分数`;
      dom.scopeConfirm.textContent = `确认是${ui.categoryName(ticket.predicted_id, ticket.label_key)}并保存`;
    } else if (ticket.corrected_id !== null && ticket.corrected_id !== undefined) {
      dom.ticketOriginal.hidden = false;
      dom.ticketOriginal.textContent = `原预测：${ui.categoryName(ticket.predicted_id, ticket.label_key)}（已保留）`;
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
    if (state.pendingConfirmation === ticket) {
      dom.ticketConflictActions.hidden = true;
      ui.setStatus(dom.ticketSync, '等待人工确认，未生成识别记录。刷新或关闭页面会放弃本次待确认结果。', false);
      return;
    }
    const record = handlers.findRecord(ticket.record_id) || ticket;
    dom.ticketConflictActions.hidden = !record.correction_conflict;
    if (record.correction_conflict) {
      ui.setStatus(dom.ticketSync, '修订冲突：本机修正尚未上报，请选择如何处理。', true);
    } else if (state.storageError && isPending(record)) {
      ui.setStatus(dom.ticketSync, '本机保存失败，请立即同步或导出；关闭页面可能丢失这条待同步记录。', true);
    } else if (record.synced && (record.corrected_id === null || record.corrected_id === undefined || record.correction_synced)) {
      ui.setStatus(dom.ticketSync, '已上报到云端。', false);
    } else if (navigator.onLine) {
      ui.setStatus(dom.ticketSync, '等待上报，会自动重试，也可以在「记录」里立即同步。', false);
    } else {
      ui.setStatus(dom.ticketSync, '当前离线：记录已保存在本机，联网后自动补传。', false);
    }
  }

  function renderCorrectionGrid(ticket) {
    dom.categoryGrid.textContent = '';
    const pending = state.pendingConfirmation === ticket;
    dom.correctionHint.textContent = pending ? '选择实际类别并保存；原预测和分数会保留。' : '选择正确类别；原预测会保留。';
    const current = ticket.corrected_id !== null && ticket.corrected_id !== undefined
      ? ticket.corrected_id
      : ticket.predicted_id;
    for (const category of state.categories) {
      const button = el('button', category.id === current ? 'current' : null, category.display_name);
      button.type = 'button';
      button.addEventListener('click', () => {
        if (pending) { handlers.confirmPending(category.id); return; }
        if (category.id === current) return;
        handlers.correctRecord(ticket.record_id, category.id);
      });
      dom.categoryGrid.appendChild(button);
    }
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

  function hideCorrection() { dom.correction.hidden = true; }
  function setCaptureStatus(message, error) { ui.setStatus(dom.captureStatus, message, error); }
  function setRecordsStatus(message, error) { ui.setStatus(dom.recordsStatus, message, error); }
  function setTicketStatus(message, error) { ui.setStatus(dom.ticketSync, message, error); }
  function setConflictBusy(busy) { dom.conflictCloud.disabled = busy; dom.conflictLocal.disabled = busy; }
  function focusTicket() {
    if (state.view === 'capture' && window.innerWidth < 700) {
      dom.ticket.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    }
  }
  return { setBusy, renderRetryButton, renderHealthBadge, renderTicket, updateTicketSync, renderCorrectionGrid, setPhase, setPreview, hideCorrection, setCaptureStatus, setRecordsStatus, setTicketStatus, setConflictBusy, focusTicket };
}
