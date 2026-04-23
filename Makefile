.PHONY: help setup install run run-cloud run-local clean test data dev-backend dev-frontend stop verify

# Variables
PYTHON ?= python3
PIP ?= pip
NPM ?= npm
VENV_DIR = .venv
BACKEND_DIR = backend
FRONTEND_DIR = frontend
DATA_DIR = data
ROOT_DIR = $(shell pwd)

# Default target
help:
	@echo "╔══════════════════════════════════════╗"
	@echo "║         M A T C H C A S T E R        ║"
	@echo "╚══════════════════════════════════════╝"
	@echo ""
	@echo "Available commands:"
	@echo "  make setup      - Full setup (venv, deps, data)"
	@echo "  make install    - Install dependencies only"
	@echo "  make data       - Download match data"
	@echo "  make run        - Run in cloud mode (Groq, default)"
	@echo "  make run-cloud  - Same as 'make run'"
	@echo "  make run-local  - Run in local mode (Ollama)"
	@echo "  make dev        - Run with live reload (both backend & frontend)"
	@echo "  make dev-backend - Run only backend with live reload"
	@echo "  make dev-frontend - Run only frontend dev server"
	@echo "  make clean      - Remove venv and cleanup"
	@echo "  make stop       - Stop all running processes"
	@echo "  make test       - Run test suite"
	@echo ""
	@echo "Environment variables:"
	@echo "  GROQ_API_KEY    - Required for cloud mode"
	@echo "  LLM_BACKEND     - Override backend (groq/local)"

# Check if Python 3.11+ is available
PYTHON_CHECK := $(shell $(PYTHON) --version 2>&1 | grep -E "Python 3\.1[1-9]|Python 3\.[2-9]" || echo "OLD")
ifeq ($(PYTHON_CHECK),OLD)
$(error Python 3.11+ is required. Please install Python 3.11 or higher.)
endif

# Check if Node.js 18+ is available
NODE_CHECK := $(shell $(NPM) --version >/dev/null 2>&1 && echo "OK" || echo "MISSING")
ifeq ($(NODE_CHECK),MISSING)
$(error Node.js 18+ is required. Please install Node.js 18 or higher.)
endif

# Full setup: install dependencies and download data
setup: install data
	@echo ""
	@echo "✅ Setup complete!"
	@echo "   - Python virtual environment: $(VENV_DIR)"
	@echo "   - Backend dependencies installed"
	@echo "   - Frontend dependencies installed"
	@echo "   - Match data downloaded"
	@echo ""
	@echo "Next steps:"
	@echo "   source $(VENV_DIR)/bin/activate    # Activate virtual environment"
	@echo "   export GROQ_API_KEY=your_key_here  # For cloud mode"
	@echo "   make run                           # Start application"

# Install all dependencies (always run, but skip if already done)
install:
	@if [ ! -d "$(VENV_DIR)" ]; then \
		echo "🔧 Creating Python virtual environment..."; \
		$(PYTHON) -m venv $(VENV_DIR); \
	fi
	@echo "📦 Installing Python dependencies..."
	@source $(VENV_DIR)/bin/activate && $(PIP) install --upgrade pip >/dev/null 2>&1
	@source $(VENV_DIR)/bin/activate && $(PIP) install -r $(BACKEND_DIR)/requirements.txt
	@echo "📦 Installing frontend dependencies..."
	@cd $(FRONTEND_DIR) && $(NPM) install
	@echo "✅ Dependencies installed successfully"

# Download match data
data:
	@echo "📥 Downloading match data..."
	@if [ ! -d "$(DATA_DIR)/matches" ] || [ ! -d "$(DATA_DIR)/lineups" ]; then \
		cd $(DATA_DIR) && bash setup.sh; \
	else \
		echo "⚠️  Match data already exists. Remove data/matches and data/lineups to re-download."; \
	fi

# Run in cloud mode (default)
run: export LLM_BACKEND=groq
run:
	@if [ ! -d "$(VENV_DIR)" ]; then \
		echo "❌ Virtual environment not found. Run 'make setup' first."; \
		exit 1; \
	fi
	@if [ -z "$${GROQ_API_KEY:-}" ]; then \
		echo "❌ GROQ_API_KEY is not set."; \
		echo ""; \
		echo "To use cloud mode, get a free key at https://console.groq.com"; \
		echo "and run: export GROQ_API_KEY=your_key_here"; \
		echo ""; \
		echo "Alternatively, use local mode without an API key:"; \
		echo "  make run-local"; \
		echo ""; \
		exit 1; \
	fi
	@echo "╔══════════════════════════════════════╗"
	@echo "║         M A T C H C A S T E R        ║"
	@echo "╚══════════════════════════════════════╝"
	@echo ""
	@echo "  Mode     →  Cloud (Groq API)"
	@echo "  Python   →  $$(source $(VENV_DIR)/bin/activate && python --version 2>&1)"
	@echo "  Backend  →  http://localhost:8000"
	@echo "  Frontend →  http://localhost:5173"
	@echo ""
	@echo "Starting services..."
	@echo "Press Ctrl+C to stop."
	@echo ""
	@# Start backend in background
	@( \
		source $(VENV_DIR)/bin/activate; \
		cd $(BACKEND_DIR); \
		exec python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 2>&1 | \
		while IFS= read -r line; do \
			case "$$line" in \
				*"Will watch for changes"*|*"Started reloader process"*|*"Started server process"*|*"Waiting for application startup"*|*"Uvicorn running on"*) ;; \
				*) printf '\033[90m[backend]\033[0m %s\n' "$$line" ;; \
			esac; \
		done \
	) & \
	BACKEND_PID=$$!; \
	sleep 2; \
	( \
		cd $(FRONTEND_DIR); \
		exec $(NPM) run dev 2>&1 | \
		while IFS= read -r line; do \
			case "$$line" in \
				*"> matchcaster-frontend"*|*"> vite"*|*"Network:"*) ;; \
				*) printf '\033[36m[frontend]\033[0m %s\n' "$$line" ;; \
			esac; \
		done \
	) & \
	FRONTEND_PID=$$!; \
	trap 'echo ""; echo "Stopping MatchCaster..."; kill $$BACKEND_PID $$FRONTEND_PID 2>/dev/null || true; exit 0' INT TERM; \
	wait $$BACKEND_PID $$FRONTEND_PID 2>/dev/null || true

# Run in cloud mode (explicit)
run-cloud: run

# Run in local mode (Ollama)
run-local: export LLM_BACKEND=local
run-local:
	@if [ ! -d "$(VENV_DIR)" ]; then \
		echo "❌ Virtual environment not found. Run 'make setup' first."; \
		exit 1; \
	fi
	@echo "╔══════════════════════════════════════╗"
	@echo "║         M A T C H C A S T E R        ║"
	@echo "╚══════════════════════════════════════╝"
	@echo ""
	@echo "  Mode     →  Local (Ollama)"
	@echo "  Python   →  $$(source $(VENV_DIR)/bin/activate && python --version 2>&1)"
	@echo "  Backend  →  http://localhost:8000"
	@echo "  Frontend →  http://localhost:5173"
	@echo ""
	@# Check if Ollama is running
	@if ! pgrep -x "ollama" > /dev/null; then \
		echo "  Starting Ollama..."; \
		ollama serve &>/dev/null & \
		sleep 2; \
	else \
		echo "  Ollama already running."; \
	fi
	@# Check if model is pulled
	@OLLAMA_MODEL="gemma2:2b-instruct-q4_K_M"; \
	if ! ollama list 2>/dev/null | grep -q "$$OLLAMA_MODEL"; then \
		echo ""; \
		echo "  ⚠️  WARNING: Model '$$OLLAMA_MODEL' not found."; \
		echo "  Run: ollama pull $$OLLAMA_MODEL"; \
		echo ""; \
	fi
	@echo "Starting services..."
	@echo "Press Ctrl+C to stop."
	@echo ""
	@# Start backend in background
	@( \
		source $(VENV_DIR)/bin/activate; \
		cd $(BACKEND_DIR); \
		exec python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 2>&1 | \
		while IFS= read -r line; do \
			case "$$line" in \
				*"Will watch for changes"*|*"Started reloader process"*|*"Started server process"*|*"Waiting for application startup"*|*"Uvicorn running on"*) ;; \
				*) printf '\033[90m[backend]\033[0m %s\n' "$$line" ;; \
			esac; \
		done \
	) & \
	BACKEND_PID=$$!; \
	sleep 2; \
	( \
		cd $(FRONTEND_DIR); \
		exec $(NPM) run dev 2>&1 | \
		while IFS= read -r line; do \
			case "$$line" in \
				*"> matchcaster-frontend"*|*"> vite"*|*"Network:"*) ;; \
				*) printf '\033[36m[frontend]\033[0m %s\n' "$$line" ;; \
			esac; \
		done \
	) & \
	FRONTEND_PID=$$!; \
	trap 'echo ""; echo "Stopping MatchCaster..."; pkill -x ollama 2>/dev/null || true; kill $$BACKEND_PID $$FRONTEND_PID 2>/dev/null || true; exit 0' INT TERM; \
	wait $$BACKEND_PID $$FRONTEND_PID 2>/dev/null || true

# Run with live reload (both backend & frontend)
dev: export LLM_BACKEND=groq
dev:
	@if [ ! -d "$(VENV_DIR)" ]; then \
		echo "❌ Virtual environment not found. Run 'make setup' first."; \
		exit 1; \
	fi
	@if [ -z "$${GROQ_API_KEY:-}" ]; then \
		echo "❌ GROQ_API_KEY is not set."; \
		echo ""; \
		echo "To use cloud mode, get a free key at https://console.groq.com"; \
		echo "and run: export GROQ_API_KEY=your_key_here"; \
		echo ""; \
		echo "Alternatively, use local mode without an API key:"; \
		echo "  make run-local"; \
		echo ""; \
		exit 1; \
	fi
	@echo "╔══════════════════════════════════════╗"
	@echo "║         M A T C H C A S T E R        ║"
	@echo "╚══════════════════════════════════════╝"
	@echo ""
	@echo "  Mode     →  Cloud (Groq API)"
	@echo "  Python   →  $$(source $(VENV_DIR)/bin/activate && python --version 2>&1)"
	@echo "  Backend  →  http://localhost:8000"
	@echo "  Frontend →  http://localhost:5173"
	@echo ""
	@echo "Starting services..."
	@echo "Press Ctrl+C to stop."
	@echo ""
	@# Start backend in background
	@( \
		source $(VENV_DIR)/bin/activate; \
		cd $(BACKEND_DIR); \
		exec python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 2>&1 | \
		while IFS= read -r line; do \
			case "$$line" in \
				*"Will watch for changes"*|*"Started reloader process"*|*"Started server process"*|*"Waiting for application startup"*|*"Uvicorn running on"*) ;; \
				*) printf '\033[90m[backend]\033[0m %s\n' "$$line" ;; \
			esac; \
		done \
	) & \
	BACKEND_PID=$$!; \
	sleep 2; \
	( \
		cd $(FRONTEND_DIR); \
		exec $(NPM) run dev 2>&1 | \
		while IFS= read -r line; do \
			case "$$line" in \
				*"> matchcaster-frontend"*|*"> vite"*|*"Network:"*) ;; \
				*) printf '\033[36m[frontend]\033[0m %s\n' "$$line" ;; \
			esac; \
		done \
	) & \
	FRONTEND_PID=$$!; \
	trap 'echo ""; echo "Stopping MatchCaster..."; kill $$BACKEND_PID $$FRONTEND_PID 2>/dev/null || true; exit 0' INT TERM; \
	wait $$BACKEND_PID $$FRONTEND_PID 2>/dev/null || true

# Run only backend dev server
dev-backend:
	@if [ ! -d "$(VENV_DIR)" ]; then \
		echo "❌ Virtual environment not found. Run 'make setup' first."; \
		exit 1; \
	fi
	@echo "🚀 Starting backend development server..."
	@source $(VENV_DIR)/bin/activate && cd $(BACKEND_DIR) && python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Run only frontend dev server
dev-frontend:
	@if [ ! -d "$(VENV_DIR)" ]; then \
		echo "❌ Virtual environment not found. Run 'make setup' first."; \
		exit 1; \
	fi
	@echo "🎨 Starting frontend development server..."
	@cd $(FRONTEND_DIR) && $(NPM) run dev

# Clean up
clean:
	@echo "🧹 Cleaning up..."
	@if [ -d "$(VENV_DIR)" ]; then \
		rm -rf $(VENV_DIR); \
		echo "  ✓ Removed virtual environment"; \
	else \
		echo "  ℹ️  No virtual environment found"; \
	fi
	@if [ -d "$(FRONTEND_DIR)/node_modules" ]; then \
		rm -rf $(FRONTEND_DIR)/node_modules; \
		echo "  ✓ Removed frontend dependencies"; \
	else \
		echo "  ℹ️  No frontend dependencies found"; \
	fi
	@echo "✅ Cleanup complete"

# Stop all running processes
stop:
	@echo "🛑 Stopping all MatchCaster processes..."
	@-pkill -f "uvicorn main:app" 2>/dev/null || true
	@-pkill -f "vite" 2>/dev/null || true
	@-pkill -x ollama 2>/dev/null || true
	@echo "✅ All processes stopped"

# Run tests
test:
	@if [ ! -d "$(VENV_DIR)" ]; then \
		echo "❌ Virtual environment not found. Run 'make setup' first."; \
		exit 1; \
	fi
	@echo "🧪 Running tests..."
	@source $(VENV_DIR)/bin/activate && $(PIP) install pytest >/dev/null 2>&1 || true
	@source $(VENV_DIR)/bin/activate && cd $(BACKEND_DIR) && python -m pytest --tb=short || echo "⚠️  No tests found or pytest failed"

# Verify setup
verify:
	@if [ ! -d "$(VENV_DIR)" ]; then \
		echo "❌ Virtual environment not found. Run 'make setup' first."; \
		exit 1; \
	fi
	@echo "🔍 Verifying setup..."
	@source $(VENV_DIR)/bin/activate && python -c "import fastapi, uvicorn" 2>/dev/null && echo "  ✓ Python dependencies OK" || echo "  ✗ Python dependencies missing"
	@cd $(FRONTEND_DIR) && npm ls react >/dev/null 2>&1 && echo "  ✓ Frontend dependencies OK" || echo "  ✗ Frontend dependencies missing"
	@[ -d "$(DATA_DIR)/matches" ] && [ "$$(ls -1 $(DATA_DIR)/matches/*.json 2>/dev/null | wc -l)" -gt 0 ] && echo "  ✓ Match data OK ($$(ls -1 $(DATA_DIR)/matches/*.json 2>/dev/null | wc -l) matches)" || echo "  ✗ Match data missing"
	@echo "✅ Verification complete"