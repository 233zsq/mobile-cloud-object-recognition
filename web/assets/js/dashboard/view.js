export function createDashboardView(state) {
  const el = id => document.getElementById(id);
  const number = value => Number(value).toLocaleString("zh-CN", {maximumFractionDigits: 2});
  const text = (id, value) => { el(id).textContent = value; };
  const status = (message, error = false) => { text("status", message); el("status").classList.toggle("error", error); };
  const node = (tag, value, className) => { const n = document.createElement(tag); if (value !== undefined) n.textContent = value; if (className) n.className = className; return n; };
  const label = (version, id) => (state.catalogs[version] || []).find(c => c.id === id)?.display_name || `类别 ${id}`;
  const date = value => new Date(value).toLocaleString("zh-CN", {hour12: false});

  function populateCategories() {
    const version = el("model").selectedOptions[0]?.dataset.version;
    el("category").replaceChildren(new Option("全部类别", ""));
    for (const [v, categories] of Object.entries(state.catalogs)) {
      if (version && v !== version) continue;
      const group = node("optgroup"); group.label = v;
      for (const category of categories) group.append(new Option(category.display_name, `${v}:${category.id}`));
      el("category").append(group);
    }
  }

  function bars(id, rows) {
    const target = el(id); target.replaceChildren(); target.classList.remove("empty");
    if (!rows.length) { target.classList.add("empty"); target.textContent = "所选范围暂无记录"; return; }
    const max = Math.max(1, ...rows.map(r => r.count));
    for (const row of rows) {
      const line = node("div", undefined, "bar-row"), title = node("div", row.name, "bar-label");
      if (row.detail) title.append(node("small", row.detail));
      const track = node("div", undefined, "bar-track"), meter = node("meter");
      meter.min = 0; meter.max = max; meter.value = row.count; meter.setAttribute("aria-label", `${row.name}：${row.count}条`);
      track.append(meter); line.append(title, track, node("span", number(row.count), "bar-value")); target.append(line);
    }
  }

  function render(stats, records, health) {
    text("total", number(stats.total_count)); text("corrected", number(stats.corrected_count)); text("low", number(stats.low_confidence_count));
    text("uncertain", stats.uncertain_count === undefined ? '尚未支持' : number(stats.uncertain_count));
    text("sources", `手机 ${number(stats.device_count)} / 云端 ${number(stats.cloud_count)}`);
    text("latency", stats.latency_ms.average === null ? "—" : `${number(stats.latency_ms.average)} ms`);
    text("latency-range", stats.latency_ms.min === null ? "预处理＋推理，不含网络" : `最小 ${number(stats.latency_ms.min)} / 最大 ${number(stats.latency_ms.max)} ms`);
    const effective = state.filters.get("category_basis") === "effective";
    text("basis-label", effective ? "修正后（未修正沿用原预测）" : "原始预测");
    bars("category-chart", stats.categories.filter(c => c[effective ? "effective_count" : "predicted_count"] > 0).map(c => ({name: c.display_name, detail: c.category_version, count: c[effective ? "effective_count" : "predicted_count"]})));
    bars("daily-chart", stats.daily_counts.map(d => ({name: d.date, count: d.count})));
    const tbody = el("record-rows"); tbody.replaceChildren();
    for (const record of records.records) {
      const tr = node("tr");
      tr.append(node("td", date(record.captured_at)), node("td", label(record.category_version, record.predicted_id)));
      const correction = node("td", record.corrected_id === null ? "未修正" : label(record.category_version, record.corrected_id));
      if (record.corrected_id !== null) correction.append(node("small", `修订 ${record.revision}`));
      tr.append(correction, node("td", `${number(record.confidence * 100)}%`), node("td", `${number(record.latency_ms)} ms`));
      const source = node("td", record.inference_source === "device" ? "手机离线" : "云端识别");
      const scope = record.scope_decision;
      const states = {accepted: '规则通过', uncertain: '不确定', unavailable: '规则未就绪'};
      source.append(node('small', scope ? `${states[scope.status] || '未标记'}${scope.manual_confirmed ? ' · 已人工确认' : ''}` : '旧记录未标记'));
      source.append(node("small", record.model_version)); tr.append(source);
      const uuid = node("td", record.record_id, "record-id"); uuid.title = record.record_id; tr.append(uuid); tbody.append(tr);
    }
    if (!records.records.length) { const td = node("td", "所选范围暂无记录", "empty"); td.colSpan = 7; const tr = node("tr"); tr.append(td); tbody.append(tr); }
    text("page-info", `共 ${number(records.total)} 条 · 第 ${records.page + 1} / ${Math.max(1, records.pages)} 页`);
    el("previous").disabled = state.page <= 0; el("next").disabled = state.page + 1 >= state.pages;
    text("health", health.model_loaded ? `服务正常 · ${health.model_version}` : "服务正常 · 推理模型暂不可用");
    status(`最近刷新 ${date(stats.generated_at)}`);
  }

  function renderCatalog(catalog) {
    el("model").replaceChildren(new Option("全部模型", ""));
    for (const model of catalog.models) {
      const option = new Option(model.model_version, model.model_version);
      option.dataset.version = model.category_version;
      el("model").append(option);
    }
    populateCategories();
    el("connection").hidden = true;
    el("disconnect").hidden = false;
    for (const id of ["refresh", "apply", "reset"]) el(id).disabled = false;
  }

  function renderDisconnected() {
    el("connection").hidden = false; el("disconnect").hidden = true;
    for (const id of ["refresh", "apply", "reset", "previous", "next"]) el(id).disabled = true;
    for (const id of ["total", "corrected", "low", "uncertain", "latency", "page-info"]) text(id, "—");
    text("sources", "手机 — / 云端 —"); text("latency-range", "预处理＋推理，不含网络");
    bars("category-chart", []); bars("daily-chart", []); el("record-rows").replaceChildren();
    text("health", "已断开"); status("已断开连接，口令已清除");
  }
  return { el, status, render, populateCategories, renderCatalog, renderDisconnected };
}
