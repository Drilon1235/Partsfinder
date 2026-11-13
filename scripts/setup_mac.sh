#!/usr/bin/env bash
# Partsfinder - installation on Mac
# Usage (in the project folder):  bash scripts/setup_mac.sh
set -e

cd "$(dirname "$0")/../backend"

PY=""
for v in python3.12 python3.11; do
  if command -v "$v" >/dev/null 2>&1; then PY="$v"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3.12 or 3.11 not found."
  echo "Install Python 3.12 from https://www.python.org/downloads/ (not the Python that ships with macOS)."
  exit 1
fi
echo "$PY found"

[ -d .venv ] || "$PY" -m venv .venv

echo "Installing packages (the first time this can take 5-10 minutes)..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "backend/.env created: fill in your ANTHROPIC_API_KEY there."
fi

echo
echo "Checking the environment..."
.venv/bin/python check_env.py
