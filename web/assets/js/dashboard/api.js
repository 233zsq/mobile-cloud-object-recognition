export function createDashboardApi(getToken, fetchImpl = globalThis.fetch) {
  async function api(path, params) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetchImpl(`/api/${path}${params?.size ? `?${params}` : ""}`, {
        headers: getToken() ? {Authorization: `Bearer ${getToken()}`} : {}, signal: controller.signal, cache: "no-store", credentials: "omit"
      });
      if (!response.ok) {
        if (response.status === 401) throw new Error("访问口令无效或已过期，请断开后重新连接");
        const body = await response.json().catch(() => null);
        throw new Error(body?.error?.message || `请求失败（HTTP ${response.status}）`);
      }
      return await response.json();
    } finally { clearTimeout(timeout); }
  }
  return api;
}
