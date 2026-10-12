/* Shared by the browser and dependency-free regression tests. */
(function (root, factory) {
  'use strict';
  const core = factory();
  if (typeof module === 'object' && module.exports) module.exports = core;
  else root.RecognitionCore = core;
})(typeof window === 'object' ? window : this, function () {
  'use strict';

  const hasCorrection = (record) => record.corrected_id !== null && record.corrected_id !== undefined;
  const isPending = (record) => !record.synced || (hasCorrection(record) && !record.correction_synced);
  const sameTime = (a, b) => Number.isFinite(Date.parse(a)) && Date.parse(a) === Date.parse(b);
  const sameCorrection = (record, sent) => record.revision === sent.revision
    && record.corrected_id === sent.corrected_id && sameTime(record.corrected_at, sent.corrected_at);

  function trimRecords(records, maximum) {
    let over = Math.max(0, records.length - maximum);
    const removed = new Set();
    // Records are newest first. Pending edits and conflicts must survive cleanup.
    for (let index = records.length - 1; index >= 0 && over > 0; index -= 1) {
      const record = records[index];
      if (record.synced && record.correction_synced && !record.correction_conflict) {
        removed.add(index);
        over -= 1;
      }
    }
    return records.filter((_, index) => !removed.has(index));
  }

  function writeState(storage, key, value) {
    try {
      storage.setItem(key, JSON.stringify(value));
      return { ok: true };
    } catch (error) {
      return { ok: false, message: '本机保存失败，当前记录仅在本次打开期间保留。请立即同步或导出记录，暂时不要关闭页面。' };
    }
  }

  function serverRecord(response, record) {
    const server = response && response.record;
    if (!server || server.record_id !== record.record_id || !Number.isSafeInteger(server.revision)
      || server.revision < 0 || (hasCorrection(server)
        && (!Number.isInteger(server.corrected_id) || server.corrected_id < 0 || server.corrected_id > 9
          || !Number.isFinite(Date.parse(server.corrected_at))))) {
      throw new Error('服务器返回的记录无效，本机修改已保留，请稍后重试。');
    }
    return server;
  }

  function adoptServerCorrection(record, server) {
    record.revision = server.revision;
    record.server_revision = server.revision;
    record.corrected_id = server.corrected_id ?? null;
    record.corrected_at = server.corrected_at ?? null;
    record.correction_synced = true;
    record.correction_conflict = false;
  }

  async function syncRecord(record, { request, uploadPayload }) {
    if (!record.synced) {
      const server = serverRecord(await request('/api/records', {
        method: 'POST', body: uploadPayload(record),
      }), record);
      record.synced = true;
      record.synced_at = new Date().toISOString();
      record.category_version = server.category_version;
      record.server_revision = server.revision;
      // A correction may have been made while POST was in flight.
      if (!hasCorrection(record) || record.correction_synced) {
        adoptServerCorrection(record, server);
      } else if (sameCorrection(record, server)) {
        record.correction_synced = true;
      } else if (server.revision >= record.revision) {
        record.correction_conflict = true;
      }
    }
    if (hasCorrection(record) && !record.correction_synced && !record.correction_conflict) {
      const sent = {
        corrected_id: record.corrected_id,
        revision: record.revision,
        corrected_at: record.corrected_at,
      };
      try {
        const server = serverRecord(await request(`/api/records/${record.record_id}/label`, {
          method: 'PATCH', body: sent,
        }), record);
        if (!sameCorrection(server, sent)) throw new Error('服务器未确认本次修正，本机修改已保留。');
        record.server_revision = Math.max(record.server_revision || 0, server.revision);
        // Only acknowledge the exact edit sent, never a newer edit made during await.
        if (sameCorrection(record, sent)) {
          record.correction_synced = true;
          record.correction_conflict = false;
        }
      } catch (error) {
        if (error.status === 409) {
          record.correction_conflict = true;
        } else {
          if (error.status === 404) record.synced = false;
          throw error;
        }
      }
    }
    return record;
  }

  function createSyncQueue({ getRecords, sync, onChange = () => {} }) {
    let running = null;
    let requested = false;
    async function drain() {
      let count = 0;
      do {
        requested = false;
        const pending = getRecords().filter((record) => isPending(record) && !record.correction_conflict);
        for (const record of pending) {
          if (!getRecords().includes(record)) continue;
          try {
            await sync(record);
            count += 1;
          } finally {
            onChange();
          }
        }
      } while (requested);
      return count;
    }
    return {
      run() {
        requested = true;
        if (!running) running = drain().finally(() => { running = null; });
        return running;
      },
    };
  }

  function filterRecords(records, filters) {
    return records.filter((record) => {
      const effective = hasCorrection(record) ? record.corrected_id : record.predicted_id;
      if (filters.model && record.model_version !== filters.model) return false;
      if (filters.category !== '' && effective !== Number(filters.category)) return false;
      if (filters.status === 'pending' && !isPending(record)) return false;
      if (filters.status === 'conflict' && !record.correction_conflict) return false;
      if (filters.status === 'corrected' && !hasCorrection(record)) return false;
      const instant = new Date(record.captured_at);
      if (filters.start && instant < new Date(`${filters.start}T00:00:00`)) return false;
      if (filters.end) {
        const end = new Date(`${filters.end}T00:00:00`);
        end.setDate(end.getDate() + 1);
        if (instant >= end) return false;
      }
      return true;
    });
  }

  function validateModels(data, categories) {
    const validVersion = (value) => typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(value);
    const hash = (value) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
    if (categories.length !== 10 || !data || !Array.isArray(data.models) || data.models.length < 1 || data.models.length > 2
      || new Set(data.models.map((model) => model.model_version)).size !== data.models.length
      || !data.models.some((model) => model.model_version === data.default_model_version)) throw new Error('云端模型列表无效。');
    for (const model of data.models) {
      if (!validVersion(model.model_version) || !validVersion(model.category_version)
        || !hash(model.model_sha256) || !hash(model.labels_sha256) || model.status !== 'frozen'
        || typeof model.available !== 'boolean' || !Array.isArray(model.labels) || model.labels.length !== 10
        || !categories.every((category, index) => category.label_key === model.labels[index])
        || !Number.isFinite(model.low_confidence_threshold) || model.low_confidence_threshold < 0 || model.low_confidence_threshold > 1
        || typeof model.display_name !== 'string' || !model.display_name.length || model.display_name.length > 64
        || typeof model.description !== 'string' || !model.description.length || model.description.length > 160) throw new Error('云端模型规格不兼容。');
    }
    return data;
  }

  function validateInference(result, { requestId, contract, categories }) {
    const invalid = (message) => { throw new Error(message); };
    if (!result || result.request_id !== requestId) invalid('响应编号不匹配，结果未保存，请重试。');
    if (result.model_version !== contract.model_version || result.model_sha256 !== contract.model_sha256) {
      invalid('云端模型与网页登记的版本或哈希不一致，请更新网页后重试。');
    }
    const scores = result.scores;
    if (!Array.isArray(scores) || scores.length !== 10 || categories.length !== 10
      || !scores.every((value) => Number.isFinite(value) && value >= 0 && value <= 1)
      || Math.abs(scores.reduce((sum, value) => sum + value, 0) - 1) > 0.0001) invalid('云端分数无效，结果未保存。');
    const top = scores.indexOf(Math.max(...scores));
    if (result.predicted_id !== top || result.label_key !== categories[top].label_key
      || result.confidence !== scores[top]) invalid('云端类别与分数不一致，结果未保存。');
    if (![result.preprocess_ms, result.inference_ms].every((value) => Number.isFinite(value) && value >= 0 && value < 60000)) {
      invalid('云端耗时无效，结果未保存。');
    }
    if (result.low_confidence !== (result.confidence < contract.low_confidence_threshold)) invalid('云端阈值与网页规格不一致，请更新网页。');
    return result;
  }

  return { hasCorrection, isPending, trimRecords, writeState, serverRecord, adoptServerCorrection,
    syncRecord, createSyncQueue, filterRecords, validateInference, validateModels };
});
