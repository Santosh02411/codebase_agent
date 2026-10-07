import { get } from "./api.js";
import { $, esc } from "./util.js";

// Code viewer dialog: shows a file with line numbers and highlights the lines the agent read.
export async function openFile(repo, path, lines) {
  const d = $("#viewer");
  $("#vtitle").textContent = path;
  $("#vcode").innerHTML = `<p class="note" style="padding:0 16px">Loading…</p>`;
  if (!d.open) d.showModal();
  try {
    const f = await get(`/repositories/${repo}/file?path=${encodeURIComponent(path)}`);
    const [a, b] = String(lines || "0-0").split("-").map(Number);
    $("#vcode").innerHTML = f.text.split("\n").map((l, i) =>
      `<div class="ln${i + 1 >= a && i + 1 <= (b || a) ? " hl" : ""}" id="L${i + 1}"><span>${i + 1}</span><code>${esc(l) || " "}</code></div>`).join("");
    $(`#L${a}`)?.scrollIntoView({ block: "center" });
  } catch (e) {
    $("#vcode").innerHTML = `<p class="note err" style="padding:0 16px">${esc(e.message)}</p>`;
  }
}
// Click on the dark backdrop closes the dialog.
$("#viewer").addEventListener("click", (e) => { if (e.target.id === "viewer") e.target.close(); });
