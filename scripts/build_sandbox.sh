#!/bin/sh
# Build the sandbox images used by SANDBOX_MODE=docker (the default). Build the languages you need, e.g.:  scripts/build_sandbox.sh python node
set -e
cd "$(dirname "$0")/../sandbox"
langs="${*:-python node go rust java}"
for l in $langs; do
  echo "== building codebase-agent/sandbox-$l"
  docker build -f "Dockerfile.$l" -t "codebase-agent/sandbox-$l:latest" .
done
