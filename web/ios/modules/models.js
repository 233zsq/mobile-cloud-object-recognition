import * as Core from '../core.js';
import { CATEGORY_FILE } from './state.js';
import { readStaticJson } from './api.js';

export function createModels({ state, ui, persistence, api }) {
  async function refreshHealth() {
    try {
      const data = await api('/api/health', { auth: false, timeout: 8000 });
      state.health = data;
      ui.renderHealthBadge();
      ui.renderModelInfo();
      return data;
    } catch (error) {
      state.health = null;
      ui.renderHealthBadge();
      ui.renderModelInfo();
      throw error;
    }
  }

  async function refreshModels() {
    if (state.busy || state.pendingConfirmation || state.modelsLoading || !state.token || state.categories.length !== 10) return;
    state.modelsLoading = true;
    ui.renderModelSelection();
    const token = state.token;
    try {
      const data = Core.validateModels(await api('/api/models'), state.categories);
      if (token !== state.token) throw new Error('口令已变化，请重新加载模型。');
      for (const model of data.models) {
        const bytes = new TextEncoder().encode(model.labels.join('\n') + '\n');
        const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), (value) => value.toString(16).padStart(2, '0')).join('');
        if (digest !== model.labels_sha256) throw new Error('云端标签哈希不一致。');
      }
      if (token !== state.token) throw new Error('口令已变化，请重新加载模型。');
      state.cloudModels = data.models;
      const version = state.modelVersion || data.default_model_version;
      const selected = data.models.find((model) => model.model_version === version && model.available);
      state.contract = selected || null;
      state.modelVersion = version;
      state.modelStatus = selected ? selected.description : '上次选择的模型不可用，请手动选择就绪模型。';
      persistence.saveState();
    } catch (error) {
      state.cloudModels = [];
      state.contract = null;
      state.modelStatus = error.message;
    } finally {
      state.modelsLoading = false;
      ui.renderModelSelection();
      ui.renderModelInfo();
    }
  }

  async function loadCategories() {
    const [data, contract] = await readStaticJson([CATEGORY_FILE, 'model-contract.json']);
    const categories = Array.isArray(data.categories) ? data.categories.slice().sort((a, b) => a.id - b.id) : [];
    if (categories.length !== 10 || data.category_version !== contract.category_version
      || !Array.isArray(contract.labels) || !categories.every((category, index) => category.id === index && category.label_key === contract.labels[index])
      || !/^[a-f0-9]{64}$/.test(contract.model_sha256) || !Number.isFinite(contract.low_confidence_threshold)) throw new Error('模型与类别规格不一致');
    state.categories = categories;
    // Preserve the original LF or CRLF bytes declared by the frozen policy.
    // A missing or damaged policy disables automatic saving, not inference.
    state.scopePolicy = null;
    state.scopePolicySha256 = '';
    try {
      const serialized = Core.scopePolicyText(contract.scope_policy, contract.scope_policy_newline);
      const bytes = new TextEncoder().encode(serialized);
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), (value) => value.toString(16).padStart(2, '0')).join('');
      if (hash === contract.scope_policy_sha256 && Core.scopePolicyMatches(contract, contract.scope_policy)) {
        state.scopePolicy = contract.scope_policy;
        state.scopePolicySha256 = hash;
      }
    } catch (error) { /* Keep manual confirmation available without a valid rule. */ }
    state.contract = contract;
    if (!state.modelVersion) state.modelVersion = contract.model_version;
    ui.renderCategories();
    ui.renderModelInfo();
    ui.renderRecords();
  }

  function selectModel(version) {
    if (state.busy || state.pendingConfirmation || state.modelsLoading) return;
    const model = state.cloudModels.find((item) => item.model_version === version && item.available);
    if (!model) return;
    state.contract = model;
    state.modelVersion = model.model_version;
    state.modelStatus = model.description;
    persistence.saveState();
    ui.renderModelSelection();
    ui.renderModelInfo();
  }
  return { refreshHealth, refreshModels, loadCategories, selectModel };
}
