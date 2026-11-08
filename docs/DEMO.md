# Demo script (about 3 minutes)

**Before you start:** `uvicorn app.main:app --reload`, open http://localhost:8000. Offline mode is enough for everything below except step 6.

1. **The problem (20 s).** “Cheap mistakes (a typo in a variable, a wrong import path, a missing brace) waste review time and still reach production. AI reviewers guess; ours is exact for what it reports.”
2. **Add a project (20 s).** *Add project → Local folder* → `examples/react-demo` (or `examples/python-demo`). It is indexed in seconds.
3. **Review code (40 s).** Click **Review code** on the dashboard. About 10 high-severity findings appear in well under a second. Open one: the code line with a caret under the mistake, *did you mean `Header`?*, and how to fix it. Point out the **What was analysed** panel: it says what was checked per language and what static analysis cannot see.
4. **Paste code (20 s).** *Code Review → Paste code → Load example → Review this code.* Edit a name and review again.
5. **Understand the project (40 s).** *Architecture → System map* (components and labelled arrows), *Execution flow* (pick a function from the dropdown: sequence diagram of what it calls), *3D map* (optional wow moment).
6. **AI on top (30 s, needs a key).** Set `LLM_PROVIDER=gemini` + key. In *AI Chat → Debug*, paste an error: root cause with citations, a patch, before/after tests, and a clearly marked **verified** or **suggested** fix. Nothing is applied until you approve.
7. **CI use (10 s).** `python -m app.review . --fail-on high` exits 1 on a high-severity finding; `--sarif` feeds GitHub code scanning.
8. **Close with the numbers (10 s).** 53 of 53 seeded mistakes found, 0 high/medium false alarms on the project's own 247 files of working code (`eval/results/review_benchmark.md`).

**Be ready to answer:** *“Why not just ask an LLM?”* Because the reviewer must be right about what it reports; the LLM is used where certainty is impossible, and its claims are checked. *“What does it miss?”* Types and logic errors, stated on the page and in the README.
