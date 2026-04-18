#!/usr/bin/env python3
"""
debug/bench_models.py — Compare Ollama model generation speed and quality
for MatchCaster's flow-block commentary task.

Run from backend/:
  python debug/bench_models.py

Adjust MODELS list to test other candidates.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import time
import httpx

OLLAMA_URL = "http://localhost:11434"
MODELS = [
    "mistral:7b-instruct-q4_K_M",
    "gemma2:2b-instruct-q4_K_M",
    "qwen2.5:3b-instruct",
]
RUNS = 2  # runs per model (average)

# Representative flow-block system + user prompt (mirrors real usage)
SYSTEM = (
    "You are a live football commentator on TV. Given a list of events from the next ~15 seconds "
    "of play, write ONE flowing paragraph of live commentary narrating this period.\n"
    "Output ONLY the commentary text. No acknowledgements, preamble, or labels.\n\n"
    "RULES:\n"
    "- 2-3 natural, connected sentences. 20-25 words total maximum. Be concise.\n"
    "- Present tense. Active voice. Last names only.\n"
    "- Goals: PEAK energy. Red cards: punchy. Quiet play: narrate the rhythm.\n"
    "- NEVER mention coordinates, xG, or probability.\n"
    "- Output: plain text ONLY. No JSON, no labels, no markdown.\n"
)

USER = (
    "MATCH STATE:\n"
    "Score: Barcelona 1 - 0 Real Madrid | Minute: 34' | Phase: open_play\n"
    "Possession: Barcelona 61% / Real Madrid 39%\n"
    "Shots: Barcelona 5 (on target 3) | Real Madrid 3 (on target 1)\n\n"
    "EVENTS IN THIS 15-SECOND WINDOW:\n"
    "[Pass] Pedri (Barcelona) — left flank → central midfield (to: Gavi)\n"
    "[Dribble] Gavi (Barcelona) — central midfield (outcome: Complete)\n"
    "[Shot] Lewandowski (Barcelona) — penalty area (outcome: Saved)\n"
    "[Goal Keeper] Courtois (Real Madrid) — goal area (Shot Saved)\n\n"
    "Write your flowing commentary paragraph (plain text, 20-25 words max):"
)


async def call_model(model: str) -> tuple[str, float, int]:
    """Returns (text, elapsed_ms, token_count)."""
    payload = {
        "model": model,
        "system": SYSTEM,
        "prompt": USER,
        "stream": True,
        "options": {
            "temperature": 0.8,
            "num_predict": 50,
            "num_ctx": 2048,
            "num_thread": 4,
            "stop": ["\n\n", "###", "---"],
        },
    }
    tokens = []
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", f"{OLLAMA_URL}/api/generate", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except ValueError:
                    continue
                tok = chunk.get("response", "")
                if tok:
                    tokens.append(tok)
                if chunk.get("done"):
                    break
    elapsed = (time.monotonic() - t0) * 1000
    text = "".join(tokens).strip()
    return text, elapsed, len(tokens)


async def bench():
    # Check Ollama reachable
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            available = {m["name"] for m in r.json().get("models", [])}
    except Exception as e:
        print(f"❌  Ollama not reachable: {e}")
        return

    print(f"\n{'='*68}")
    print("  MatchCaster Model Benchmark — flow-block commentary task")
    print(f"{'='*68}\n")
    print(f"  Prompt: {len(SYSTEM.split()) + len(USER.split())} words total\n")

    results = []

    for model in MODELS:
        if model not in available:
            print(f"  ⚠  {model} not found — skipping (run: ollama pull {model})")
            continue

        print(f"  Model: {model}")
        run_times = []
        run_tokens = []
        last_text = ""

        for i in range(RUNS):
            print(f"    Run {i+1}/{RUNS} ... ", end="", flush=True)
            try:
                text, ms, ntok = await call_model(model)
                run_times.append(ms)
                run_tokens.append(ntok)
                last_text = text
                tps = ntok / (ms / 1000) if ms > 0 else 0
                print(f"{ms/1000:.1f}s  {ntok} tok  {tps:.1f} tok/s")
            except Exception as e:
                print(f"ERROR: {e}")

        if run_times:
            avg_ms = sum(run_times) / len(run_times)
            avg_tok = sum(run_tokens) / len(run_tokens)
            avg_tps = avg_tok / (avg_ms / 1000)
            results.append((model, avg_ms, avg_tps, last_text))
            print(f"    ─ avg: {avg_ms/1000:.1f}s  {avg_tps:.1f} tok/s")
            print(f"    Output: \"{last_text[:120]}\"")
        print()

    # Summary table
    if results:
        print(f"\n{'─'*68}")
        print(f"  {'Model':<40} {'Avg Time':>9} {'Tok/s':>7}  Fits 15s?")
        print(f"{'─'*68}")
        for model, avg_ms, tps, _ in sorted(results, key=lambda x: x[1]):
            fits = "✅" if avg_ms < 12000 else ("⚠ " if avg_ms < 20000 else "❌")
            print(f"  {model:<40} {avg_ms/1000:>7.1f}s  {tps:>5.1f}  {fits}")
        print(f"{'─'*68}")
        print("  Fits 15s? = generation finishes within the real-time block budget at 1×\n")

asyncio.run(bench())
