export const CATEGORY_FILE = 'categories.json';
export const STORAGE_KEY = 'campus-ios-v1';
export const MAX_RECORDS = 300;                        // 本机保留上限，超出时先清理已同步的最旧记录
export const MAX_SOURCE_BYTES = 32 * 1024 * 1024;      // 导入原图上限
export const TRANSFER_MAX_SIDE = 2048;                 // 传输副本最长边
export const TRANSFER_QUALITY = 0.92;
export const TRANSFER_MAX_BYTES = 8 * 1024 * 1024;     // 传输副本上限
export const INFER_TIMEOUT_MS = 40000;
export const REQUEST_TIMEOUT_MS = 15000;
export const RETRY_INTERVAL_MS = 45000;                // 存在待传记录时的自动补传间隔
export const PAGE_SIZE = 24;


export function createState() {
return {
  token: '',
  clientId: '',
  modelVersion: '',
  records: [],
  categories: [],
  view: 'capture',
  busy: false,
  ticket: null,
  lastFile: null,
  health: null,
  contract: null,
  cloudModels: [],
  modelsLoading: false,
  modelStatus: '先设置访问口令',
  storageError: '',
  syncing: false,
  settingsPage: '',
  visibleRecords: PAGE_SIZE,
  previewUrl: '',
  previewRecordId: '',
  inferController: null,
  scopePolicy: null,
  scopePolicySha256: '',
  pendingConfirmation: null,
};

}
