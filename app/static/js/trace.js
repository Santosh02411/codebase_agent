// Right-hand panel: what the agent did, and which code it read.
import { $, esc } from "./util.js";

export function pending(msg) {
  $("#trace").innerHTML = `<li class="idle"><div class="reading">${esc(msg)}<i></i><i></i><i></i></div></li>`;
  $("#srcs").innerHTML = `<p class="note">Nothing yet.</p>`;
}

// Steps appear one after another (staggered via --i) — it replays the real step log of the run.
export function show(steps = []) {
  $("#trace").innerHTML = steps.map((s, i) =>
    `<li style="--i:${i}"><b>${esc(s.node.replace(/_/g, " "))}</b><p>${esc(s.message)}</p></li>`).join("")
    || `<li class="idle">No steps recorded.</li>`;
}

export function sources(list = [], onOpen) {
  const el = $("#srcs");
  el.innerHTML = list.map((s, i) =>
    `<button class="src" style="--i:${i}" data-file="${esc(s.file)}" data-lines="${esc(s.lines)}"><span class="mark">${esc(s.file)}:${esc(s.lines)}</span><small>${esc(s.symbol)}</small></button>`).join("")
    || `<p class="note">Nothing yet.</p>`;
  el.onclick = (e) => { const b = e.target.closest(".src"); if (b) onOpen(b.dataset.file, b.dataset.lines); };
}
