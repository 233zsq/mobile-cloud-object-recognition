import * as Core from '../../core.js';
import { el } from './dom.js';
import { percent, durationText, localTime } from '../format.js';

export function createRecordsView({ state, dom, ui, handlers }) {
  const isPending = Core.isPending;
  function recordRow(record) {
    const item = el('li');
    const head = el('div', 'head');
    const name = record.corrected_label === 'other' ? '其他'
      : record.corrected_id !== null && record.corrected_id !== undefined
        ? ui.categoryName(record.corrected_id, record.label_key)
        : ui.categoryName(record.predicted_id, record.label_key);
    const title = el('span', 'title', name);
    if (Core.hasCorrection(record)) {
      title.appendChild(el('em', null, `原预测 ${ui.categoryName(record.predicted_id, record.label_key)}`));
    }
    head.appendChild(title);
    head.appendChild(el('span', 'conf', percent(record.confidence)));
    item.appendChild(head);
    item.appendChild(el('div', 'sub', `${localTime(record.captured_at)} · 模型 ${record.model_version} · 云端识别 · 耗时 ${durationText(record.total_ms)}`));

    const badges = el('div', 'badges');
    badges.appendChild(el('span', 'tag', record.synced ? '已上报' : '待上报'));
    if (Core.hasCorrection(record)) {
      badges.appendChild(el('span', 'tag fixed', record.correction_synced && !record.correction_conflict ? '修正已上报' : '修正待上报'));
    }
    if (record.correction_conflict) badges.appendChild(el('span', 'tag pending', '修订冲突'));
    if (record.low_confidence && !record.scope_manually_confirmed) badges.appendChild(el('span', 'tag pending', '需要确认'));
    if (record.scope_manually_confirmed) badges.appendChild(el('span', 'tag fixed', '已人工确认'));
    item.appendChild(badges);

    const actions = el('div', 'row-actions');
    const correctButton = el('button', 'secondary', record.correction_conflict ? '处理冲突' : '纠正类别');
    correctButton.type = 'button';
    correctButton.addEventListener('click', () => handlers.openRecord(record.record_id));
    const syncButton = el('button', 'secondary', '同步');
    syncButton.type = 'button';
    syncButton.disabled = !isPending(record) || record.correction_conflict || state.syncing;
    // Every trigger shares one queue, including row buttons, online events and retries.
    syncButton.title = '通过统一队列同步待传记录';
    syncButton.addEventListener('click', () => handlers.syncAll({ silent: false }));
    const deleteButton = el('button', 'secondary danger', '删除本机');
    deleteButton.type = 'button';
    deleteButton.disabled = state.syncing;
    deleteButton.addEventListener('click', () => handlers.deleteRecord(record.record_id));
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
    ui.renderStorageInfo();
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

  return { recordRow, renderRecords, currentFilters, renderFilterOptions };
}
