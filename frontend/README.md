# CodeScout AI: web app (v14 redesign)

Next.js 14 (App Router) · React 18 · TypeScript · Tailwind · Radix primitives · Monaco · React Flow · Recharts · Framer Motion · Zustand · TanStack Query.
It talks to the FastAPI backend through the same API client and hooks as before; no backend contract changed.

## Run
The backend serves the pre-built app at **http://localhost:8000** (`app/webapp`). Rebuild it after changing the frontend with `scripts/build_frontend.sh` (Node 18+). For development with hot reload use the commands below (port 3000).
```bash
uvicorn app.main:app --reload              # terminal 1 (project root)
cd frontend && cp .env.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install && npm run dev                  # http://localhost:3000
npm run typecheck && npm run build          # checks
```
The backend allows `http://localhost:3000` by default (`CORS_ORIGINS` to change). Monaco loads from a CDN, so the first load needs internet access. Keys and tokens: [../docs/ENV_SETUP.md](../docs/ENV_SETUP.md).

## Pages
| Route | What it is |
|---|---|
| `/` Dashboard | Repository stats, languages, architecture summary, quality score, test status, important issues, recent agent runs and commits/patches, quick actions |
| `/chat` AI Chat | Explain / Debug / Review / Change / Test modes, `@file` and `@symbol` references, paste screenshots, clickable `[n]` citations and `file:line` references, expandable evidence, patch and test cards, and the **agent timeline** (Understand → Plan → Research → Analyze → Implement → Test → Review → Complete) |
| `/explorer` Code Explorer | File tree with git markers, Monaco editor (theme-aware), outline, callers/callees, imports/impact/tests, text and semantic search, changes diff, Ask AI. Deep-linkable: `/explorer?file=app/x.py&line=12` |
| `/architecture` | React Flow graphs: module imports (whole repo or focused), function call graph, file impact with tests; zoom, pan, search, folder/kind filters, folder expand/collapse, dependency highlighting, click to select, double-click to open code, routes and models lists |
| `/debug` | Paste an error; decoded error report, root cause with citations, affected files, patch preview with diff, before/after tests, regression verification, apply/reject. Verified fixes and suggested fixes look different |
| `/review` | Run a project or file review; severity charts, filters, expandable findings with evidence, confidence, remediation |
| `/quality` | Run scans, score ring and dimensions, trend, analyzers, findings, coverage, maintainability, tests |
| `/changes` | All patches with exact per-file diffs, per-file approval, apply (then checks run), revert, re-check, agent repair |
| `/testing` | Run tests, outcome chart, failed tests, full log, coverage, run history, sandbox status, regression verification table |
| `/github` | Pull requests (analyze, draft a review), issues (fix), approvals, repository and push proposals |
| `/settings` | Theme, provider override, verify default, sandbox, integrations status (never the secrets) |
| `/workbench` | The previous multi-tab IDE layout, kept for its terminal, git panel and retrieval experiments |

## Structure
```
src/app/(app)/*          one folder per page; layout.tsx wraps them in the AppShell, template.tsx adds the page transition
src/components/ui/       design system: button, badge, card, dialog + drawer, dropdown, select, tabs, tooltip, skeleton, states, table, progress, switch, segmented, confirm
src/components/shell/    sidebar (collapsible), topbar, project switcher, command palette (Ctrl+K), notifications, profile, index status, onboarding
src/components/{dashboard,chat,explorer,arch,debug,review,quality,patches,testing,github,settings}/   page features
src/components/common/   shared bits: markdown renderer, file links, score ring, chart tooltip
src/lib, src/hooks, src/store   API client, types, query hooks, agent-run hook, zustand stores (unchanged contracts)
```

## Theming
Semantic CSS variables in `globals.css` (`--background`, `--panel`, `--surface`, `--primary`, `--success`, chart and syntax-token colours...) with a complete light palette and a complete dark palette. Light / dark / system preference is persisted and applied before first paint (no flash). Charts, Monaco editors and diffs, React Flow, toasts, dialogs and code blocks follow the theme.

## Behaviour you should know about
- **Nothing is simulated.** Every number, status and timeline comes from the API or from the real event stream of the run. A phase that never ran is shown as “not needed”, not as done.
- **Answers are not token-streamed.** The backend streams *events* (phases, tool calls, model calls); the final answer arrives as one result, so the UI shows live activity while it works and renders the answer when it is complete.
- **Chat history and agent runs live in the browser session** (they are cleared on reload or New chat). Patches, quality reports and projects live on the backend.
- Human approval is unchanged: patches are applied only from the Changes / Debug screens after an explicit confirm; pushes, PRs and posted reviews go through the Approvals tab.
- Accessibility: keyboard-operable navigation, command palette, dialogs and menus (Radix), visible focus rings, ARIA labels on charts and icon buttons, reduced-motion support. Not yet audited with a screen reader.
