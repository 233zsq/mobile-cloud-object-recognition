export function buildFilters(values) {
  const query = new URLSearchParams();
  for (const key of ["start", "end"]) if (values[key]) query.set(key, new Date(values[key]).toISOString());
  if (query.has("start") && query.has("end") && query.get("start") >= query.get("end")) throw new Error("开始时间必须早于结束时间");
  if (values["model"]) query.set("model_version", values["model"]);
  if (values["source"]) query.set("inference_source", values["source"]);
  if (values["recognition-status"]) query.set("recognition_status", values["recognition-status"]);
  if (values["category"]) { const [version, id] = values["category"].split(":"); query.set("category_version", version); query.set("category_id", id); }
  query.set("category_basis", values["basis"]);
  return query;
}
