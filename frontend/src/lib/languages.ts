const MAP: Record<string, string> = {
  py: "python", js: "javascript", jsx: "javascript", mjs: "javascript", ts: "typescript", tsx: "typescript",
  json: "json", md: "markdown", html: "html", css: "css", yml: "yaml", yaml: "yaml", toml: "ini", ini: "ini", cfg: "ini",
  sql: "sql", sh: "shell", java: "java", go: "go", rs: "rust", c: "c", h: "c", cpp: "cpp", txt: "plaintext",
};

export function languageOf(path: string): string {
  const name = path.split("/").pop() ?? path;
  if (name === "Dockerfile") return "dockerfile";
  const ext = name.includes(".") ? name.split(".").pop()!.toLowerCase() : "";
  return MAP[ext] ?? "plaintext";
}
