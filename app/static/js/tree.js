import { esc } from "./util.js";

// Builds a collapsible folder tree from flat paths. Native <details> keeps it keyboard accessible.
export function renderTree(el, files, filter, onOpen) {
  const f = filter.trim().toLowerCase();
  const list = (f ? files.filter((x) => x.toLowerCase().includes(f)) : files).slice(0, 1500);
  const root = {};
  for (const p of list) {
    let n = root;
    const parts = p.split("/");
    parts.forEach((s, i) => { n = n[s] ??= i === parts.length - 1 ? null : {}; });
  }
  const draw = (n, path) => Object.entries(n)
    .sort(([a, x], [b, y]) => (!x - !y) || a.localeCompare(b))   // folders first
    .map(([k, v]) => v
      ? `<details ${f || !path ? "open" : ""}><summary>${esc(k)}</summary>${draw(v, `${path}${k}/`)}</details>`
      : `<button class="file" data-p="${esc(path + k)}">${esc(k)}</button>`).join("");
  el.innerHTML = draw(root, "") || `<p class="note">${files.length ? "No files match." : "No project selected."}</p>`;
  el.onclick = (e) => { const b = e.target.closest(".file"); if (b) onOpen(b.dataset.p); };
}
