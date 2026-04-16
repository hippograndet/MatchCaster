# Development & Debugging Guidelines

## Architecture
This project is split into isolated subsystems. Each folder under `backend/` is a self-contained module. Respect those boundaries — don't create cross-dependencies unless explicitly discussed.

## Debugging approach
- Always isolate before integrating. When something breaks, identify which subsystem fails and fix it there first.
- Use `debug/` scripts as the primary testing interface. Each subsystem should have a standalone `debug/test_<subsystem>.py` that runs with hardcoded or snapshot inputs.
- Use `debug/snapshots/` for intermediate JSON dumps between subsystems so failures are reproducible.
- When I report a bug, ask me (or check) which subsystem boundary it crosses before proposing a fix.

## How to help me
- Scoped fixes only. Fix one module at a time, never refactor across subsystems in a single pass.
- When I paste an error, check the relevant debug script first. If none exists, write one.
- For LLM output issues (wrong format, hallucinations), fix the prompt, not the surrounding code, unless the code genuinely doesn't handle the output correctly.
- For real-time/timing bugs, look at timestamps in logs before suggesting code changes.

## Code standards
- Structured logging everywhere: `[timestamp] [subsystem.module] message`. Set up in `config.py`.
- All inter-subsystem data flows through typed dicts or Pydantic models — no raw strings between modules.
- New features get a debug script before they get wired into main.py.