# Project Memory / Decision Log

A running log of key decisions made during this project and why — useful for
writing your README later and for recalling your reasoning in interviews.

## Decisions Made So Far

**Use case chosen:** Delivery status updates in low-network areas — picked
over field-data-collection and rural-healthcare-logging use cases because it
affects a much larger, everyday user base (gig delivery workforce) across
both cities and rural areas, and is instantly understandable to recruiters
(maps to Swiggy/Zomato/Amazon-style logistics).

**Tech stack:**
- React (frontend) — chosen since it's already a known skill
- IndexedDB (client-side offline storage) — chosen over localStorage because
  it supports structured, larger-scale local data, which this project needs
- FastAPI (backend) — chosen over Django since this project is API-only with
  no need for Django's admin/templating layer
- SQLite (server-side DB) — chosen for zero-setup simplicity in v1; migration
  to MySQL/Postgres noted as a valid future step, not required now
- Vite (frontend build tool) — chosen over Create React App since CRA is
  deprecated and Vite is faster to start, without changing how React itself
  is written

**Conflict resolution strategy:** Last-write-wins based on `updated_at`
timestamp — simple, explainable, and a legitimate v1 approach. Documented
limitation: can silently overwrite near-simultaneous updates; future
iterations could explore field-level merges.

**Constraints:** Zero budget — every tool in this stack is free; no hardware
required beyond a personal laptop.

**Working style:** Built collaboratively step-by-step (not fully
autonomous/agent-generated) specifically so the builder can explain every
design decision in interviews.

## Open Questions / Future Decisions
- Final choice on deployment platform (Render vs Railway vs PythonAnywhere)
- Whether to migrate SQLite → MySQL/Postgres before or after v1 ships
- Whether to add a second use-case frontend later (e.g. reusing the sync
  engine for a different domain) as a future portfolio project

## How to Use This File
Update this log whenever a meaningful decision is made or changed during the
build — not implementation details, just the "what we chose and why." For a
detailed, phase-by-phase log of every bug encountered and how it was fixed,
see `docs/PROJECT_WORKFLOW.md`.
