// Centre column: renders answers, proposed fixes, search hits and test runs as cards.
import { $, esc, md, diffHtml, toast } from "./util.js";

const out = () => $("#out");
const pill = (t) => `<span class="pill ${t ? t.status : "none"}">${t ? t.status.replace("_", " ") : "not run"}</span>`;
function card(cls, html) {
  const d = document.createElement("article");
  d.className = `card ${cls}`;
  d.innerHTML = html;
  out().append(d);
  return d;
}

export const clear = () => out().replaceChildren();
export const error = (m) => card("err", `<h3>Something went wrong</h3><p>${esc(m)}</p>`);
export const tests = (t) =>
  card("", `<h3>Test run ${pill(t)}</h3><p class="note">${esc(t.summary)}</p><pre>${esc(t.output)}</pre>`);

export function empty(ideas, onPick) {
  out().innerHTML = `<div class="empty"><h2>What do you want to know about your code?</h2><div class="ideas">${
    ideas.map((i) => `<button type="button">${esc(i)}</button>`).join("")}</div></div>`;
  out().onclick = (e) => { const b = e.target.closest(".ideas button"); if (b) onPick(b.textContent); };
}

export function search(hits, open) {
  const c = card("", `<h3>${hits.length} matching ${hits.length === 1 ? "place" : "places"}</h3>${
    hits.map((h) => `<div class="hit"><button class="link" data-f="${esc(h.file)}" data-l="${h.start}-${h.end}">${esc(h.file)}:${h.start}-${h.end}</button>
      <span class="note">${esc(h.qualname)}${h.route ? ` · ${esc(h.route)}` : ""}</span><pre>${esc(h.text.slice(0, 900))}</pre></div>`).join("") || `<p class="note">No matches. Try different words or a function name.</p>`}`);
  c.onclick = (e) => { const b = e.target.closest(".link"); if (b) open(b.dataset.f, b.dataset.l); };
}

export function answer(r, apply) {
  card("answer", `<h3>Answer <small>${esc(r.llm)} model</small></h3>${md(r.answer)}`);
  if (!r.patch) return;
  const showDiff = r.diff && !r.answer.includes("```diff");
  const c = card("fix", `<h3>Proposed fix <small>${esc(r.patch.file)}</small></h3>
    <p class="verdict">Tests before ${pill(r.test_before)} <i>→</i> after ${pill(r.test_after)}</p>
    ${r.patch.explanation ? `<p>${esc(r.patch.explanation)}</p>` : ""}${showDiff ? diffHtml(r.diff) : ""}
    <div class="row"><button class="btn" data-apply>Apply fix to project copy</button></div><p class="note" data-msg></p>`);
  const btn = $("[data-apply]", c), msg = $("[data-msg]", c);
  btn.onclick = async () => {
    btn.disabled = true;
    try {
      await apply(r.patch);
      msg.textContent = "Applied to the server's copy of the project. Your original files are untouched. Run tests to confirm.";
      toast("Fix applied");
    } catch (e) { btn.disabled = false; msg.className = "note err"; msg.textContent = e.message; }
  };
}

export const architecture = (r) => card("answer", `<h3>Architecture</h3>${md(r.answer)}`);

export function review(r, open) {
  const c = card("", `<h3>Code review</h3><p>${esc(r.summary)}</p>${r.findings.map((f) => `<div class="hit">
    <span class="sev ${f.severity}">${f.severity}</span><button class="link" data-f="${esc(f.file)}" data-l="${f.line || 1}">${esc(f.file)}${f.line ? `:${f.line}` : ""}</button>
    ${f.source === "ai" ? '<small class="note">AI</small>' : ""}<p>${esc(f.message)}</p></div>`).join("") || '<p class="note">No issues found.</p>'}`);
  c.onclick = (e) => { const b = e.target.closest(".link"); if (b && b.dataset.f) open(b.dataset.f, b.dataset.l); };
}

// Proposed multi-file change or generated tests. `act.apply()` writes to the project copy; `act.pr()` opens a GitHub PR.
export function changes(r, act) {
  if (r.status === "no_change") {
    return card("", `<h3>No change proposed</h3><p>${esc(r.explanation || "The agent could not produce a valid change.")}</p>${
      r.steps.filter((s) => s.node === "generate").map((s) => `<p class="note">${esc(s.message)}</p>`).join("")}`);
  }
  const verified = r.test_after ? `<p class="verdict">Tests before ${pill(r.test_before)} <i>→</i> after ${pill(r.test_after)}</p>`
    : `<p class="note">Tests were not run.</p>`;
  const c = card("fix", `<h3>Proposed change <small>${r.files.length} file${r.files.length === 1 ? "" : "s"}</small></h3>${verified}
    <ul class="files">${r.files.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>${r.explanation ? `<p>${esc(r.explanation)}</p>` : ""}${diffHtml(r.diff)}
    <div class="row"><button class="btn" data-apply>Apply to project copy</button>${act.canPr ? '<button class="btn ghost" data-pr>Open pull request</button>' : ""}</div><p class="note" data-msg></p>`);
  const msg = $("[data-msg]", c);
  const run = (btn, fn) => async () => {
    btn.disabled = true; msg.className = "note"; msg.textContent = "Working…";
    try { msg.innerHTML = await fn(); } catch (e) { btn.disabled = false; msg.className = "note err"; msg.textContent = e.message; }
  };
  const a = $("[data-apply]", c), p = $("[data-pr]", c);
  a.onclick = run(a, async () => { await act.apply(); toast("Change applied"); return "Applied to the server's copy of the project. Your original files are untouched. Run tests to confirm."; });
  if (p) p.onclick = run(p, async () => {
    if (!confirm("This creates a branch and a pull request on GitHub. Continue?")) { p.disabled = false; return ""; }
    const pr = await act.pr();
    return `Pull request opened: <a href="${esc(pr.url)}" target="_blank" rel="noopener">#${pr.number}</a>`;
  });
}
