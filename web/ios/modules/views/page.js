
export function createPageView({ state, dom, ui }) {
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

  function setStatus(node, message, isError) {
    if (!node) return;
    node.textContent = message || '';
    node.classList.toggle('error', Boolean(isError));
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
    if (name === 'records') ui.renderRecords();
    if (name === 'settings') ui.renderStorageInfo();
    window.scrollTo(0, 0);
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
      cloudModel: 'cloud-model', cloudModelStatus: 'cloud-model-status', refreshModels: 'refresh-models',
      scopeActions: 'scope-actions', scopeConfirm: 'scope-confirm', scopeChoose: 'scope-choose', scopeDiscard: 'scope-discard',
      ticketActions: 'ticket-actions', correctionHint: 'correction-hint',
    })) dom[key] = document.getElementById(id);
    dom.settingsPages = Array.from(document.querySelectorAll('[data-settings-page]'));
  }

  return { categoryName, viewFromHash, settingsPageFromHash, setStatus, showView, cacheDom };
}
