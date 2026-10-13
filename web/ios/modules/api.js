import { REQUEST_TIMEOUT_MS } from './state.js';

export async function readStaticJson(paths, fetchImpl = globalThis.fetch) {
  const responses = await Promise.all(paths.map(path => fetchImpl(path, { cache: 'no-cache' })));
  if (responses.some(response => !response.ok)) throw new Error('模型或类别规格加载失败');
  return Promise.all(responses.map(response => response.json()));
}

export class ApiFailure extends Error {
  constructor(code, message, status) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export function createApiClient({getToken, fetchImpl = globalThis.fetch}) {
  function httpMessage(status) {
    if (status === 401) return '口令无效或未设置，请在「我的 → 云端连接」填写访问口令。';
    if (status === 403) return '服务器拒绝了这个请求。';
    if (status === 404) return '接口不存在，请确认服务器版本。';
    if (status === 413) return '图片太大，服务器拒绝接收。';
    if (status === 429) return '请求过于频繁，请稍后再试。';
    if (status === 503) return '服务暂不可用，请稍后重试。';
    return `请求失败（HTTP ${status}）。`;
  }

  async function api(path, options = {}) {
    const { method = 'GET', body, timeout = REQUEST_TIMEOUT_MS, auth = true, signal } = options;
    const controller = new AbortController();
    const cancel = () => controller.abort();
    if (signal) {
      signal.addEventListener('abort', cancel, { once: true });
      if (signal.aborted) controller.abort();
    }
    const timer = setTimeout(() => controller.abort(), timeout);
    const headers = {};
    if (auth && getToken()) headers.Authorization = `Bearer ${getToken()}`;
    const isForm = body instanceof FormData;
    if (body && !isForm) headers['Content-Type'] = 'application/json';
    try {
      const response = await fetchImpl(path, {
        method,
        headers,
        body: isForm ? body : (body ? JSON.stringify(body) : undefined),
        signal: controller.signal,
        cache: 'no-store',
      });
      const text = await response.text();
      let data = null;
      if (text) {
        try {
          data = JSON.parse(text);
        } catch (error) {
          data = null;
        }
      }
      if (!response.ok) {
        const detail = data && data.error;
        throw new ApiFailure(
          detail ? detail.code : `HTTP_${response.status}`,
          detail ? detail.message : httpMessage(response.status),
          response.status,
        );
      }
      if (!data || typeof data !== 'object') throw new ApiFailure('INVALID_RESPONSE', '服务器响应格式无效，请稍后重试。', response.status);
      return data;
    } catch (error) {
      if (error instanceof ApiFailure) throw error;
      if (error && error.name === 'AbortError') {
        if (signal && signal.aborted) throw new ApiFailure('CANCELLED', '本次识别已取消，未保存识别记录。', 0);
        throw new ApiFailure('TIMEOUT', '请求超时，请确认网络后重试。', 0);
      }
      throw new ApiFailure('NETWORK', '无法连接服务器，请确认网络与访问口令。', 0);
    } finally {
      clearTimeout(timer);
      if (signal) signal.removeEventListener('abort', cancel);
    }
  }

  return api;
}
