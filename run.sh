#!/usr/bin/env bash
# Launch the academic dashboard locally.
set -e
cd "$(dirname "$0")"

# Create a virtual environment on first run.
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt
fi

# Build the database from the outlines if it doesn't exist yet.
if [ ! -f "dashboard.db" ]; then
  echo "Scanning course outlines..."
  ./.venv/bin/python -m app.store
fi

echo "Dashboard running at http://127.0.0.1:5173  (Ctrl+C to stop)"
exec ./.venv/bin/python -m app.server
