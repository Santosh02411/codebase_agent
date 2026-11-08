#!/usr/bin/env bash
# Builds the web app and installs it where the backend serves it (app/webapp, shown at http://localhost:8000).
# Needs Node 18+. Run again after changing anything in frontend/.
set -euo pipefail
cd "$(dirname "$0")/../frontend"
[ -d node_modules ] || npm install --no-audit --no-fund
# empty API URL = same origin as the page, because FastAPI serves both
NEXT_PUBLIC_API_URL="" NEXT_TELEMETRY_DISABLED=1 npm run build
rm -rf ../app/webapp
cp -r out ../app/webapp
echo "Installed into app/webapp. Start the backend:  uvicorn app.main:app --reload   ->  http://localhost:8000"
