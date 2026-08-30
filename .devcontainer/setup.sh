#!/usr/bin/env bash
# One-time Codespace setup. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/../free_tsenta_clone"

echo "==> Python dependencies"
pip install --user -q -r requirements.txt

echo "==> Chromium for the ATS agent (--with-deps: the base image lacks the system libs)"
python -m playwright install --with-deps chromium || \
  echo "!! Chromium install failed — everything except ATS form-filling still works."

echo "==> Building the dashboard"
cd frontend && npm install --no-audit --no-fund && npm run build && cd ..

echo
echo "Setup complete. Start it with:"
echo "    cd free_tsenta_clone && uvicorn app.main:app --host 0.0.0.0 --port 8000"
