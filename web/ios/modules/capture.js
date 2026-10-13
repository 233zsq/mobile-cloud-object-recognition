import * as Core from '../core.js';
import { ApiFailure } from './api.js';
import { uuidv4, durationText } from './format.js';
import { INFER_TIMEOUT_MS } from './state.js';

export function createCapture({ state, ui, api, images, records }) {
  async function inferOnce(blob, signal, contract) {
    const requestId = uuidv4();
    const body = new FormData();
    body.append('request_id', requestId);
    body.append('model_version', contract.model_version);
    body.append('image', blob, 'photo.jpg');
    const result = await api('/api/infer', { method: 'POST', body, timeout: INFER_TIMEOUT_MS, signal });
    return Core.validateInference(result, { requestId, contract, categories: state.categories });
  }

  async function recognize(file) {
    if (state.busy || state.pendingConfirmation) return;
    state.lastFile = file;
    if (state.categories.length !== 10) {
      ui.setCaptureStatus('模型规格尚未加载，请刷新页面重试。', true);
      return;
    }
    if (!state.token) {
      ui.setCaptureStatus('请先在「我的 → 云端连接」保存组内访问口令。', true);
      ui.renderRetryButton();
      ui.showView('settings', 'cloud');
      return;
    }
    const contract = state.contract;
    if (!contract) {
      ui.setCaptureStatus('请先刷新模型列表并选择一个就绪的云端模型。', true);
      ui.renderRetryButton();
      return;
    }
    state.ticket = null;
    ui.renderTicket();
    const controller = new AbortController();
    state.inferController = controller;
    ui.setPreview(null);
    const capturedAt = new Date().toISOString();
    ui.setBusy(true, '正在准备图片…');
    ui.setPhase('prepare');
    const started = Date.now();
    try {
      const blob = await images.makeTransferCopy(file);
      if (controller.signal.aborted) throw new ApiFailure('CANCELLED', '本次识别已取消，未保存识别记录。', 0);
      ui.setPreview(blob);
      ui.setBusy(true, '正在上传并识别…');
      ui.setPhase('infer');
      const catalog = Core.validateModels(await api('/api/models', { signal: controller.signal }), state.categories);
      if (controller.signal.aborted) throw new ApiFailure('CANCELLED', '本次识别已取消，未保存识别记录。', 0);
      const current = catalog.models.find((model) => model.model_version === contract.model_version && model.available);
      if (!current || current.model_sha256 !== contract.model_sha256 || current.labels_sha256 !== contract.labels_sha256
        || current.low_confidence_threshold !== contract.low_confidence_threshold || current.category_version !== contract.category_version) {
        throw new ApiFailure('MODEL_VERSION_MISMATCH', '所选模型不可用或规格已变化，请刷新模型列表后手动选择。', 409);
      }
      const result = await inferOnce(blob, controller.signal, contract);
      if (controller.signal.aborted) throw new ApiFailure('CANCELLED', '本次识别已取消，未保存识别记录。', 0);
      ui.setPhase('save');
      const totalMs = Date.now() - started;
      const record = records.recordFromResult(result, totalMs);
      record.captured_at = capturedAt;
      record.scope_decision = Core.scopeDecision(result, contract, state.scopePolicy);
      if (record.scope_decision.status !== 'unavailable' && !record.scope_decision.policy_sha256)
        record.scope_decision.policy_sha256 = state.scopePolicySha256;
      if (record.scope_decision.status === 'accepted') records.rememberRecord(record);
      else state.pendingConfirmation = record;
      state.ticket = record;
      state.previewRecordId = record.record_id;
      state.lastFile = null;
      ui.renderTicket();
      ui.setCaptureStatus(state.pendingConfirmation
        ? '暂不确定：请确认类别，或不保存并重新拍摄。本次结果尚未保存和上报。'
        : `识别完成，用时 ${durationText(totalMs)}。${state.storageError ? '本机保存失败，请立即同步或导出。' : ''}`, Boolean(state.storageError));
      ui.focusTicket();
      if (!state.pendingConfirmation) records.syncAll({ silent: true });
    } catch (error) {
      if (controller.signal.aborted) error = new ApiFailure('CANCELLED', '本次识别已取消，未保存识别记录。', 0);
      ui.setCaptureStatus(`${error.message} ${error.code === 'CANCELLED' ? '可重新选择图片或重试。' : '可以点「再试一次」重发这张图片。'}`, error.code !== 'CANCELLED');
      ui.renderRetryButton();
    } finally {
      state.inferController = null;
      ui.setBusy(false);
    }
  }

  function confirmPending(categoryId) {
    const pending = state.pendingConfirmation;
    if (!pending || state.busy) return;
    const record = Core.confirmScopedRecord(pending, categoryId, new Date().toISOString());
    state.pendingConfirmation = null;
    state.ticket = record;
    state.lastFile = null;
    ui.hideCorrection();
    records.rememberRecord(record);
    ui.renderTicket();
    ui.setBusy(false);
    ui.setCaptureStatus(state.storageError || '已人工确认并保存，正在上报记录。', Boolean(state.storageError));
    records.syncAll({ silent: true });
  }

  function discardPending() {
    if (!state.pendingConfirmation || state.busy) return;
    state.pendingConfirmation = null;
    state.ticket = null;
    state.lastFile = null;
    ui.hideCorrection();
    ui.setPreview(null);
    ui.renderTicket();
    ui.setBusy(false);
    ui.setCaptureStatus('本次结果未保存和上报，可以重新拍摄或选择图片。', false);
  }

  return { inferOnce, recognize, confirmPending, discardPending };
}
