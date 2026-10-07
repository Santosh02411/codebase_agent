// Thin fetch wrapper: JSON in/out, readable errors from FastAPI's {detail}.
export async function api(path, opt) {
  const r = await fetch(path, opt);
  let d = {};
  try { d = await r.json(); } catch { /* empty body */ }
  if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail || r.statusText));
  return d;
}
export const get = (p) => api(p);
export const post = (p, body) =>
  api(p, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
export function upload(file, name) {
  const f = new FormData();
  f.append("file", file);
  f.append("name", name);
  return api("/repositories/upload", { method: "POST", body: f });
}
