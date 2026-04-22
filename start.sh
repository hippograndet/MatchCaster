#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

# ---------------------------------------------------------------------------
# Python virtual environment (.venv)
# ---------------------------------------------------------------------------
VENV_DIR="$ROOT/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating Python virtual environment in .venv ..."
  python3 -m venv "$VENV_DIR"
  source "$VENV_DIR/bin/activate"
  python -m pip install --upgrade pip
  python -m pip install -r "$ROOT/backend/requirements.txt"
else
  source "$VENV_DIR/bin/activate"
fi

PY_VER="$(python --version 2>&1)"

# ---------------------------------------------------------------------------
# Parse backend argument: ./start.sh [groq|local]  (default: groq)
# ---------------------------------------------------------------------------
BACKEND="${1:-groq}"
if [[ "$BACKEND" != "groq" && "$BACKEND" != "local" ]]; then
  echo "Usage: ./start.sh [groq|local]"
  echo "  groq  — Cloud (Groq API, default, requires GROQ_API_KEY)"
  echo "  local — Local Ollama (offline, requires model pulled)"
  exit 1
fi

export LLM_BACKEND="$BACKEND"

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
if [[ "$BACKEND" == "groq" ]]; then
  MODE_LABEL="Cloud (Groq API)"
else
  MODE_LABEL="Local (Ollama)"
fi

echo "╔══════════════════════════════════════╗"
echo "║         M A T C H C A S T E R        ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "  Mode     →  $MODE_LABEL"
echo "  Python   →  $PY_VER (.venv)"
echo "  Backend  →  http://localhost:8000"
echo "  Frontend →  http://localhost:5173"
echo ""

# ---------------------------------------------------------------------------
# Backend-specific pre-flight checks
# ---------------------------------------------------------------------------
if [[ "$BACKEND" == "groq" ]]; then
  if [[ -z "${GROQ_API_KEY:-}" ]]; then
    echo "  WARNING: GROQ_API_KEY is not set."
    echo "  Get a free key at https://console.groq.com and run:"
    echo "    export GROQ_API_KEY=gsk_..."
    echo ""
  fi
else
  # Local mode: ensure Ollama is running and model is pulled
  if ! pgrep -x "ollama" > /dev/null; then
    echo "  Starting Ollama..."
    ollama serve &>/dev/null &
    sleep 2
  else
    echo "  Ollama already running."
  fi

  OLLAMA_MODEL="gemma2:2b-instruct-q4_K_M"
  if ! ollama list 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
    echo ""
    echo "  WARNING: Model '$OLLAMA_MODEL' not found."
    echo "  Run: ollama pull $OLLAMA_MODEL"
    echo ""
  fi
fi

echo "Press Ctrl+C to stop."
echo ""

# ---------------------------------------------------------------------------
# Start backend
# ---------------------------------------------------------------------------
(cd "$ROOT/backend" && python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 2>&1 \
  | while IFS= read -r line; do
      case "$line" in
        *"Will watch for changes"*|*"Started reloader process"*|\
        *"Started server process"*|*"Waiting for application startup"*|\
        *"Uvicorn running on"*) ;;
        *) printf '\033[90m[backend]\033[0m %s\n' "$line" ;;
      esac
    done) &
BACKEND_PID=$!

# Give backend a moment to bind before frontend starts
sleep 1

# ---------------------------------------------------------------------------
# Start frontend
# ---------------------------------------------------------------------------
(cd "$ROOT/frontend" && npm run dev 2>&1 \
  | while IFS= read -r line; do
      case "$line" in
        ""|*"> matchcaster-frontend"*|*"> vite"*|*"Network:"*) ;;
        *) printf '\033[36m[frontend]\033[0m %s\n' "$line" ;;
      esac
    done) &
FRONTEND_PID=$!

# ---------------------------------------------------------------------------
# Cleanup on exit
# ---------------------------------------------------------------------------
cleanup() {
  echo ""
  echo "Stopping MatchCaster..."
  [[ "$BACKEND" == "local" ]] && pkill -x ollama 2>/dev/null || true
  kill -- -$$ 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

while kill -0 "$BACKEND_PID" 2>/dev/null || kill -0 "$FRONTEND_PID" 2>/dev/null; do
  wait
done
