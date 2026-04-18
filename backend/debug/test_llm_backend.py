#!/usr/bin/env python3
"""
debug/test_llm_backend.py — Test the active LLM backend (Groq or Ollama).

Shows exactly what input the production code sends and what it gets back,
including timing and token throughput. Works for both backends.

Run from backend/:
    # Groq (default — requires GROQ_API_KEY):
    export GROQ_API_KEY=gsk_...
    python3 debug/test_llm_backend.py

    # Ollama (local):
    LLM_BACKEND=local python3 debug/test_llm_backend.py

What it tests:
    Test 1 — Backend connectivity: can we reach the LLM at all?
    Test 2 — Short generation: minimal prompt, just verify output arrives.
    Test 3 — Real flow-block: exact payload the PBP agent sends in production.
    Test 4 — Real analyst:    exact payload the Analyst agent sends.
    Test 5 — Latency budget:  5 consecutive flow-block calls, timing distribution.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import time

# ── Init backend from environment ─────────────────────────────────────────────
from commentator.llm import init_backend, get_backend
from config import LLM_BACKEND, GROQ_MODEL, OLLAMA_MODEL, MAX_OUTPUT_TOKENS

init_backend()
BACKEND = get_backend()

# ── Real prompts (copied exactly from prompts.py production paths) ─────────────

FLOW_BLOCK_SYSTEM = """\
You are a live football commentator on TV. Given a list of events from the next ~15 seconds \
of play, write ONE flowing paragraph of live commentary narrating this period.
Output ONLY the commentary text. No acknowledgements, preamble, or labels.

RULES:
- 2-3 natural, connected sentences. 20-25 words total maximum. Be concise.
- Present tense. Active voice. Last names only.
- Goals: PEAK energy — "GOAL! [Player]!" then state score.
- NEVER mention coordinates, xG, or probability.
- Plain text ONLY. No JSON, labels, or markdown.

Be balanced and impartial. Report facts accurately without favouring either team."""

FLOW_BLOCK_USER = """\
RECENT COMMENTARY — do not repeat:
Pedri collects on the left and plays it inside. Real sit back, letting Barca circulate.

MATCH STATE:
Score: Barcelona 1 - 0 Real Madrid | Minute: 34' | Phase: open_play
Possession: Barcelona 61% / Real Madrid 39%
Shots: Barcelona 5 (on target 3) | Real Madrid 3 (on target 1)
Fouls: Barcelona 3 | Real Madrid 4

MATCH INFO:
La Liga 2010/11 | Camp Nou, Barcelona | Conditions: cool (8°C), calm

EVENTS IN THIS 15-SECOND WINDOW:
[Pass] Pedri (Barcelona) — left flank → central midfield (to: Gavi)
[Dribble] Gavi (Barcelona) — central midfield
[Shot] Lewandowski (Barcelona) — penalty area (outcome: Saved)
[Goal Keeper] Courtois (Real Madrid) — goal area

Write your flowing commentary paragraph (plain text, 20-25 words max):"""

ANALYST_SYSTEM = """\
You are a calm, authoritative football expert analyst — the co-commentator on live TV.
Output ONLY the commentary text. No acknowledgements, preamble, or labels.

YOUR ROLE:
- Provide MACRO analysis: momentum, tactical shifts, which team is dominating and why.
- 1-2 sentences maximum. Hard cap: 40 words total.
- Measured, authoritative tone. Never shout.
- NEVER describe individual moment-to-moment actions.

Be balanced and impartial."""

ANALYST_USER = """\
RECENT COMMENTARY — do not repeat:
Lewandowski fires — brilliant save from Courtois! The keeper denies him again.

MATCH STATE:
Score: Barcelona 1 - 0 Real Madrid | Minute: 34' | Phase: open_play
Possession: Barcelona 61% / Real Madrid 39%
Shots: Barcelona 5 (on target 3) | Real Madrid 3 (on target 1)

MATCH PICTURE (last 10 min):
Barcelona pressing high, winning the ball in Real's half repeatedly. Real Madrid's build-up is being disrupted.

TRIGGER: Give a macro insight on how the match is going right now.

Your expert insight (1-2 sentences, max 40 words, plain text only):"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def hr(char: str = "─", width: int = 70) -> str:
    return char * width


def count_words(text: str) -> int:
    return len(text.split())


def budget_icon(elapsed: float) -> str:
    if elapsed < 5:   return "✅ fast"
    if elapsed < 15:  return "✅ ok"
    if elapsed < 30:  return "⚠️  slow"
    return "❌ too slow"


def print_result(label: str, system: str, user: str, output: str, elapsed: float) -> None:
    sys_words  = count_words(system)
    user_words = count_words(user)
    out_words  = count_words(output)

    print(f"\n  ── Input ────────────────────────────────────────────────")
    print(f"  System  : {sys_words} words  ({len(system)} chars)")
    print(f"  User    : {user_words} words  ({len(user)} chars)")
    print(f"  Total   : {sys_words + user_words} words in  →  {out_words} words out")

    print(f"\n  ── Full system prompt ───────────────────────────────────")
    for line in system.splitlines():
        print(f"  {line}")

    print(f"\n  ── Full user prompt ─────────────────────────────────────")
    for line in user.splitlines():
        print(f"  {line}")

    print(f"\n  ── Raw output ───────────────────────────────────────────")
    print(f"  {output!r}")

    print(f"\n  ── Timing ───────────────────────────────────────────────")
    print(f"  Elapsed : {elapsed:.2f}s  →  {budget_icon(elapsed)}")
    print(f"  Words   : {out_words}  (target for flow-block: 20–25)")


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_1_connectivity() -> bool:
    print(f"\n{hr('═')}")
    print(f"  TEST 1 — Backend connectivity")
    print(hr('═'))
    print(f"  Backend : {BACKEND.name}")
    print(f"  Model   : {BACKEND.model_name}")
    print(f"  Warmup  : {'yes' if BACKEND.needs_warmup else 'no'}")

    if BACKEND.needs_warmup:
        print(f"\n  Running warmup...", end="", flush=True)
        t0 = time.monotonic()
        try:
            await BACKEND.warmup()
            elapsed = time.monotonic() - t0
            print(f" done in {elapsed:.1f}s")
        except Exception as exc:
            print(f" FAILED: {type(exc).__name__}: {exc}")
            return False

    print(f"\n  Sending minimal probe...", end="", flush=True)
    t0 = time.monotonic()
    try:
        out = await BACKEND.generate(
            system="Output exactly the word: ready",
            prompt="What is the word?",
            temperature=0.0,
            max_tokens=5,
        )
        elapsed = time.monotonic() - t0
        print(f" done in {elapsed:.2f}s")
        print(f"\n  Response : {out!r}")
        print(f"\n  ✅  {BACKEND.name} is reachable and responding.")
        return True
    except Exception as exc:
        elapsed = time.monotonic() - t0
        print(f" FAILED after {elapsed:.1f}s: {type(exc).__name__}: {exc}")
        if LLM_BACKEND == "groq":
            print("\n  Check that GROQ_API_KEY is set correctly.")
        else:
            print("\n  Check that Ollama is running: `ollama serve`")
        return False


async def test_2_short_generation() -> None:
    print(f"\n{hr('═')}")
    print("  TEST 2 — Short generation (low-stakes smoke test)")
    print(hr('═'))

    system = "You are a football commentator. Output ONLY the text, no preamble."
    user   = "Describe in exactly 10 words: a striker scoring a dramatic late winner."

    print(f"\n  System : {system!r}")
    print(f"  User   : {user!r}")
    print(f"\n  Generating...", end="", flush=True)

    t0 = time.monotonic()
    try:
        out = await BACKEND.generate(system=system, prompt=user, temperature=0.7, max_tokens=30)
        elapsed = time.monotonic() - t0
        print(f" done in {elapsed:.2f}s")
        print(f"\n  Output : {out!r}")
        print(f"  Words  : {count_words(out)}")
    except Exception as exc:
        elapsed = time.monotonic() - t0
        print(f" FAILED after {elapsed:.1f}s: {type(exc).__name__}: {exc}")


async def test_3_real_flow_block() -> None:
    print(f"\n{hr('═')}")
    print("  TEST 3 — Real flow-block (exact PBP agent payload)")
    print(hr('═'))
    print(f"  max_tokens={MAX_OUTPUT_TOKENS}  temperature=0.8")
    print(f"\n  Generating...", end="", flush=True)

    t0 = time.monotonic()
    try:
        out = await BACKEND.generate(
            system=FLOW_BLOCK_SYSTEM,
            prompt=FLOW_BLOCK_USER,
            temperature=0.8,
            max_tokens=MAX_OUTPUT_TOKENS,
        )
        elapsed = time.monotonic() - t0
        print(f" done in {elapsed:.2f}s")
        print_result("flow_block", FLOW_BLOCK_SYSTEM, FLOW_BLOCK_USER, out, elapsed)
    except Exception as exc:
        elapsed = time.monotonic() - t0
        print(f" FAILED after {elapsed:.1f}s: {type(exc).__name__}: {exc}")


async def test_4_real_analyst() -> None:
    print(f"\n{hr('═')}")
    print("  TEST 4 — Real analyst (exact Analyst agent payload)")
    print(hr('═'))
    print(f"  max_tokens={MAX_OUTPUT_TOKENS}  temperature=0.5")
    print(f"\n  Generating...", end="", flush=True)

    t0 = time.monotonic()
    try:
        out = await BACKEND.generate(
            system=ANALYST_SYSTEM,
            prompt=ANALYST_USER,
            temperature=0.5,
            max_tokens=MAX_OUTPUT_TOKENS,
        )
        elapsed = time.monotonic() - t0
        print(f" done in {elapsed:.2f}s")
        print_result("analyst", ANALYST_SYSTEM, ANALYST_USER, out, elapsed)
    except Exception as exc:
        elapsed = time.monotonic() - t0
        print(f" FAILED after {elapsed:.1f}s: {type(exc).__name__}: {exc}")


async def test_5_latency_budget() -> None:
    print(f"\n{hr('═')}")
    print("  TEST 5 — Latency budget: 5 consecutive flow-block calls")
    print(hr('═'))
    print("  A 15-second game window demands generation in <15s real time.")
    print("  With 4 blocks ahead (60s lookahead), <30s is still acceptable.")

    N = 5
    times: list[float] = []
    outputs: list[str] = []

    for i in range(1, N + 1):
        print(f"\n  Call {i}/{N}...", end="", flush=True)
        t0 = time.monotonic()
        try:
            out = await BACKEND.generate(
                system=FLOW_BLOCK_SYSTEM,
                prompt=FLOW_BLOCK_USER,
                temperature=0.8,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
            elapsed = time.monotonic() - t0
            times.append(elapsed)
            outputs.append(out)
            print(f" {elapsed:.2f}s  {budget_icon(elapsed)}  {count_words(out)} words")
        except Exception as exc:
            elapsed = time.monotonic() - t0
            times.append(elapsed)
            outputs.append("")
            print(f" FAILED after {elapsed:.1f}s: {type(exc).__name__}: {exc}")

    if times:
        print(f"\n  ── Summary ──────────────────────────────────────────────")
        print(f"  Min     : {min(times):.2f}s")
        print(f"  Max     : {max(times):.2f}s")
        print(f"  Mean    : {sum(times)/len(times):.2f}s")
        ok  = sum(1 for t in times if t < 15)
        meh = sum(1 for t in times if 15 <= t < 30)
        bad = sum(1 for t in times if t >= 30)
        print(f"  <15s    : {ok}/{N}  ✅")
        print(f"  15–30s  : {meh}/{N}  ⚠️")
        print(f"  ≥30s    : {bad}/{N}  ❌")
        mean = sum(times) / len(times)
        if mean < 15:
            verdict = "✅  Comfortable — real-time commentary should be gapless."
        elif mean < 25:
            verdict = "⚠️   Marginal — commentary may occasionally lag. Reduce speed to 0.5× if needed."
        else:
            verdict = "❌  Too slow — commentary will fall behind at 1× speed. Use Groq (./start.sh groq)."
        print(f"\n  Verdict : {verdict}")

        print(f"\n  ── Sample outputs ───────────────────────────────────────")
        for i, out in enumerate(outputs[:3], 1):
            print(f"  [{i}] {out!r}")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    print(f"\n{'═'*70}")
    print(f"  MatchCaster — LLM Backend Debug")
    print(f"  Backend : {BACKEND.name}  |  Model: {BACKEND.model_name}")
    print(f"  Mode    : LLM_BACKEND={LLM_BACKEND}")
    print(f"{'═'*70}")

    ok = await test_1_connectivity()
    if not ok:
        print("\n  Aborting — fix connectivity first.\n")
        return

    await test_2_short_generation()
    await test_3_real_flow_block()
    await test_4_real_analyst()
    await test_5_latency_budget()

    print(f"\n{hr('═')}")
    print("  Done.")
    print(f"  If Test 3 and Test 5 are consistently <15s → commentary will be gapless at 1×.")
    print(f"  If not → run with ./start.sh groq for cloud speed.")
    print(f"{'═'*70}\n")


asyncio.run(main())
