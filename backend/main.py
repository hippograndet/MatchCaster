# backend/main.py
# FastAPI application entrypoint for MatchCaster.

from __future__ import annotations

import logging
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import HOST, PORT

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("[MAIN]")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="MatchCaster",
    description="AI Football Commentary Engine",
    version="1.0.0",
)

# CORS — allow the Vite dev server on port 5173 (and any origin in dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Mount routers
# ---------------------------------------------------------------------------
from player.emitter import router as emitter_router
from ws.handler import router as ws_router

app.include_router(emitter_router)
app.include_router(ws_router)


# ---------------------------------------------------------------------------
# Lineup endpoint (for formation display)
# ---------------------------------------------------------------------------
from pathlib import Path
import json as _json
from fastapi import HTTPException
from config import LINEUPS_DIR

@app.get("/api/lineup/{match_id}")
async def get_lineup(match_id: str):
    """
    Return starting XI for both teams: home and away arrays of
    {name, jersey_number, positions[]} (positions from StatsBomb lineup file).
    """
    lineup_path = Path(LINEUPS_DIR) / f"{match_id}.json"
    if not lineup_path.exists():
        return {"home": [], "away": []}

    with open(lineup_path, "r", encoding="utf-8") as f:
        lineups = _json.load(f)

    result = {"home": [], "away": []}
    teams = []

    for team_lineup in lineups:
        team_name = team_lineup.get("team_name", "")
        players = []
        for p in team_lineup.get("lineup", []):
            positions = p.get("positions", [])
            # Only include players with a starting position (from == "00:00:00.000")
            starting_positions = [
                pos.get("position", "Center Midfield")
                for pos in positions
                if pos.get("from", "") == "00:00:00.000" or not positions
            ]
            if not starting_positions and positions:
                starting_positions = [positions[0].get("position", "Center Midfield")]
            if not starting_positions:
                continue   # non-starter

            nick = p.get("player_nickname") or ""
            full = p.get("player_name", "Unknown")
            display_name = nick.strip() if nick.strip() else full

            players.append({
                "name": display_name,
                "jersey_number": p.get("jersey_number", 0),
                "positions": starting_positions,
            })

        teams.append({"name": team_name, "players": players})

    if len(teams) >= 2:
        result["home"] = teams[0]["players"]
        result["away"] = teams[1]["players"]

    return result


# ---------------------------------------------------------------------------
# Match summary (activity waveform + goal markers for seek bar)
# ---------------------------------------------------------------------------
import player.loader as _loader
from player.loader import compute_snapshots as _compute_snapshots

SKIP_TYPES = {
    'Ball Receipt*', 'Ball Recovery', 'Starting XI',
    'Half Start', 'Half End', 'Referee Ball-Drop',
    'Pressure', 'Carry',
}

@app.get("/api/match_summary/{match_id}")
async def get_match_summary(match_id: str):
    """
    Return activity buckets (60s) and goal markers for the seek-bar waveform.
    """
    try:
        events = _loader.load_events(match_id)
    except FileNotFoundError:
        return {"home_team": "", "goals": [], "buckets": [], "total_time": 5400}

    # Determine home team from lineup
    lineup_path = Path(LINEUPS_DIR) / f"{match_id}.json"
    home_team = ""
    if lineup_path.exists():
        with open(lineup_path, "r", encoding="utf-8") as f:
            lineups_data = _json.load(f)
        if lineups_data:
            home_team = lineups_data[0].get("team_name", "")

    total_time = events[-1].timestamp_sec if events else 5400
    bucket_size = 60
    n_buckets = max(1, int(total_time / bucket_size) + 1)
    buckets = [{"t": i * bucket_size, "home": 0, "away": 0} for i in range(n_buckets)]

    goals = []
    for e in events:
        if e.event_type in SKIP_TYPES:
            continue
        bi = min(int(e.timestamp_sec / bucket_size), n_buckets - 1)
        is_home = e.team == home_team
        if is_home:
            buckets[bi]["home"] += 1
        else:
            buckets[bi]["away"] += 1

        if e.event_type == "Shot" and e.details.get("shot_outcome") == "Goal":
            goals.append({
                "timestamp_sec": e.timestamp_sec,
                "team": e.team,
                "player": e.player,
            })

    # Also determine away team for snapshot computation
    away_team = ""
    if lineup_path.exists():
        if lineups_data and len(lineups_data) >= 2:
            away_team = lineups_data[1].get("team_name", "")

    snapshots = _compute_snapshots(events, home_team, away_team) if home_team else []

    return {
        "home_team": home_team,
        "goals": goals,
        "buckets": buckets,
        "total_time": total_time,
        "snapshots": snapshots,
    }


# ---------------------------------------------------------------------------
# Developer inspection endpoints (DEV_MODE=true only — never in production)
# ---------------------------------------------------------------------------
from typing import Optional
from pydantic import BaseModel
from config import DEV_MODE
import config as _config
from debug.override import override_store


@app.get("/api/dev/config")
async def dev_config():
    """Return all config.py constants for the DevPanel config tab."""
    if not DEV_MODE:
        raise HTTPException(status_code=404)
    return {
        k: v for k, v in vars(_config).items()
        if not k.startswith("_") and isinstance(v, (str, int, float, bool, dict, list))
    }


class PromptOverrideRequest(BaseModel):
    agent: str                          # "play_by_play" | "tactical" | "stats"
    system_prompt: Optional[str] = None # replaces general context for next LLM call
    user_prompt: Optional[str] = None   # replaces assembled user turn for next LLM call


@app.post("/api/dev/prompt-override")
async def dev_prompt_override(req: PromptOverrideRequest):
    """Queue a one-shot prompt override for the next generate() call from this agent."""
    if not DEV_MODE:
        raise HTTPException(status_code=404)
    payload = {}
    if req.system_prompt is not None:
        payload["system_prompt"] = req.system_prompt
    if req.user_prompt is not None:
        payload["user_prompt"] = req.user_prompt
    if not payload:
        raise HTTPException(status_code=400, detail="Provide system_prompt and/or user_prompt")
    override_store.set(req.agent, payload)
    return {"status": "queued", "agent": req.agent}


@app.delete("/api/dev/prompt-override/{agent}")
async def dev_clear_override(agent: str):
    """Discard a pending override without applying it."""
    if not DEV_MODE:
        raise HTTPException(status_code=404)
    override_store.consume(agent)
    return {"status": "cleared", "agent": agent}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "MatchCaster"}


@app.get("/")
async def root():
    return {
        "service": "MatchCaster Backend",
        "docs": "/docs",
        "websocket": "ws://localhost:8000/ws/match?match_id=<id>",
        "matches": "/api/matches",
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting MatchCaster backend…")
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=True,
        log_level="info",
    )
