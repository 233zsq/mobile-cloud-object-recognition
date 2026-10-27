import * as Core from '../../core.js';
import { el } from './dom.js';
import { percent } from '../format.js';

export function createSettingsView({ state, dom, ui }) {
  const isPending = Core.isPending;
  function renderStorageInfo() {
    const pending = state.records.filter(isPending).length;
    dom.storageInfo.textContent = `${state.storageError ? '当前会话暂存' : '本机保存'} ${state.records.length} 条记录，其中 ${pending} 条待同步；`
      + `口令${state.token ? (state.storageError ? '仅本次会话可用' : '已保存') : '未设置'}。记录与口令不会自动同步到其他设备。`;
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
    const policy = contract && Object.prototype.hasOwnProperty.call(contract, 'scope_policy') ? contract.scope_policy : state.scopePolicy;
    dom.modelSummary.textContent = contract ? contract.model_version : '请选择云端模型';
    appendRows(dom.connectionMeta, [
      ['服务地址', location.origin], ['默认云端模型', state.health?.model_version || '尚未连接'],
      ['连接状态', state.health?.model_loaded ? '模型已就绪' : '未就绪'],
      ['访问口令', state.token ? '已设置（需测试认证）' : '未设置'],
    ]);
    appendRows(dom.modelMeta, contract ? [
      ['所选云端模型', contract.model_version], ['类别版本', contract.category_version],
      ['模型 SHA-256', contract.model_sha256], ['低置信阈值', percent(contract.low_confidence_threshold)],
      ['输入规格', 'RGB 224 × 224 · 模型内部归一化'],
      ['传输副本', '最长边 2048 · JPEG · 灰底 · 清除 EXIF'],
      ['确认规则', Core.scopePolicyMatches(contract, policy)
        ? `最高分 ≥${percent(policy.confidence_threshold)}，前两名相差 ≥${Math.round(policy.margin_threshold * 100)} 个百分点${policy.rule === 'learned_knownness_v1' ? `，范围分数 ≥${percent(policy.knownness_threshold)}` : ''}`
        : '无匹配规则，识别结果需人工确认'],
      ['规则 SHA-256', policy?.policy_sha256 || state.scopePolicySha256 || '未加载'],
    ] : [['当前选择', '请在识别页选择云端模型']]);
    dom.connectShortcut.hidden = Boolean(state.token);
    dom.connectionHint.textContent = !state.token ? '首次使用，请先保存组内访问口令。'
      : (!contract ? '请刷新模型列表并选择就绪模型。' : '');
    ui.renderHealthBadge();
  }

  function renderModelSelection() {
    dom.cloudModel.replaceChildren();
    if (!state.cloudModels.length) dom.cloudModel.add(new Option(state.token ? '模型未加载' : '先设置访问口令', ''));
    for (const model of state.cloudModels) {
      const option = new Option(`${model.display_name} · ${model.model_version}${model.available ? '' : '（暂不可用）'}`, model.model_version);
      option.disabled = !model.available;
      dom.cloudModel.add(option);
    }
    dom.cloudModel.value = state.contract && state.cloudModels.length ? state.modelVersion : '';
    dom.cloudModelStatus.textContent = state.modelStatus;
    const blocked = state.busy || Boolean(state.pendingConfirmation) || state.modelsLoading;
    dom.cloudModel.disabled = blocked || !state.cloudModels.length;
    dom.refreshModels.disabled = blocked;
  }

  function renderCategories() {
    dom.filterCategory.replaceChildren(new Option('全部类别', ''));
    dom.modelCategories.textContent = '';
    for (const category of state.categories) {
      dom.filterCategory.add(new Option(category.display_name, String(category.id)));
      dom.modelCategories.appendChild(el('li', null, category.display_name));
    }
    dom.filterCategory.add(new Option('其他（人工标注）', 'other'));
  }
  return { renderStorageInfo, renderStorageWarning, appendRows, renderModelInfo, renderModelSelection, renderCategories };
}
