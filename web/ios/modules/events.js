import { RETRY_INTERVAL_MS, PAGE_SIZE } from './state.js';
import * as Core from '../core.js';

export function createEvents({ state, dom, ui, persistence, api, records, capture, models }) {
  const isPending = Core.isPending;
  function bindEvents() {
    dom.refreshModels.addEventListener('click', models.refreshModels);
    dom.cloudModel.addEventListener('change', () => models.selectModel(dom.cloudModel.value));
    document.querySelector('.skip-link').addEventListener('click', (event) => {
      event.preventDefault();
      document.getElementById('main').focus();
    });
    dom.inputCamera.addEventListener('change', onFileChosen);
    dom.inputLibrary.addEventListener('change', onFileChosen);

    dom.ticketAgain.addEventListener('click', () => {
      state.ticket = null;
      state.lastFile = null;
      ui.setPreview(null);
      ui.renderTicket();
      ui.setStatus(dom.captureStatus, '', false);
    });

    dom.ticketCorrect.addEventListener('click', () => {
      dom.correction.hidden = !dom.correction.hidden;
    });
    dom.scopeConfirm.addEventListener('click', () => capture.confirmPending(state.pendingConfirmation?.predicted_id));
    dom.scopeChoose.addEventListener('click', () => { dom.correction.hidden = !dom.correction.hidden; });
    dom.scopeDiscard.addEventListener('click', capture.discardPending);

    dom.syncNow.addEventListener('click', () => records.syncAll({ silent: false }));
    dom.cancelInfer.addEventListener('click', () => state.inferController?.abort());
    dom.conflictCloud.addEventListener('click', () => records.resolveConflict(false));
    dom.conflictLocal.addEventListener('click', () => records.resolveConflict(true));
    for (const button of document.querySelectorAll('[data-export-records]')) button.addEventListener('click', exportRecords);
    for (const button of document.querySelectorAll('[data-settings]')) button.addEventListener('click', () => ui.showView('settings', button.dataset.settings));
    dom.settingsBack.addEventListener('click', () => ui.showView('settings'));
    const filters = [dom.filterModel, dom.filterCategory, dom.filterStatus, dom.filterStart, dom.filterEnd];
    for (const input of filters) input.addEventListener('change', () => { state.visibleRecords = PAGE_SIZE; ui.renderRecords(); });
    dom.filterReset.addEventListener('click', () => {
      for (const input of filters) input.value = '';
      state.visibleRecords = PAGE_SIZE;
      ui.renderRecords();
    });
    dom.loadMore.addEventListener('click', () => { state.visibleRecords += PAGE_SIZE; ui.renderRecords(); });

    dom.clearAll.addEventListener('click', () => {
      if (!state.records.length) return;
      const pending = state.records.filter(isPending).length;
      const confirmText = pending
        ? `本机有 ${pending} 条记录还没上报，清空后就无法补传；已上报的记录在云端仍然保留。确定清空本机 ${state.records.length} 条记录吗？`
        : `清空本机 ${state.records.length} 条记录，云端已入库的记录不受影响。确定清空吗？`;
      if (!window.confirm(confirmText)) return;
      state.records = [];
      state.ticket = null;
      state.pendingConfirmation = null;
      state.lastFile = null;
      ui.setPreview(null);
      persistence.saveState();
      ui.renderRecords();
      ui.renderTicket();
      ui.setBusy(false);
      ui.setStatus(dom.recordsStatus, '本机记录已清空，云端记录不受影响。', false);
    });

    dom.tokenForm.addEventListener('submit', (event) => {
      event.preventDefault();
      state.token = dom.tokenInput.value.trim();
      state.cloudModels = [];
      state.contract = null;
      dom.cloudModel.replaceChildren(new Option('先设置访问口令', ''));
      dom.cloudModel.disabled = true;
      const saved = persistence.saveState();
      ui.setStatus(dom.settingsStatus, saved ? (state.token ? '口令已保存在本机。' : '口令已清空。') : state.storageError, !saved);
      ui.renderStorageInfo();
      ui.renderModelInfo();
      models.refreshModels();
    });

    dom.testConnection.addEventListener('click', async () => {
      ui.setStatus(dom.settingsStatus, '正在检查…', false);
      try {
        const data = await models.refreshHealth();
        if (data.model_loaded) {
          ui.setStatus(dom.settingsStatus, `服务器正常，模型 ${data.model_version} 已就绪。`, false);
        } else {
          ui.setStatus(dom.settingsStatus, `服务器可访问，但模型状态为 ${data.model_status}。`, true);
        }
        if (!state.token) {
          ui.setStatus(dom.settingsStatus, '服务可访问；请先保存口令，再测试认证。', true);
          return;
        }
        if (state.token) {
          try {
            await api('/api/records?page=0&page_size=1');
            ui.setStatus(dom.settingsStatus, `${dom.settingsStatus.textContent} 口令校验通过。`, false);
          } catch (error) {
            ui.setStatus(dom.settingsStatus, `${dom.settingsStatus.textContent} 但口令校验失败：${error.message}`, true);
          }
        }
      } catch (error) {
        ui.setStatus(dom.settingsStatus, error.message, true);
      }
    });

    dom.clearStorage.addEventListener('click', () => {
      const pending = state.records.filter(isPending).length;
      if (!window.confirm(`清除本机口令与全部 ${state.records.length} 条记录？其中 ${pending} 条待同步，建议先导出。云端已入库记录仍保留。`)) return;
      // 只保留设备标识，避免下次上报被当成新设备
      const clientId = state.clientId;
      state.token = '';
      state.contract = null;
      state.cloudModels = [];
      dom.cloudModel.replaceChildren(new Option('先设置访问口令', ''));
      dom.cloudModel.disabled = true;
      state.records = [];
      state.ticket = null;
      state.pendingConfirmation = null;
      state.lastFile = null;
      ui.setPreview(null);
      state.clientId = clientId;
      persistence.saveState();
      dom.tokenInput.value = '';
      ui.renderRecords();
      ui.renderTicket();
      ui.renderModelInfo();
      ui.setBusy(false);
      ui.setStatus(dom.settingsStatus, state.storageError || '本机数据已清除。', Boolean(state.storageError));
    });

    for (const button of dom.tabButtons) {
      button.addEventListener('click', () => ui.showView(button.dataset.view));
    }

    window.addEventListener('hashchange', () => ui.showView(ui.viewFromHash(), ui.settingsPageFromHash(), true));
    window.addEventListener('popstate', () => ui.showView(ui.viewFromHash(), ui.settingsPageFromHash(), true));
    window.addEventListener('online', () => {
      models.refreshHealth().catch(() => {});
      records.syncAll({ silent: true });
    });
    window.addEventListener('offline', () => ui.updateTicketSync());

    setInterval(() => {
      if (!document.hidden && navigator.onLine && state.records.some((record) => isPending(record) && !record.correction_conflict)) records.syncAll({ silent: true });
    }, RETRY_INTERVAL_MS);

    setInterval(() => { if (!document.hidden && navigator.onLine) models.refreshHealth().catch(() => {}); }, 120000);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && navigator.onLine) {
        models.refreshHealth().catch(() => {});
        records.syncAll({ silent: true });
      }
    });
  }

  function onFileChosen(event) {
    const input = event.target;
    const file = input.files && input.files[0];
    input.value = '';                    // 允许再次选择同一张图片
    if (!file) return;
    dom.correction.hidden = true;
    capture.recognize(file);
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

  function openRecord(recordId) {
    const record = records.findRecord(recordId);
    if (!record) return;

      if (state.pendingConfirmation) {
        state.ticket = state.pendingConfirmation;
        ui.showView('capture');
        ui.renderTicket();
        ui.setStatus(dom.captureStatus, '请先确认或放弃这张照片，再修改历史记录。', false);
        return;
      }
      state.ticket = record;
      ui.showView('capture');
      dom.correction.hidden = false;
      ui.renderTicket();

  }

  function deleteRecord(recordId) {
    const record = records.findRecord(recordId);
    if (!record || state.syncing) return;

      const confirmText = record.synced
        ? '这条记录已上报到云端，删除只影响本机显示，云端记录仍然保留。确定删除吗？'
        : '这条记录还没有上报，删除后就无法补传了。确定删除吗？';
      if (!window.confirm(confirmText)) return;
      state.records = state.records.filter((item2) => item2.record_id !== record.record_id);
      if (state.ticket && state.ticket.record_id === record.record_id) {
        state.ticket = null;
        ui.setPreview(null);
      }
      persistence.saveState();
      ui.renderRecords();
      ui.renderTicket();

  }

  return { bindEvents, onFileChosen, exportRecords, openRecord, deleteRecord };
}
