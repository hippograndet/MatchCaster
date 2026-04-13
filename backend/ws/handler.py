# backend/ws/handler.py
from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from audio.queue import AudioQueue
from director.router import Director
from director.state import SharedMatchState
from replay.emitter import get_or_create_session, ReplaySession
from replay.loader import load_events, list_available_matches
from analysis.engine import MatchAnalysisEngine
from enrichment.match_meta import get_match_meta
from enrichment.weather import fetch_weather
from enrichment.team_colors import get_team_colors

logger = logging.getLogger("[WS]")

router = APIRouter()
_sessions: dict[str, "MatchSession"] = {}


class MatchSession:
    def __init__(self, match_id: str) -> None:
        self.match_id = match_id
        self.clients: set[WebSocket] = set()

        self.state = SharedMatchState()
        self.audio_queue = AudioQueue()
        self.director = Director(
            state=self.state,
            audio_queue=self.audio_queue,
            broadcast_cb=self._broadcast,
            speed_cb=self._on_speed_override,
        )

        self.replay_session = get_or_create_session(match_id)
        self.replay_session.clock.register_tick(self._on_clock_tick)

        self._audio_pump_task: Optional[asyncio.Task] = None
        self._clock_broadcast_task: Optional[asyncio.Task] = None
        self._event_consumer_task: Optional[asyncio.Task] = None

        self._nickname_map: dict[str, str] = {}
        self._match_meta: dict = {}
        self._goal_scorers: dict[str, list[dict]] = {}
        self._analysis: MatchAnalysisEngine | None = None
        self._team_colors: dict[str, dict] = {}

        self._init_teams()
        self._load_nicknames()

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def _init_teams(self) -> None:
        # Primary: use lineup JSON (authoritative home/away ordering)
        from config import LINEUPS_DIR
        lineup_path = Path(LINEUPS_DIR) / f"{self.match_id}.json"
        if lineup_path.exists():
            try:
                with open(lineup_path, "r", encoding="utf-8") as f:
                    lineups = json.load(f)
                if len(lineups) >= 2:
                    self.state.home_team = lineups[0].get("team_name", "")
                    self.state.away_team = lineups[1].get("team_name", "")
                    self.state.score = {"home": 0, "away": 0}
                    return
            except Exception as exc:
                logger.warning(f"Could not read lineup for teams: {exc}")
        # Fallback: infer from first 50 events
        events = self.replay_session.events
        if not events:
            return
        teams = list(dict.fromkeys(
            e.team for e in events[:50] if e.team and e.team != "Unknown"
        ))
        if len(teams) >= 2:
            self.state.home_team = teams[0]
            self.state.away_team = teams[1]
            self.state.score = {"home": 0, "away": 0}

    def _load_nicknames(self) -> None:
        """Load player_nickname from StatsBomb lineup file."""
        from config import LINEUPS_DIR
        lineup_path = Path(LINEUPS_DIR) / f"{self.match_id}.json"
        if not lineup_path.exists():
            return
        try:
            with open(lineup_path, "r", encoding="utf-8") as f:
                lineups = json.load(f)
            for team_lineup in lineups:
                for player in team_lineup.get("lineup", []):
                    full_name = player.get("player_name", "")
                    nickname = player.get("player_nickname") or ""
                    if full_name:
                        # Use nickname if present, else extract last name
                        short = nickname.strip() if nickname.strip() else _extract_short_name(full_name)
                        self._nickname_map[full_name] = short
            logger.info(f"Loaded {len(self._nickname_map)} player nicknames")
        except Exception as exc:
            logger.warning(f"Could not load nicknames: {exc}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self.director.start()
        self._audio_pump_task = asyncio.get_event_loop().create_task(self._audio_pump())
        self._clock_broadcast_task = asyncio.get_event_loop().create_task(self._clock_broadcast())
        self._event_queue = self.replay_session.subscribe()
        self._event_consumer_task = asyncio.get_event_loop().create_task(self._event_consumer())
        asyncio.get_event_loop().create_task(self._load_enrichment())
        if not self.replay_session.clock.is_running:
            self.replay_session.clock.start()
        logger.info(f"MatchSession started: {self.match_id}")

    async def _load_enrichment(self) -> None:
        """Fetch weather + build full match meta; initialise analysis engine."""
        home = self.state.home_team or ""
        away = self.state.away_team or ""

        full_meta = get_match_meta(self.match_id, home, away)
        self._team_colors = {
            home: get_team_colors(home),
            away: get_team_colors(away),
        }

        # Fetch weather (non-blocking — failure silently ignored)
        weather = None
        if full_meta.latitude and full_meta.date:
            kick_h = int(full_meta.kick_off.split(":")[0]) if full_meta.kick_off else 20
            weather = await fetch_weather(
                full_meta.latitude, full_meta.longitude, full_meta.date, kick_h
            )

        self._match_meta = {
            "competition": full_meta.competition,
            "season": full_meta.season,
            "date": full_meta.date,
            "kick_off": full_meta.kick_off,
            "stadium": full_meta.stadium,
            "city": full_meta.city,
            "country": full_meta.country,
            "home_manager": full_meta.home_manager,
            "away_manager": full_meta.away_manager,
            "weather": weather.description if weather and weather.available else "",
            "home_colors": self._team_colors.get(home, {}),
            "away_colors": self._team_colors.get(away, {}),
        }

        # Initialise real-time analysis engine
        if home and away:
            self._analysis = MatchAnalysisEngine(home, away)

        # Broadcast enriched meta to all connected clients
        await self._broadcast({
            "type": "state",
            "state": self.state.to_dict(),
            "clock": {
                "match_time": self.replay_session.clock.get_time(),
                "speed": self.replay_session.clock.speed,
                "running": self.replay_session.clock.is_running,
            },
            "match_id": self.match_id,
            "nickname_map": self._nickname_map,
            "match_meta": self._match_meta,
        })
        # Inject match context into the director so agents know where/when they are
        ctx_parts = []
        if full_meta.competition:
            ctx_parts.append(f"{full_meta.competition} {full_meta.season}")
        if full_meta.stadium and full_meta.city:
            ctx_parts.append(f"{full_meta.stadium}, {full_meta.city}")
        if weather and weather.available:
            ctx_parts.append(f"Conditions: {weather.description}")
        if full_meta.home_manager and home:
            ctx_parts.append(f"{home} manager: {full_meta.home_manager}")
        if full_meta.away_manager and away:
            ctx_parts.append(f"{away} manager: {full_meta.away_manager}")
        if ctx_parts:
            self.director.set_match_context(" | ".join(ctx_parts))

        logger.info(f"Enrichment loaded: {full_meta.competition} | {full_meta.stadium} | weather={weather.description if weather and weather.available else 'N/A'}")

    def stop(self) -> None:
        self.director.stop()
        for t in (self._audio_pump_task, self._clock_broadcast_task, self._event_consumer_task):
            if t:
                t.cancel()
        self.replay_session.clock.stop()

    # ------------------------------------------------------------------
    # Client management
    # ------------------------------------------------------------------

    async def add_client(self, ws: WebSocket) -> None:
        self.clients.add(ws)
        try:
            msg: dict = {
                "type": "state",
                "state": self.state.to_dict(),
                "clock": {
                    "match_time": self.replay_session.clock.get_time(),
                    "speed": self.replay_session.clock.speed,
                    "running": self.replay_session.clock.is_running,
                },
                "match_id": self.match_id,
                "nickname_map": self._nickname_map,
            }
            # Only include match_meta once it has been loaded (avoid empty dict overwriting null)
            if self._match_meta:
                msg["match_meta"] = self._match_meta
            await ws.send_text(json.dumps(msg))
        except Exception:
            pass

    def remove_client(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def handle_message(self, ws: WebSocket, message: str) -> None:
        try:
            msg = json.loads(message)
        except json.JSONDecodeError:
            return

        action = msg.get("action")

        if action == "play":
            speed = float(msg.get("speed", self.replay_session.clock.speed))
            self.director.set_base_speed(speed)
            self.director.set_paused(False)
            self.replay_session.clock.set_speed(speed)
            if self.replay_session.clock._paused:
                self.replay_session.clock.resume()
            else:
                self.replay_session.clock.start()

        elif action == "pause":
            # BUG FIX: pause commentary AND clock together
            self.replay_session.clock.pause()
            self.director.set_paused(True)

        elif action == "set_speed":
            speed = float(msg.get("speed", 5))
            self.director.set_base_speed(speed)
            self.replay_session.clock.set_speed(speed)

        elif action == "set_personality":
            self.director.personality = msg.get("personality", "neutral")

        elif action == "rewind":
            # Rewind 30 match-seconds (legacy — prefer 'seek' with target_time)
            current = self.replay_session.clock.get_time()
            target = max(0.0, current - 30.0)
            was_paused = self.replay_session.clock._paused
            self.replay_session.clock.pause()
            self.replay_session.seek(target)
            self.director.set_paused(True)
            self.director._last_utterance_game_time = target - 999
            if not was_paused:
                self.replay_session.clock.resume()
                self.director.set_paused(False)

        elif action == "seek":
            # Seek to absolute match time
            target = max(0.0, float(msg.get("target_time", 0)))
            was_paused = self.replay_session.clock._paused
            self.replay_session.clock.pause()
            self.replay_session.seek(target)
            self.director.set_paused(True)
            self.director._last_utterance_game_time = target - 999
            if not was_paused:
                self.replay_session.clock.resume()
                self.director.set_paused(False)

        elif action == "reset":
            self.replay_session.clock.stop()
            self.replay_session.reset()
            self.state = SharedMatchState()
            self._init_teams()
            self.audio_queue.clear()
            self.director.state = self.state
            self.director.is_paused = False
            self.director._match_ended = False
            self._goal_scorers = {}
            self.replay_session.clock.start()

        await self._broadcast({
            "type": "clock",
            "match_time": self.replay_session.clock.get_time(),
            "speed": self.replay_session.clock.speed,
            "running": self.replay_session.clock.is_running,
        })

    # ------------------------------------------------------------------
    # Speed callback from director (dynamic speed)
    # ------------------------------------------------------------------

    def _on_speed_override(self, speed: float) -> None:
        self.replay_session.clock.set_speed(speed)
        asyncio.get_event_loop().create_task(self._broadcast({
            "type": "clock",
            "match_time": self.replay_session.clock.get_time(),
            "speed": speed,
            "running": self.replay_session.clock.is_running,
        }))

    # ------------------------------------------------------------------
    # Internal tasks
    # ------------------------------------------------------------------

    async def _on_clock_tick(self, match_time: float) -> None:
        pass  # events handled via subscriber queue

    async def _event_consumer(self) -> None:
        batch: list[dict] = []

        async def flush() -> None:
            nonlocal batch
            if not batch:
                return
            event_map = {e.id: e for e in self.replay_session.events}
            events = [event_map[d["id"]] for d in batch if d["id"] in event_map]
            batch = []

            # Apply nicknames to event player fields
            for ev in events:
                if ev.player in self._nickname_map:
                    ev.player = self._nickname_map[ev.player]
                # Also apply to pass_recipient
                recip = ev.details.get("pass_recipient")
                if recip and recip in self._nickname_map:
                    ev.details["pass_recipient"] = self._nickname_map[recip]
                sub = ev.details.get("sub_replacement")
                if sub and sub in self._nickname_map:
                    ev.details["sub_replacement"] = self._nickname_map[sub]

            if events:
                try:
                    clock_time = self.replay_session.clock.get_time()
                    # Update analysis engine
                    if self._analysis:
                        self._analysis.update(events, clock_time)
                        snapshot = self._analysis.get_context_snapshot()
                        self.director.set_analysis_snapshot(snapshot)
                    await self.director.process_events(events, clock_time)
                except Exception as exc:
                    logger.error(f"Director error: {exc}")

        try:
            while True:
                try:
                    payload = await asyncio.wait_for(self._event_queue.get(), timeout=0.1)
                    batch.append(payload)
                except asyncio.TimeoutError:
                    if batch:
                        await flush()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"Event consumer error: {exc}")

    async def _audio_pump(self) -> None:
        try:
            while True:
                item = await self.audio_queue.get()
                msg: dict = {
                    "type": "audio",
                    "agent": item.agent_name,
                    "text": item.text,
                    "match_time": item.match_time,
                }
                if item.audio_bytes:
                    msg["audio_b64"] = base64.b64encode(item.audio_bytes).decode("ascii")
                    msg["audio_format"] = "wav"
                await self._broadcast(msg)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(f"Audio pump error: {exc}")

    async def _clock_broadcast(self) -> None:
        _analysis_tick = 0
        try:
            while True:
                await asyncio.sleep(0.5)
                if not self.clients:
                    continue
                msg: dict = {
                    "type": "clock",
                    "match_time": self.replay_session.clock.get_time(),
                    "speed": self.replay_session.clock.speed,
                    "running": self.replay_session.clock.is_running,
                    "state": self.state.to_dict(),
                }
                # Send analysis snapshot every 5 seconds (10 ticks)
                _analysis_tick += 1
                if _analysis_tick >= 10 and self._analysis:
                    _analysis_tick = 0
                    snap = self._analysis.get_context_snapshot()
                    msg["analysis"] = {
                        "momentum_home": snap.momentum_home,
                        "momentum_away": snap.momentum_away,
                        "xg_home": snap.xg_home,
                        "xg_away": snap.xg_away,
                        "shots": [
                            {
                                "player": s.player, "team": s.team,
                                "position": list(s.position),
                                "xg": s.xg, "outcome": s.outcome,
                                "timestamp_sec": s.timestamp_sec,
                            }
                            for s in snap.shots
                        ],
                        "build_up_vectors": snap.build_up_vectors,
                        "dangerous_entries": snap.dangerous_entries,
                    }
                await self._broadcast(msg)
        except asyncio.CancelledError:
            pass

    async def _broadcast(self, payload: dict) -> None:
        if not self.clients:
            return
        message = json.dumps(payload)
        dead = set()
        for ws in self.clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.clients.discard(ws)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _extract_short_name(full_name: str) -> str:
    """Best-effort: return the most recognisable part of a player's name."""
    parts = full_name.strip().split()
    if len(parts) <= 1:
        return full_name
    # For compound surnames (e.g. "de Bruyne"), take last two parts
    # Heuristic: if second-to-last is lowercase (de/van/da/dos), take last two
    if len(parts) >= 3 and parts[-2].islower():
        return " ".join(parts[-2:])
    return parts[-1]


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

def _get_or_create_match_session(match_id: str) -> MatchSession:
    if match_id not in _sessions:
        session = MatchSession(match_id)
        _sessions[match_id] = session
        session.start()
    return _sessions[match_id]


@router.websocket("/ws/match")
async def ws_match(websocket: WebSocket, match_id: str = ""):
    await websocket.accept()
    if not match_id:
        await websocket.send_text(json.dumps({"type": "error", "message": "match_id required"}))
        await websocket.close()
        return

    try:
        session = _get_or_create_match_session(match_id)
    except FileNotFoundError as exc:
        await websocket.send_text(json.dumps({"type": "error", "message": str(exc)}))
        await websocket.close()
        return

    await session.add_client(websocket)

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                await session.handle_message(websocket, data)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error(f"WebSocket error: {exc}")
    finally:
        session.remove_client(websocket)
