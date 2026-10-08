# Codebase Agent IDE (frontend)

Next.js 14 (App Router) · React 18 · TypeScript · Tailwind CSS · shadcn/ui primitives · Monaco Editor · Zustand · TanStack Query.

## Run
```bash
# terminal 1 — backend (inside your venv)
uvicorn app.main:app --reload

# terminal 2 — frontend
cd frontend
cp .env.example .env.local      # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev                     # http://localhost:3000
```
The backend allows `http://localhost:3000` by default; set `CORS_ORIGINS` (comma-separated) to serve the UI from elsewhere.
Monaco loads from a CDN, so the first load needs internet access.

## What's in the window
| Area | What it does |
|---|---|
| Explorer + Outline | File tree with git markers; the open file's functions/classes, click to jump |
| Search | Exact text/regex across the repo, or semantic search over the AI index |
| Git changes | Working copy vs. imported version, diff viewer, discard, commit (in the server's copy) |
| Editor | Monaco, tabs, breadcrumbs with current function, Ctrl+S saves to the project copy |
| Selection toolbar | Select code → Ask AI / Explain / Tests / Change (or Ctrl+L) |
| AI chat | Ask, Debug, Change, Tests, Review, Architecture; answers cite their sources |
| Review tab | Per-change Approve / Reject, live diff preview, Apply, Run tests, Open pull request |
| Agent activity | Live timeline: every model call, tool call, file read and test run, with timings |
| Terminal | Restricted: ls, cat, grep, tree, git status/diff/log, pytest (no shell) |
| Tests / Sources / Problems | Test history, clickable citations with code peek, review findings |

Shortcuts: `Ctrl+P` files · `Ctrl+Shift+O` functions in file · `Ctrl+T` functions in repo · `Ctrl+Shift+P` commands · `Ctrl+Shift+F` search · `Ctrl+J` bottom panel · `F12` / `Ctrl+click` go to definition.

## Notes
- Nothing touches your real project: edits, applied AI changes and commits happen in the server's copy (`data/repos/...`).
- "Stop" ends the live view; the server may finish the request in the background, but nothing is applied.
- Type-check: `npm run typecheck`. Production build: `npm run build && npm start`.
