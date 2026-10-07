// DOM + text helpers shared by every module.
export const $ = (s, r = document) => r.querySelector(s);
const ENT = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
export const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ENT[c]);

export function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = `toast ${kind}`;
  t.textContent = msg;
  $("#toasts").append(t);
  setTimeout(() => t.classList.add("out"), 3200);
  setTimeout(() => t.remove(), 3700);
}

const lineClass = (l) =>
  l[0] === "+" && !l.startsWith("+++") ? "add" : l[0] === "-" && !l.startsWith("---") ? "del" : l.startsWith("@@") ? "hunk" : "";

export const diffHtml = (text) =>
  `<pre class="diff">${text.replace(/\n$/, "").split("\n").map((l) => `<span class="${lineClass(l)}">${esc(l) || " "}</span>`).join("")}</pre>`;

// Tiny markdown: paragraphs, **bold**, `code`, fenced blocks (diff blocks get colour).
export function md(t = "") {
  return t.split(/```(\w*)\n([\s\S]*?)```/).map((p, i, a) => {
    if (i % 3 === 0) {
      return esc(p).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>")
        .split(/\n{2,}/).filter((x) => x.trim()).map((x) => `<p>${x.replace(/\n/g, "<br>")}</p>`).join("");
    }
    if (i % 3 === 1) return "";
    return a[i - 1] === "diff" ? diffHtml(p) : `<pre>${esc(p)}</pre>`;
  }).join("");
}
