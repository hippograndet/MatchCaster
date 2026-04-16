#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "╔══════════════════════════════════════╗"
echo "║         M A T C H C A S T E R       ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "  Backend  →  http://localhost:8000"
echo "  Frontend →  http://localhost:5173"
echo ""
echo "Press Ctrl+C to stop."
echo ""

# Ensure Ollama is running
if ! pgrep -x "ollama" > /dev/null; then
  echo "  Starting Ollama..."
  ollama serve &>/dev/null &
  sleep 2
else
  echo "  Ollama already running."
fi

# Check required model is pulled
OLLAMA_MODEL="mistral:7b-instruct-q4_K_M"
if ! ollama list 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
  echo ""
  echo "  WARNING: Model '$OLLAMA_MODEL' not found."
  echo "  Run: ollama pull $OLLAMA_MODEL"
  echo ""
fi

# Start backend
(cd "$ROOT/backend" && python3 -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 2>&1 \
  | while IFS= read -r line; do printf '\033[90m[backend]\033[0m %s\n' "$line"; done) &
BACKEND=$!

# Give backend a moment to bind before frontend starts
sleep 1

# Start frontend
(cd "$ROOT/frontend" && npm run dev 2>&1 \
  | while IFS= read -r line; do printf '\033[36m[frontend]\033[0m %s\n' "$line"; done) &
FRONTEND=$!

# Cleanup on exit
cleanup() {
  echo ""
  echo "Stopping MatchCaster..."
  kill "$BACKEND" "$FRONTEND" 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

wait "$BACKEND" "$FRONTEND"
