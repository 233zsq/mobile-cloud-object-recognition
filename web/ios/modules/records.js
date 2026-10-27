import * as Core from '../core.js';

export function createRecords({ state, ui, persistence, api }) {
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
      scores: result.scores.slice(),
      preprocess_ms: result.preprocess_ms,
      inference_ms: result.inference_ms,
      total_ms: totalMs,
      corrected_id: null,
      corrected_label: null,
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
    persistence.trimRecords();
    persistence.saveState();
    ui.renderRecords();
  }

  function findRecord(recordId) {
    return state.records.find((record) => record.record_id === recordId) || null;
  }

  function uploadPayload(record) {
    const payload = {
      record_id: record.record_id,
      client_id: state.clientId,
      inference_source: record.inference_source,
      model_version: record.model_version,
      predicted_id: record.predicted_id,
      confidence: record.confidence,
      latency_ms: record.latency_ms,
      captured_at: record.captured_at,
    };
    if (record.scope_decision) payload.scope_decision = {
      status: record.scope_decision.status, policy_version: record.scope_decision.policy_version ?? null,
      policy_sha256: record.scope_decision.policy_sha256 ?? null, knownness: record.scope_decision.knownness ?? null,
      manual_confirmed: record.scope_manually_confirmed === true,
    };
    return payload;
  }

  function isPending(record) {
    return Core.isPending(record);
  }

  async function syncRecord(record) {
    return Core.syncRecord(record, { request: api, uploadPayload });
  }

  async function syncAll(options = {}) {
    const pending = state.records.filter((record) => isPending(record) && !record.correction_conflict);
    if (!pending.length) {
      if (!options.silent) {
        const conflict = state.records.some((record) => record.correction_conflict);
        ui.setRecordsStatus(conflict ? '有修订冲突，请点记录中的「处理冲突」。' : (state.records.length ? '全部记录都已上报。' : '还没有需要上报的记录。'), conflict);
      }
      return;
    }
    state.syncing = true;
    ui.renderRecords();
    try {
      const done = await syncQueue.run();
      const conflicts = state.records.filter((record) => record.correction_conflict).length;
      if (!options.silent || conflicts) {
        ui.setRecordsStatus(`本轮已处理 ${done} 次同步。${conflicts ? `另有 ${conflicts} 条修订冲突需要处理。` : ''}`, conflicts > 0);
      }
    } catch (error) {
      ui.setRecordsStatus(`还有 ${state.records.filter(isPending).length} 条待同步：${error.message}`, true);
    } finally {
      state.syncing = false;
      persistence.saveState();
      ui.renderRecords();
      if (state.ticket) ui.updateTicketSync();
    }
  }

  function correctRecord(recordId, correctedId) {
    const record = findRecord(recordId);
    if (!record) return;
    const other = correctedId === 'other';
    if (!other && (!Number.isInteger(correctedId) || correctedId < 0 || correctedId > 9)) return;
    record.corrected_id = other ? null : correctedId;
    record.corrected_label = other ? 'other' : null;
    record.corrected_at = new Date().toISOString();
    record.revision = Math.max(Number(record.revision) || 0, Number(record.server_revision) || 0) + 1;
    record.correction_synced = false;
    record.correction_conflict = false;
    persistence.saveState();
    ui.renderRecords();
    if (state.ticket && state.ticket.record_id === recordId) {
      state.ticket = record;
      ui.renderTicket();
    }
    syncAll({ silent: true });
  }

  async function resolveConflict(useLocal) {
    const record = state.ticket && findRecord(state.ticket.record_id);
    if (!record || !record.correction_conflict || state.syncing) return;
    const wanted = { corrected_id: record.corrected_id ?? null, corrected_label: record.corrected_label ?? null,
      revision: record.revision, corrected_at: record.corrected_at };
    ui.setConflictBusy(true);
    try {
      // Re-uploading an existing UUID returns its current server state without inserting a duplicate.
      const server = Core.serverRecord(await api('/api/records', { method: 'POST', body: uploadPayload(record) }), record);
      if (record.revision !== wanted.revision || (record.corrected_id ?? null) !== wanted.corrected_id
        || (record.corrected_label ?? null) !== wanted.corrected_label || record.corrected_at !== wanted.corrected_at) {
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
      persistence.saveState();
      ui.renderTicket();
      ui.renderRecords();
      if (useLocal) await syncAll({ silent: true });
    } catch (error) {
      ui.setTicketStatus(error.message, true);
    } finally {
      ui.setConflictBusy(false);
    }
  }

  const syncQueue = Core.createSyncQueue({
    getRecords: () => state.records,
    sync: syncRecord,
    onChange: () => {
      persistence.trimRecords();
      persistence.saveState();
      ui.renderRecords();
      if (state.ticket) ui.updateTicketSync();
    },
  });

  return { recordFromResult, rememberRecord, findRecord, uploadPayload, isPending, syncRecord, syncAll, correctRecord, resolveConflict };
}
