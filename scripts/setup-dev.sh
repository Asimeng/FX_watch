#!/usr/bin/env bash
# Create (or rebuild) the local development environment for FX Watch (Linux/macOS).
#
#   1. Picks a Python interpreter (3.12 preferred to match production, else 3.11+).
#   2. Creates .venv and installs the project with dev tools.
#   3. Creates .env from .env.example with a freshly generated SECRET_KEY (never overwrites).
#   4. Creates the local SQLite database and fetches the first rates (unless --skip-fetch).
#
# Usage:
#   ./scripts/setup-dev.sh                    # set up (reuses an existing .venv)
#   ./scripts/setup-dev.sh --recreate         # delete and rebuild .venv
#   ./scripts/setup-dev.sh --python python3.13
#   ./scripts/setup-dev.sh --skip-fetch
set -euo pipefail

PYTHON=""
RECREATE=0
SKIP_FETCH=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --python) PYTHON="$2"; shift 2 ;;
    --recreate) RECREATE=1; shift ;;
    --skip-fetch) SKIP_FETCH=1; shift ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/.."
step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }

# --- 1. interpreter ---------------------------------------------------------------
step "Selecting Python"
supported() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; }
if [[ -n "$PYTHON" ]]; then
  supported "$PYTHON" || { echo "$PYTHON is missing or older than 3.11" >&2; exit 1; }
else
  for candidate in python3.12 python3.13 python3.11 python3.14 python3 python; do
    if command -v "$candidate" >/dev/null && supported "$candidate"; then PYTHON="$candidate"; break; fi
  done
  [[ -n "$PYTHON" ]] || { echo "No Python 3.11+ found. Install python3.12 (and python3.12-venv on Debian/Ubuntu)." >&2; exit 1; }
fi
echo "Using $("$PYTHON" --version) ($(command -v "$PYTHON"))"

# --- 2. virtual environment ---------------------------------------------------------
if [[ -d .venv && $RECREATE -eq 1 ]]; then
  step "Removing existing .venv"
  rm -rf .venv
fi
VENV_PY=.venv/bin/python
[[ -x $VENV_PY ]] || VENV_PY=.venv/Scripts/python.exe  # Git Bash on Windows
if [[ ! -x $VENV_PY ]]; then
  step "Creating .venv"
  if ! "$PYTHON" -m venv .venv; then
    echo "venv creation failed. On Debian/Ubuntu: sudo apt install python3-venv (or python3.12-venv)" >&2
    exit 1
  fi
  VENV_PY=.venv/bin/python
  [[ -x $VENV_PY ]] || VENV_PY=.venv/Scripts/python.exe
else
  echo ".venv already exists ($("$VENV_PY" --version)); reusing it. Pass --recreate to rebuild."
fi

step "Installing FX Watch + dev tools"
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet -e ".[dev]"

# --- 3. .env ---------------------------------------------------------------------------
if [[ ! -f .env ]]; then
  step "Creating .env (console email backend, local SQLite)"
  secret=$("$VENV_PY" -m fxwatch generate-secret 2>/dev/null)
  sed "s|^SECRET_KEY=$|SECRET_KEY=${secret}|" .env.example > .env
  chmod 600 .env
else
  printf '\n.env already exists; leaving it untouched.\n'
fi

# --- 4. database + first data -------------------------------------------------------
step "Preparing database"
"$VENV_PY" -m fxwatch db upgrade
if [[ $SKIP_FETCH -eq 0 ]]; then
  step "Fetching rates (the first run also downloads history, ~1 min)"
  "$VENV_PY" -m fxwatch run-once > /dev/null || echo "Warning: fetch reported problems; check the log above." >&2
fi

printf '\n\033[32mDone. Next:\033[0m\n'
cat <<'EOF'
  source .venv/bin/activate
  streamlit run streamlit_app.py      # http://localhost:8501
  pytest                              # run the test suite
  python -m fxwatch run-once          # fetch rates + evaluate alerts again
EOF
