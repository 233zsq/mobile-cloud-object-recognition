import * as Core from '../core.js';
import { uuidv4 } from './format.js';
import { STORAGE_KEY, MAX_RECORDS } from './state.js';

export function createPersistence(state, { getStorage, onChange = () => {} }) {
  function loadState() {
    let saved = null;
    try {
      saved = JSON.parse(getStorage().getItem(STORAGE_KEY) || 'null');
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
  }

  function saveState() {
    let result;
    try {
      result = Core.writeState(getStorage(), STORAGE_KEY, {
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
    onChange();
    return result.ok;
  }

  function trimRecords() {
    state.records = Core.trimRecords(state.records, MAX_RECORDS);
  }

  return { loadState, saveState, trimRecords };
}
