# Setting up `.env`: every key, how to get it, and what happens without it

Copy the template once, then edit the copy:

```bash
cp .env.example .env        # in the project root, next to README.md (the backend reads it from there)
```
Restart the backend (`uvicorn app.main:app --reload`) after every change to `.env`. **Never commit `.env`** (it is git-ignored) and never paste keys into chat, issues or screenshots. The web UI never shows a secret; Settings → Integrations only shows whether each one is set.

**Gotcha:** write `KEY=value` with nothing else on the line. For an *empty* key, do not add a `# comment` after the `=`: the .env parser would read the comment text as the value (and the app would think a key is set). Put comments on their own line.

Menus on Google, OpenAI, GitHub, GitLab and Atlassian sites change from time to time. The URLs below are the stable entry points; if a button has moved, the name of the thing to look for stays the same.

## At a glance

| Key | Needed for | Required? | If it is empty |
|---|---|---|---|
| `LLM_PROVIDER` | Which model family the agent uses | Yes (default `mock`) | `mock` = offline demo mode (see below) |
| `GEMINI_API_KEY` | Gemini models (LLM, and Gemini embeddings) | Only if `LLM_PROVIDER=gemini` or `EMBEDDING_PROVIDER=gemini` | Requests that use Gemini fail with **“GEMINI_API_KEY is not set”** |
| `OPENAI_API_KEY` | OpenAI models (LLM, and OpenAI embeddings) | Only if you use OpenAI | Requests fail with **“OPENAI_API_KEY is not set”** |
| `LLM_MODEL`, `LLM_MODEL_FAST` | Choose the exact model | Optional | Gemini: a current Flash model is chosen automatically. OpenAI: `gpt-4o-mini` (set a current model if it is retired) |
| `GITHUB_TOKEN` | Read PRs/issues, open PRs, push (GitHub) | Optional | GitHub features answer “GitHub is not connected…”; everything else works |
| `GITHUB_CLIENT_ID` + `GITHUB_CLIENT_SECRET` | “Sign in with GitHub” (browse and import your private repos) | Optional | The sign-in button is hidden or says “not configured”; you can still import by URL, ZIP or local folder |
| `GITLAB_TOKEN` | Clone private GitLab repos | Optional | Public GitLab repos work; private ones fail to clone |
| `BITBUCKET_USERNAME` + `BITBUCKET_APP_PASSWORD` | Clone private Bitbucket repos | Optional | Public repos work; private ones fail to clone |
| `BRAVE_API_KEY` or `TAVILY_API_KEY` | Lets the agent search the web for error messages | Optional | The `search_web` tool is simply not offered to the model |
| `DATABASE_URL` (+ `DATABASE_SCHEMA`) | Store vectors in PostgreSQL/pgvector | Optional | In-memory index with an on-disk cache; nothing breaks |
| `VECTOR_WEIGHT` | Retrieval tuning | Optional | Automatic: 0.25 with `hash` embeddings, 1.0 with real embedding models |
| `NEXT_PUBLIC_API_URL` (`frontend/.env.local`) | Where the web UI finds the backend | Optional | `http://localhost:8000` |

Everything works with **no keys at all** in offline demo mode (`LLM_PROVIDER=mock`, `EMBEDDING_PROVIDER=hash`): you can import projects, browse code, search, view architecture graphs and dependency impact, run the quality dashboard and run tests. What you do not get: model-written answers, root-cause analysis, patches and AI review findings. The deterministic review checks (secrets, `eval`, bare `except`...) still run. The Settings page shows a yellow “offline mock” badge in this mode.

## Three ready-made setups

**1. Offline demo (no accounts, no cost)**
```ini
LLM_PROVIDER=mock
EMBEDDING_PROVIDER=hash
```

**2. Real answers with Gemini (free tier available)**
```ini
LLM_PROVIDER=gemini
GEMINI_API_KEY=<your key>
LLM_MODEL=<a current Gemini model name>
EMBEDDING_PROVIDER=hash
```

**3. Full setup**: LLM key + `GITHUB_TOKEN` (PRs and issues) + optionally GitHub sign-in, PostgreSQL and real embeddings.

---

## 1. `LLM_PROVIDER`, `LLM_MODEL`, `LLM_MODEL_FAST`

- `LLM_PROVIDER` is `mock`, `gemini` or `openai`. You can also override it per run from the chat composer or Settings (the key for that provider must still be in `.env`).
- `LLM_MODEL` is the model used for analysis, code and review. `LLM_MODEL_FAST` is an optional cheaper model for planning and tool choice; if empty, `LLM_MODEL` is used for everything.
- If `LLM_MODEL` is empty, Gemini picks a current Flash model for your key automatically and remembers the one that worked (stored in `data/llm_model.json`). OpenAI falls back to its built-in default (`gpt-4o-mini`). Providers retire models, so set it explicitly to one that exists today. To list the models your key can use:
  - Gemini: `curl "https://generativelanguage.googleapis.com/v1beta/models?key=$GEMINI_API_KEY"` and use the name without the `models/` prefix.
  - OpenAI: `curl https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY"`.
- A wrong model name does not break startup. The first run that uses it ends with an error from the provider shown in the UI (“agent failed: …”).

## 2. `GEMINI_API_KEY` (Google Gemini)

1. Sign in with a Google account at **https://aistudio.google.com/apikey** (Google AI Studio).
2. Click **Create API key**. Pick an existing Google Cloud project or let it create one.
3. Copy the key (it starts with `AIza`) into `.env`: `GEMINI_API_KEY=AIza...`
4. Set `LLM_PROVIDER=gemini` (and `LLM_MODEL=` as described above). Restart the backend.
5. Check: Settings → Model & agent shows provider `gemini`. Ask a question in AI Chat. A wrong key gives an authentication error in the run.

Notes: a free tier exists with per-minute and per-day request limits. When you hit them the backend retries with backoff and then reports a rate-limit error; wait a minute or lower `MAX_LLM_CALLS`. Free-tier terms may allow Google to use your prompts, so do not send private code on it if that matters to you; check Google’s current terms.
**If missing:** with `LLM_PROVIDER=gemini` every agent run fails immediately with “GEMINI_API_KEY is not set”. With `LLM_PROVIDER=mock` it is never needed.

## 3. `OPENAI_API_KEY` (OpenAI)

1. Sign in at **https://platform.openai.com/api-keys**.
2. **Create new secret key** (name it, e.g. “codebase-agent”). **The key is shown only once**: copy it now (starts with `sk-`).
3. The API is pay-as-you-go: add a payment method or prepaid credit under **Settings → Billing**, otherwise requests fail with a quota error.
4. `.env`: `OPENAI_API_KEY=sk-...` and `LLM_PROVIDER=openai`, plus `LLM_MODEL=`.
5. Using an OpenAI-compatible server (Ollama, vLLM, LM Studio)? Set `OPENAI_BASE_URL=http://localhost:11434/v1` and put any non-empty text in `OPENAI_API_KEY` (the server ignores it).

**If missing:** runs using OpenAI fail with “OPENAI_API_KEY is not set”. If `EMBEDDING_PROVIDER=openai` and the key is missing, importing or re-indexing a project fails with the same message.

## 4. `GITHUB_TOKEN` (personal access token)

Used to list pull requests and issues, analyze/review PRs, fix issues, create branches/PRs and push, always behind an approval screen.

1. Open **https://github.com/settings/personal-access-tokens** (fine-grained tokens, recommended) → **Generate new token**.
2. Name it, set an expiry, and under **Repository access** pick the repositories the agent may touch.
3. Under **Permissions → Repository permissions** set: **Contents: Read and write**, **Pull requests: Read and write**, **Issues: Read and write** (read is enough if you will not let it comment), **Metadata: Read** (added automatically).
4. **Generate token**, copy it (starts with `github_pat_`), and set `GITHUB_TOKEN=github_pat_...`.
   *Classic alternative:* **https://github.com/settings/tokens** → Generate new token (classic) → tick **`repo`** (or only **`public_repo`** for public repositories) → copy the `ghp_...` token.
5. Restart. Check: Settings → Integrations → “GitHub token” shows **set**; GitHub & Pull Requests lists your PRs. The project must have been imported from a GitHub URL (a ZIP or local folder has no GitHub remote to talk to).

**If missing:** GitHub tabs show “GitHub is not connected: sign in with GitHub, or set GITHUB_TOKEN on the server” (or “this project is not a GitHub repository” for ZIP/local imports). Importing public repos by URL still works. Signing in with GitHub (next section) provides the same access without a token.
**If the token is wrong/expired:** “GitHub rejected the saved token: reconnect GitHub”.

## 5. `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` (+ `GITHUB_OAUTH_SCOPE`, `OAUTH_REDIRECT_BASE`, `FRONTEND_URL`)

Enables the **Sign in with GitHub** button and the picker of your private repositories.

1. Go to **https://github.com/settings/developers** → **OAuth Apps** → **New OAuth App**.
2. **Application name**: anything. **Homepage URL**: `http://localhost:3000`. **Authorization callback URL**: exactly `http://localhost:8000/auth/github/callback`. Click **Register application**.
3. On the app page copy the **Client ID**. Click **Generate a new client secret** and copy it immediately (shown once).
4. `.env`:
   ```ini
   GITHUB_CLIENT_ID=<client id>
   GITHUB_CLIENT_SECRET=<client secret>
   GITHUB_OAUTH_SCOPE=repo read:user        # or "public_repo read:user" for public repos only
   OAUTH_REDIRECT_BASE=http://localhost:8000   # where the BACKEND is reachable: must match the callback URL above
   FRONTEND_URL=http://localhost:3000          # where to send you after login
   ```
5. Restart the backend, click the avatar (top right) → **Sign in with GitHub**, approve, and you return to the app signed in.

Deploying somewhere other than localhost? Use your public URLs in all three places (GitHub callback, `OAUTH_REDIRECT_BASE`, `FRONTEND_URL`) and add the frontend’s origin to `CORS_ORIGINS`. This server assumes **one local user**; do not expose it publicly without adding accounts.
**If missing:** the sign-in entry shows “not configured” and `/auth/github/login` answers “GitHub OAuth isn't configured: set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in .env”. Nothing else is affected.

## 6. `GITLAB_TOKEN`

Only to clone **private** GitLab repositories (used as `oauth2:<token>` over HTTPS).

1. **https://gitlab.com/-/user_settings/personal_access_tokens** (User settings → Access tokens) → **Add new token**.
2. Scope: **`read_repository`**. Set an expiry. Create and copy the token (starts with `glpat-`).
3. `GITLAB_TOKEN=glpat-...`

**If missing:** public GitLab repositories import fine; private ones fail with an authentication error from git.

## 7. `BITBUCKET_USERNAME`, `BITBUCKET_APP_PASSWORD`

Only to clone **private** Bitbucket Cloud repositories.

**Important (checked November 2026):** Atlassian retired Bitbucket *app passwords* in 2026 (creation was disabled in September 2025 and they stopped working during June–July 2026), so a new app password cannot be created. Use a Bitbucket **API token** instead:

1. **https://id.atlassian.com/manage-profile/security/api-tokens** → **Create API token with scopes**, choose **Bitbucket** as the app, set an expiry, and grant **repository read** permission.
2. Copy the token.
3. Atlassian’s guidance is that git over HTTPS uses your **Atlassian account email** as the username. Set `BITBUCKET_USERNAME=<your Atlassian account email>` and put the API token in `BITBUCKET_APP_PASSWORD=` (the variable keeps its old name).
   *I have not been able to test this combination against a live Bitbucket account; if the clone fails, try your Bitbucket username in `BITBUCKET_USERNAME` instead and check the git error shown in the UI.*

**If missing:** public repos work; private ones fail to clone.

## 8. `BRAVE_API_KEY` or `TAVILY_API_KEY` (optional web search for the agent)

Lets the agent look up error messages and library behaviour on the web. Queries are scrubbed of paths, emails, IPs and secrets before leaving your machine, and results are treated as untrusted text.

- **Brave:** sign up at **https://brave.com/search/api/**, choose a plan (a free tier exists), create a subscription token, set `BRAVE_API_KEY=`.
- **Tavily:** sign up at **https://app.tavily.com**, copy the API key from the dashboard, set `TAVILY_API_KEY=`.
- Optionally force one with `WEB_SEARCH_PROVIDER=brave` or `tavily`.

**If missing:** the web-search tool is not offered to the model. Everything else is unchanged. Uncomment the line in `.env` to use it.

## 9. `DATABASE_URL` and `DATABASE_SCHEMA` (PostgreSQL + pgvector)

Optional. Without it the index is held in memory (and cached on disk under `data/`), which is fine for single projects.

1. Easiest: Docker. `docker compose up db` starts PostgreSQL 16 with pgvector (user/password/db: `agent` / `agent` / `codeagent`).
2. `DATABASE_URL=postgresql://agent:agent@localhost:5432/codeagent`. For your own server use `postgresql://USER:PASSWORD@HOST:5432/DBNAME` (the server must have the `pgvector` extension; tables are created automatically).
3. `DATABASE_SCHEMA=` is optional (keeps the tables in their own schema); leave empty for the default.

**If missing:** in-memory store. **If set but unreachable:** the Settings → retrieval panel and API report a database error; fix the URL or unset it.

## 10. `VECTOR_WEIGHT` (retrieval tuning, leave empty)

How much vector search counts against keyword (BM25) search. Empty means automatic: 0.25 with the offline `hash` embeddings (they are mostly lexical) and 1.0 with real embedding models. Only change it after measuring with `python -m app.rag.eval`.

## 11. Embeddings (`EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`)

`hash` (default) needs nothing and works offline but is a weak, mostly lexical baseline. For better retrieval use `EMBEDDING_PROVIDER=gemini` (needs `GEMINI_API_KEY`) or `openai` (needs `OPENAI_API_KEY`), or a local model: `bge` (`pip install sentence-transformers`, no key, downloads a model once) or `fastembed`. After changing the embedding provider, re-index each project (project menu → Re-index) so old vectors are not mixed with new ones.

## 12. Frontend: `frontend/.env.local`

```bash
cd frontend && cp .env.example .env.local
```
`NEXT_PUBLIC_API_URL=http://localhost:8000` is where the web UI finds the backend. If the backend is elsewhere, change it and add the UI’s origin to the backend’s `CORS_ORIGINS` (comma-separated). If the backend is unreachable the UI shows a red “Backend unreachable” banner with the exact address it tried. The code editor loads Monaco from a CDN, so the first load needs internet access.

## Speed and limits
`FAST_PLANNING=true` (default) skips two planning model calls for plain Explain questions. `LLM_TIMEOUT` (default 30 s) and `LLM_MAX_RETRIES` (default 2) bound how long a slow or overloaded model can hold a run; an overloaded or out-of-quota Gemini model triggers an immediate try of the next-best model.

## Other settings you may meet in `.env`

`ALLOW_LOCAL_PATHS=true` allows importing a folder from the server’s disk (off by default for safety). `SANDBOX_MODE=docker|local`: `docker` (default) runs repository code in a locked-down container and refuses to run anything if Docker is missing (patches are then reported “unverified”); `local` runs it directly on your machine, for development only. `MAX_LLM_CALLS`, `MAX_RUN_SECONDS`, `TEST_TIMEOUT` bound cost and time. `RATE_LIMIT_PER_MINUTE` is for public deployments.

## Quick troubleshooting

| You see | Meaning | Fix |
|---|---|---|
| “GEMINI_API_KEY is not set” / “OPENAI_API_KEY is not set” | The selected provider has no key | Add the key and restart, or switch provider to `mock` |
| “agent failed: … 401/403/authentication” | Key is wrong, revoked or has no billing | Re-create the key; for OpenAI check billing |
| “agent failed: … 429 / rate limit” | Provider limit (common on free tiers) | Wait, lower usage, or use a paid key |
| “GitHub is not connected…” | No `GITHUB_TOKEN` and not signed in | Section 4 or 5 |
| “this project is not a GitHub repository” | Project came from a ZIP/folder | Import it from its GitHub URL |
| “GitHub OAuth isn't configured…” | Missing client id/secret | Section 5 |
| Red “Backend unreachable” banner | Backend not running or wrong `NEXT_PUBLIC_API_URL` / CORS | Start `uvicorn`; check section 12 |
| Patches always “not verified” | Sandbox unavailable (no Docker) | `scripts/build_sandbox.sh`, or `SANDBOX_MODE=local` for development |
