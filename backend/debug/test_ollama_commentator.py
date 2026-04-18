#!/usr/bin/env python3
"""
debug/test_ollama_commentator.py — Diagnose Ollama generation speed and quality
for MatchCaster's flow-block commentary task.

Sends EXACTLY the same payload as _call_ollama() does in production, so you can
see token throughput, timing, and raw output before wiring into the real app.

Run from backend/:
    python3 debug/test_ollama_commentator.py

What it tests:
    Test 1 — Minimal warmup probe: does Ollama respond at all?
    Test 2 — Warmup with real options (num_ctx=2048, num_thread=4): primes KV cache
    Test 3 — Real flow-block call (matches _call_ollama exactly): measures real speed
    Test 4 — Prompt token count: how large is the prompt we're actually sending?
    Test 5 — Options sweep: does changing num_ctx or num_predict help?
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import time
import httpx

# ── Config (must match config.py) ────────────────────────────────────────────
OLLAMA_URL  = "http://localhost:11434"
MODEL       = "gemma2:2b-instruct-q4_K_M"   # change if you switched models
TIMEOUT_SEC = 120.0                           # generous — we want to see how long it ACTUALLY takes
NUM_CTX     = 2048
NUM_THREAD  = 4
NUM_PREDICT = 50
TEMPERATURE = 0.8

# ── Real prompts (copied from prompts.py) ─────────────────────────────────────
SYSTEM_PROMPT = """\
You are a live football commentator on TV. Given a list of events from the next ~15 seconds \
of play, write ONE flowing paragraph of live commentary narrating this period.
Output ONLY the commentary text. No acknowledgements, preamble, or labels.

RULES:
- 2-3 natural, connected sentences. 20-25 words total maximum. Be concise.
- Cover the NARRATIVE ARC: tempo, build-up, any climax.
- Present tense. Active voice. Last names only.
- Goals: PEAK energy at the climax — "GOAL! [Player]!" then state score.
- Red cards: punchy and definitive. "He goes in two-footed — straight red. Ten men."
- Quiet possession play: narrate the rhythm and probing.
- NEVER mention coordinates, xG, or probability.
- NEVER start with "I". NEVER greet the audience.
- Output: plain text ONLY. No JSON, no labels, no markdown, no quotes around the text.

Be balanced and impartial. Report facts accurately without favouring either team.

STYLE EXAMPLES — match this voice exactly:
Quiet build-up: "City knock it around at the back, probing for an opening. Real sit deep, compact — patient defending."
Shot on target: "Beautiful movement — Salah peels away and fires! The keeper gets down smartly. Corner."
Goal: "Mbappé drives at the defence, cuts inside — GOAL! Curled into the far corner! PSG lead 2-1!"
"""

USER_PROMPT = """\
MATCH STATE:
Score: Barcelona 1 - 0 Real Madrid | Minute: 34' | Phase: open_play
Possession: Barcelona 61% / Real Madrid 39%
Shots: Barcelona 5 (on target 3) | Real Madrid 3 (on target 1)
Fouls: Barcelona 3 | Real Madrid 4

MATCH INFO:
La Liga 2010/11 | Camp Nou, Barcelona | Conditions: cool (8°C), calm

EVENTS IN THIS 15-SECOND WINDOW:
[Pass] Pedri (Barcelona) — left flank → central midfield (to: Gavi)
[Dribble] Gavi (Barcelona) — central midfield (outcome: Complete)
[Shot] Lewandowski (Barcelona) — penalty area (outcome: Saved)
[Goal Keeper] Courtois (Real Madrid) — goal area (Shot Saved)

Write your flowing commentary paragraph (plain text, 20-25 words max):"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def count_words(text: str) -> int:
    return len(text.split())


def hr(char: str = "─", width: int = 70) -> str:
    return char * width


async def check_ollama() -> set[str]:
    """Return set of available model names, or empty set if unreachable."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            return {m["name"] for m in r.json().get("models", [])}
    except Exception as e:
        print(f"\n❌  Cannot reach Ollama at {OLLAMA_URL}: {e}")
        print("    Make sure Ollama is running: `ollama serve`")
        return set()


async def raw_generate(
    prompt: str,
    system: str = "",
    options: dict | None = None,
    stream: bool = True,
    label: str = "call",
) -> tuple[str, float, int, float]:
    """
    POST to Ollama /api/generate.
    Returns (text, elapsed_sec, token_count, time_to_first_token_sec).
    Prints live token stream.
    """
    if options is None:
        options = {}

    payload: dict = {
        "model": MODEL,
        "prompt": prompt,
        "stream": stream,
        "options": options,
    }
    if system:
        payload["system"] = system

    # Show exact payload (without full prompts — shown separately)
    print(f"\n  Payload options: {json.dumps(options)}")
    print(f"  stream={stream}")

    tokens: list[str] = []
    t0 = time.monotonic()
    t_first: float = 0.0

    async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
        if stream:
            async with client.stream("POST", f"{OLLAMA_URL}/api/generate", json=payload) as resp:
                resp.raise_for_status()
                print(f"\n  ── Raw output ──────────────────────────────────────────")
                print("  ", end="", flush=True)
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue
                    tok = chunk.get("response", "")
                    if tok:
                        if not t_first:
                            t_first = time.monotonic() - t0
                        tokens.append(tok)
                        print(tok, end="", flush=True)
                    if chunk.get("done") or len(tokens) >= NUM_PREDICT:
                        break
                print()  # newline after stream
        else:
            resp = await client.post(f"{OLLAMA_URL}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            text = data.get("response", "")
            tokens = list(text)
            t_first = time.monotonic() - t0
            print(f"\n  ── Raw output ──────────────────────────────────────────")
            print(f"  {text}")

    elapsed = time.monotonic() - t0
    return "".join(tokens).strip(), elapsed, len(tokens), t_first


def print_timing(elapsed: float, ntok: int, t_first: float) -> None:
    tps = ntok / elapsed if elapsed > 0 else 0
    budget_ok = "✅" if elapsed < 15 else ("⚠️ " if elapsed < 30 else "❌")
    print(f"\n  ── Timing ──────────────────────────────────────────────")
    print(f"  Time to first token : {t_first:.2f}s")
    print(f"  Total elapsed       : {elapsed:.1f}s")
    print(f"  Tokens generated    : {ntok}")
    print(f"  Throughput          : {tps:.1f} tok/s")
    print(f"  Fits 15s budget?    : {budget_ok} ({'yes' if elapsed < 15 else 'no — too slow'})")


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_1_minimal_warmup() -> None:
    """Minimal call — exactly like the OLD warmup (no num_ctx)."""
    print(f"\n{hr('═')}")
    print("  TEST 1 — Minimal warmup probe (old style, no num_ctx)")
    print(hr('═'))
    print("  Prompt: 'Ready.'  |  stream=False  |  options: {num_predict: 1}")

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(f"{OLLAMA_URL}/api/generate", json={
                "model": MODEL,
                "prompt": "Ready.",
                "stream": False,
                "options": {"num_predict": 1},
            })
        elapsed = time.monotonic() - t0
        resp_tok = r.json().get("response", "")
        print(f"\n  Response: {resp_tok!r}")
        print(f"  Time    : {elapsed:.2f}s")
        print(f"  → {'✅ Fast warmup' if elapsed < 5 else '⚠️  Slow warmup — model may have been unloaded'}")
    except Exception as e:
        print(f"\n  ❌ Error: {type(e).__name__}: {e}")


async def test_2_real_warmup() -> None:
    """Warmup with num_ctx=2048, num_thread=4 — the NEW warmup."""
    print(f"\n{hr('═')}")
    print("  TEST 2 — Warmup with real options (new style)")
    print(hr('═'))
    print("  Prompt: 'Ready.'  |  stream=False  |  options: {num_predict:1, num_ctx:2048, num_thread:4}")

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(f"{OLLAMA_URL}/api/generate", json={
                "model": MODEL,
                "prompt": "Ready.",
                "stream": False,
                "options": {"num_predict": 1, "num_ctx": NUM_CTX, "num_thread": NUM_THREAD},
            })
        elapsed = time.monotonic() - t0
        resp_tok = r.json().get("response", "")
        print(f"\n  Response: {resp_tok!r}")
        print(f"  Time    : {elapsed:.2f}s")
        print(f"  → {'✅ Fast' if elapsed < 5 else f'⚠️  {elapsed:.1f}s — context alloc was slow'}")
    except Exception as e:
        print(f"\n  ❌ Error: {type(e).__name__}: {e}")


async def test_3_real_flow_block() -> None:
    """Exact replica of _call_ollama() — what the app actually sends."""
    print(f"\n{hr('═')}")
    print("  TEST 3 — Real flow-block call (EXACT _call_ollama payload)")
    print(hr('═'))

    sys_words  = count_words(SYSTEM_PROMPT)
    user_words = count_words(USER_PROMPT)
    print(f"\n  System prompt : {sys_words} words  ({len(SYSTEM_PROMPT)} chars)")
    print(f"  User prompt   : {user_words} words  ({len(USER_PROMPT)} chars)")
    print(f"  Total         : {sys_words + user_words} words")
    print(f"\n  ── System prompt ───────────────────────────────────────")
    for line in SYSTEM_PROMPT.splitlines():
        print(f"  {line}")
    print(f"\n  ── User prompt ─────────────────────────────────────────")
    for line in USER_PROMPT.splitlines():
        print(f"  {line}")

    options = {
        "temperature": TEMPERATURE,
        "num_predict": NUM_PREDICT,
        "num_ctx": NUM_CTX,
        "num_thread": NUM_THREAD,
        "stop": ["\n\n", "###", "---"],
    }

    try:
        text, elapsed, ntok, t_first = await raw_generate(
            prompt=USER_PROMPT,
            system=SYSTEM_PROMPT,
            options=options,
            stream=True,
            label="flow_block",
        )
        print_timing(elapsed, ntok, t_first)
        words = count_words(text)
        print(f"  Output words  : {words}  (target: 20–25)")
    except Exception as e:
        print(f"\n  ❌ Error: {type(e).__name__}: {e}")


async def test_4_options_sweep() -> None:
    """Run the same prompt with different num_ctx values to find the sweet spot."""
    print(f"\n{hr('═')}")
    print("  TEST 4 — num_ctx sweep (same prompt, different context window)")
    print(hr('═'))

    configs = [
        ("num_ctx=512",  {"num_predict": NUM_PREDICT, "num_ctx": 512,  "num_thread": NUM_THREAD, "temperature": TEMPERATURE}),
        ("num_ctx=1024", {"num_predict": NUM_PREDICT, "num_ctx": 1024, "num_thread": NUM_THREAD, "temperature": TEMPERATURE}),
        ("num_ctx=2048", {"num_predict": NUM_PREDICT, "num_ctx": 2048, "num_thread": NUM_THREAD, "temperature": TEMPERATURE}),
    ]

    results = []
    for label, opts in configs:
        print(f"\n  [{label}]", end="", flush=True)
        t0 = time.monotonic()
        try:
            tokens: list[str] = []
            t_first = 0.0
            async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as c:
                async with c.stream("POST", f"{OLLAMA_URL}/api/generate", json={
                    "model": MODEL,
                    "system": SYSTEM_PROMPT,
                    "prompt": USER_PROMPT,
                    "stream": True,
                    "options": opts,
                }) as resp:
                    resp.raise_for_status()
                    print(" generating...", end="", flush=True)
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except ValueError:
                            continue
                        tok = chunk.get("response", "")
                        if tok:
                            if not t_first:
                                t_first = time.monotonic() - t0
                            tokens.append(tok)
                        if chunk.get("done") or len(tokens) >= NUM_PREDICT:
                            break
            elapsed = time.monotonic() - t0
            tps = len(tokens) / elapsed if elapsed > 0 else 0
            results.append((label, elapsed, tps, t_first, "".join(tokens).strip()))
            fits = "✅" if elapsed < 15 else ("⚠️ " if elapsed < 30 else "❌")
            print(f" done  {elapsed:.1f}s  {tps:.1f} tok/s  TTFT={t_first:.2f}s  {fits}")
        except Exception as e:
            elapsed = time.monotonic() - t0
            print(f" ERROR after {elapsed:.1f}s: {type(e).__name__}: {e}")

    print(f"\n  ── Summary ─────────────────────────────────────────────")
    print(f"  {'Config':<15} {'Time':>8} {'tok/s':>7} {'TTFT':>7}  Output (first 80 chars)")
    print(f"  {'─'*15} {'─'*8} {'─'*7} {'─'*7}  {'─'*40}")
    for label, elapsed, tps, t_first, text in results:
        fits = "✅" if elapsed < 15 else ("⚠️ " if elapsed < 30 else "❌")
        print(f"  {label:<15} {elapsed:>7.1f}s {tps:>6.1f}  {t_first:>6.2f}s  {text[:80]!r}")


async def test_5_thread_sweep() -> None:
    """Same prompt, vary num_thread to find CPU optimum."""
    print(f"\n{hr('═')}")
    print("  TEST 5 — num_thread sweep (find CPU optimum)")
    print(hr('═'))

    configs = [
        ("num_thread=1", {"num_predict": NUM_PREDICT, "num_ctx": NUM_CTX, "num_thread": 1, "temperature": TEMPERATURE}),
        ("num_thread=2", {"num_predict": NUM_PREDICT, "num_ctx": NUM_CTX, "num_thread": 2, "temperature": TEMPERATURE}),
        ("num_thread=4", {"num_predict": NUM_PREDICT, "num_ctx": NUM_CTX, "num_thread": 4, "temperature": TEMPERATURE}),
    ]

    results = []
    for label, opts in configs:
        print(f"\n  [{label}]", end="", flush=True)
        t0 = time.monotonic()
        try:
            tokens: list[str] = []
            async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as c:
                async with c.stream("POST", f"{OLLAMA_URL}/api/generate", json={
                    "model": MODEL,
                    "system": SYSTEM_PROMPT,
                    "prompt": USER_PROMPT,
                    "stream": True,
                    "options": opts,
                }) as resp:
                    resp.raise_for_status()
                    print(" generating...", end="", flush=True)
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
                        if chunk.get("done") or len(tokens) >= NUM_PREDICT:
                            break
            elapsed = time.monotonic() - t0
            tps = len(tokens) / elapsed if elapsed > 0 else 0
            results.append((label, elapsed, tps))
            print(f" done  {elapsed:.1f}s  {tps:.1f} tok/s")
        except Exception as e:
            elapsed = time.monotonic() - t0
            print(f" ERROR after {elapsed:.1f}s: {type(e).__name__}: {e}")

    print(f"\n  ── Summary ─────────────────────────────────────────────")
    best = min(results, key=lambda x: x[1]) if results else None
    for label, elapsed, tps in results:
        marker = " ← best" if best and label == best[0] else ""
        print(f"  {label:<15} {elapsed:>7.1f}s  {tps:>5.1f} tok/s{marker}")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    print(f"\n{'═'*70}")
    print("  MatchCaster — Ollama Commentator Debug")
    print(f"  Model: {MODEL}  |  URL: {OLLAMA_URL}")
    print(f"{'═'*70}")

    available = await check_ollama()
    if not available:
        return

    if MODEL not in available:
        print(f"\n  ⚠️  Model '{MODEL}' not found.")
        print(f"  Available models: {', '.join(sorted(available))}")
        print(f"  Run: ollama pull {MODEL}")
        return

    print(f"\n  ✅  Ollama reachable. Model '{MODEL}' available.")

    # Run tests sequentially so we can observe model warm/cold state transitions
    await test_1_minimal_warmup()
    await test_2_real_warmup()
    await test_3_real_flow_block()
    await test_4_options_sweep()
    await test_5_thread_sweep()

    print(f"\n{hr('═')}")
    print("  Done. Key question: is Test 3 generating in <20s?")
    print("  If not, the block budget (15s real + 60s lookahead) will still be exceeded.")
    print(f"{'═'*70}\n")


asyncio.run(main())
