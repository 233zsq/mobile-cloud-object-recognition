import { createDashboardState } from './state.js';
import { createDashboardApi } from './api.js';
import { createDashboardView } from './view.js';
import { buildFilters } from './filters.js';

export function startDashboard() {
  const state = createDashboardState();
  const view = createDashboardView(state);
  const api = createDashboardApi(() => state.token);
  function schedule() {
    clearTimeout(state.timer);
    if (state.connected && view.el("auto-refresh").checked) state.timer = setTimeout(refresh, 5000);
  }

  async function refresh() {
    if (!state.connected || state.busy) return;
    const generation = state.generation;
    let retryPage = false;
    state.busy = true; view.el("refresh").disabled = true;
    try {
      const recordsParams = new URLSearchParams(state.filters); recordsParams.set("page", state.page); recordsParams.set("page_size", "20");
      const [stats, records, health] = await Promise.all([api("stats", state.filters), api("records", recordsParams), api("health")]);
      if (generation !== state.generation) return;
      if (records.pages > 0 && state.page >= records.pages) { state.page = records.pages - 1; retryPage = true; return; }
      state.pages = records.pages;
      view.render(stats, records, health);
    } catch (error) {
      if (generation === state.generation) view.status(`刷新失败：${error.name === "AbortError" ? "请求超时" : error.message}。保留上次成功数据。`, true);
    } finally {
      state.busy = false; view.el("refresh").disabled = !state.connected;
      if (retryPage) { clearTimeout(state.timer); queueMicrotask(refresh); } else schedule();
    }
  }

  function apply() {
    if (state.busy) return;
    try { state.filters = buildFilters(Object.fromEntries(["start", "end", "model", "source", "recognition-status", "category", "basis"].map(key => [key, view.el(key).value]))); state.page = 0; refresh(); }
    catch (error) { view.status(error.message, true); }
  }

  function bindEvents() {
    view.el("connect-form").addEventListener("submit", async event => {
      event.preventDefault(); if (state.busy) return;
      state.token = view.el("token").value.trim(); view.el("token").value = "";
      state.busy = true; view.status("正在连接…");
      try {
        const catalog = await api("categories"); state.catalogs = catalog.catalogs;
        state.connected = true; view.renderCatalog(catalog);
      } catch (error) { state.token = ""; view.status(`连接失败：${error.name === "AbortError" ? "请求超时" : error.message}`, true); }
      finally { state.busy = false; }
      if (state.connected) apply();
    });
    view.el("disconnect").addEventListener("click", () => {
      state.generation++; state.token = ""; state.connected = false; clearTimeout(state.timer);
      view.renderDisconnected();
    });
    view.el("model").addEventListener("change", view.populateCategories);
    view.el("apply").addEventListener("click", apply);
    view.el("reset").addEventListener("click", () => {
      for (const id of ["start", "end", "model", "source", "recognition-status"]) view.el(id).value = "";
      view.el("basis").value = "predicted"; view.populateCategories(); apply();
    });
    view.el("refresh").addEventListener("click", refresh);
    view.el("auto-refresh").addEventListener("change", schedule);
    view.el("previous").addEventListener("click", () => { if (!state.busy && state.page > 0) { state.page--; refresh(); } });
    view.el("next").addEventListener("click", () => { if (!state.busy && state.page + 1 < state.pages) { state.page++; refresh(); } });
  }
  bindEvents();
}
