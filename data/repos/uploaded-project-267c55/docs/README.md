# Offline-First Delivery Status Sync

A delivery status tracking system built to work fully offline and sync automatically
once connectivity returns — designed for delivery agents working in low-network
areas (basements, elevators, rural zones, dense buildings).

## Problem It Solves
Delivery agents lose connectivity constantly during their routes. Existing apps
either fail silently or block the agent from updating status until signal returns,
causing delays and lost/duplicate updates. This project solves that with local-first
storage and a conflict-aware sync engine.

## Tech Stack
- **Frontend:** React + Vite + IndexedDB (offline-capable client storage)
- **Backend:** FastAPI
- **Database:** SQLite (source of truth on server)
- **Sync Logic:** Custom-built conflict resolution (last-write-wins by timestamp)
- **Version Control:** Git + GitHub
- **Deployment:** TBD (Render/Railway — free tier)

## Project Status
✅ Phase 1 — Backend schema + API skeleton (done)
✅ Phase 2 — Offline-capable React frontend (done)
✅ Phase 3 — Sync engine with conflict resolution (done)
✅ Phase 4 — Dispatcher dashboard filtering + Agent view ordering/delete (done)
🚧 Phase 5 — Final polish, README, demo, deployment

## Project Structure
```
delivery-sync-project/
├── backend/           # FastAPI app
├── frontend/          # React app (Vite)
├── docs/              # Project documentation (this folder)
└── README.md
```

## How to Run This Project

This project has TWO parts that must run AT THE SAME TIME, in two separate
terminal windows: the backend (FastAPI) and the frontend (React). Neither
works correctly without the other also running.

### 1. Run the Backend

Open a terminal and run:

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

You should see a message ending in something like:
```
Uvicorn running on http://127.0.0.1:8000
```

Leave this terminal open. You can verify it's working by opening
`http://127.0.0.1:8000/docs` in your browser — you should see the interactive
Swagger UI listing all the API endpoints.

### 2. Run the Frontend

Open a **second, separate** terminal (don't close the backend one) and run:

```bash
cd frontend
npm install
npm run dev
```

You should see a message like:
```
VITE ready in ... ms
➜  Local:   http://localhost:3000/
```

Open `http://localhost:3000` in your browser to use the app.

### 3. Using the App

- **Agent View** (default): add sample deliveries, update their status. Works
  even with your wifi turned off — changes save locally and show a
  "Saved locally" badge.
- **Dispatcher View**: shows all deliveries that have been synced to the
  backend, in a table.
- Sync happens automatically every ~15 seconds while online, when
  connectivity is restored after being offline, and on page load. You can
  also click **"Sync Now"** to trigger it immediately.

### Common Issues
- **"Failed to fetch" when syncing** → the backend isn't running, or isn't
  reachable at `http://127.0.0.1:8000`. Check the backend terminal is still
  running and `/docs` loads in your browser.
- **JSX syntax errors on `npm run dev`** → make sure files containing JSX
  (like `App.jsx`, component files) have the `.jsx` extension, not `.js`.
- See `docs/PROJECT_WORKFLOW.md` for a detailed log of every bug encountered
  during development and exactly how each was fixed — useful both for
  troubleshooting and for understanding the project deeply enough to explain
  it in interviews.

## Author
Built by Santy as a portfolio project targeting Python Full Stack / Backend
Developer / SDE roles.
