// Entry point: holds UI state and wires the modules together.
import { get, post, upload } from "./api.js";
import { $, esc, toast } from "./util.js";
import { renderTree } from "./tree.js";
import * as trace from "./trace.js";
import * as view from "./results.js";
import { openFile } from "./viewer.js";

const S = { mode: "chat", repo: "", files: [], repos: [], busy: false };
const HINT = {
  search: "Find code, for example: where is the user's password checked?",
  architecture: "Optional: press Send to get an overview of how the project is structured.",
  review: "Optional: a file to review, like services/eta.py. Leave empty to review the project.",
  change: "Describe the change, for example: add a /health endpoint and a test for it.",
  tests: "Which file should get tests? For example: services/eta.py",
  chat: "Ask about the project, for example: how does authentication work?",
  debug: "Describe the bug, or paste an error message or stack trace.",
};
const IDEAS = ["Where is authentication implemented?", "Why does creating a record return a 500 error?", "Which functions call the database?"];
const open = (file, lines) => S.repo && openFile(S.repo, file, lines);

/* ---- projects ---- */
async function loadRepos(select) {
  S.repos = await get("/repositories");
  $("#repo").innerHTML = S.repos.map((r) => `<option value="${esc(r.id)}">${esc(r.name)}</option>`).join("") || `<option value="">No projects yet</option>`;
  if (select) $("#repo").value = select;
  if (!S.repos.length) $("#add").open = true;
  await pick();
}
const drawTree = () => renderTree($("#tree"), S.files, $("#filter").value, open);
async function pick() {
  S.repo = $("#repo").value; S.files = [];
  const m = S.repos.find((r) => r.id === S.repo);
  $("#meta").textContent = m ? `${m.files} files · ${m.chunks} code pieces` : "";
  drawTree();
  if (!S.repo) return;
  S.files = (await get(`/repositories/${S.repo}/tree`)).files;
  drawTree();
}
async function add(promise, msg) {
  const note = $("#addmsg");
  note.className = "note"; note.textContent = msg;
  try {
    const m = await promise;
    note.textContent = "";
    toast(`Added ${m.name}: ${m.files} files indexed`);
    await loadRepos(m.id);
  } catch (e) { note.className = "note err"; note.textContent = e.message; }
}
function setZip(f) { $("#dropText").textContent = f ? f.name : "Drop a .zip here or click to choose"; }
$("#zip").onchange = () => setZip($("#zip").files[0]);
const drop = $("#drop");
["dragover", "dragenter"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, () => drop.classList.remove("over")));
drop.addEventListener("drop", (e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) { $("#zip").files = e.dataTransfer.files; setZip(f); } });
$("#upload").onclick = () => {
  const f = $("#zip").files[0];
  if (!f) return toast("Choose a .zip file first.", "err");
  add(upload(f, $("#zname").value.trim() || f.name.replace(/\.zip$/i, "")), "Uploading and indexing…");
};
$("#clone").onclick = () => { const u = $("#url").value.trim(); if (u) add(post("/repositories", { source: u }), "Cloning and indexing…"); };
$("#repo").onchange = pick;
$("#filter").oninput = drawTree;
$("#reindex").onclick = async () => {
  if (!S.repo) return;
  $("#meta").textContent = "Re-indexing…";
  try { await post(`/repositories/${S.repo}/index`, {}); await loadRepos(S.repo); toast("Re-indexed"); }
  catch (e) { toast(e.message, "err"); }
};
$("#tests").onclick = async () => {
  if (!S.repo) return toast("Add and pick a project first.", "err");
  view.clear(); trace.pending("Running tests…");
  try { view.tests(await post("/run-tests", { repo_id: S.repo })); }
  catch (e) { view.error(e.message); }
  trace.show([{ node: "run tests", message: "Ran the project's tests in an isolated copy." }]);
};

/* ---- mode switch (sliding thumb) ---- */
const OPTIONAL = ["architecture", "review"];
function setMode(m) {
  S.mode = m;
  const seg = $("#seg");
  seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.m === m));
  const on = seg.querySelector(`[aria-pressed=true]`), thumb = seg.querySelector(".thumb");
  thumb.style.setProperty("--w", `${on.offsetWidth}px`);
  thumb.style.setProperty("--h", `${on.offsetHeight}px`);
  thumb.style.transform = `translate(${on.offsetLeft}px, ${on.offsetTop}px)`;
  $("#q").placeholder = HINT[m];
}
$("#seg").onclick = (e) => { const b = e.target.closest("button"); if (b) setMode(b.dataset.m); };
addEventListener("resize", () => setMode(S.mode));

/* ---- ask ---- */
function busy(on) { S.busy = on; $("#go").disabled = on; }
async function send(e) {
  e?.preventDefault();
  if (S.busy) return;
  const q = $("#q").value.trim();
  if (!S.repo) return toast("Add and pick a project first.", "err");
  if (!q && !OPTIONAL.includes(S.mode)) return toast("Type a question or paste an error.", "err");
  busy(true); view.clear();
  trace.pending(["debug", "change", "tests"].includes(S.mode) ? "Working and running tests. This can take a minute." : "Reading your code…");
  try {
    if (S.mode === "search") {
      const hits = await post("/search", { repo_id: S.repo, query: q, k: 6 });
      trace.show([{ node: "search", message: `${hits.length} matches` }]);
      trace.sources(hits.map((h) => ({ file: h.file, lines: `${h.start}-${h.end}`, symbol: h.qualname })), open);
      view.search(hits, open);
    } else if (S.mode === "architecture") {
      const r = await post("/architecture", { repo_id: S.repo });
      trace.show(r.steps); trace.sources([], open); view.architecture(r);
    } else if (S.mode === "review") {
      const r = await post("/review", { repo_id: S.repo, path: q || null });
      trace.show(r.steps); trace.sources([], open); view.review(r, open);
    } else if (S.mode === "change" || S.mode === "tests") {
      const r = S.mode === "tests" ? await post("/generate-tests", { repo_id: S.repo, target: q }) : await post("/change", { repo_id: S.repo, request: q });
      const meta = S.repos.find((x) => x.id === S.repo);
      trace.show(r.steps); trace.sources(r.sources, open);
      view.changes(r, {
        canPr: /^https:\/\/github\.com\//.test(meta?.source || ""),
        apply: () => post("/apply-changes", { repo_id: S.repo, edits: r.edits, new_files: r.new_files }),
        pr: () => post("/create-pr", { repo_id: S.repo, files: r.final_files, title: (r.explanation || "AI-generated change").split("\n")[0].slice(0, 70), body: r.explanation, confirm: true }),
      });
    } else {
      const r = await post(S.mode === "debug" ? "/debug" : "/chat", { repo_id: S.repo, question: q });
      trace.show(r.steps); trace.sources(r.sources, open);
      view.answer(r, (p) => post("/apply-patch", { repo_id: S.repo, file: p.file, search: p.search, replace: p.replace }));
    }
  } catch (err) { view.error(err.message); trace.show([]); }
  finally { busy(false); }
}
$("#form").onsubmit = send;
$("#q").onkeydown = (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send(e); };

/* ---- boot ---- */
get("/health").then((h) => {
  const mock = h.llm_provider === "mock", chip = $("#model");
  chip.textContent = mock ? "Offline model: answers list relevant files only" : `Model: ${h.llm_provider}`;
  chip.classList.toggle("warn", mock);
}).catch(() => {});
view.empty(IDEAS, (t) => { $("#q").value = t; $("#q").focus(); });
document.fonts?.ready.then(() => setMode(S.mode));
setMode("chat");
loadRepos().catch((e) => toast(e.message, "err"));
