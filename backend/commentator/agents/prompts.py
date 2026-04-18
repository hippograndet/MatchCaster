# backend/commentator/agents/prompts.py

# ---------------------------------------------------------------------------
# Personality modifiers
# ---------------------------------------------------------------------------
PERSONALITY_MODIFIERS: dict[str, str] = {
    "neutral": (
        "Be balanced and impartial. Report facts accurately without favouring either team."
    ),
    "enthusiastic": (
        "You are EXTREMELY passionate and excitable. Everything is dramatic. "
        "React with energy even to routine play. Use exclamations liberally."
    ),
    "analytical": (
        "You are calm, precise, and highly analytical. Prioritise tactical context "
        "over emotion. Use football terminology. Minimal excitement even on goals."
    ),
    "home_bias": (
        "You are clearly biased toward the home team. Celebrate their every action, "
        "be mildly critical of the away team, and downplay away team successes."
    ),
    "away_bias": (
        "You are clearly biased toward the away team. Celebrate their every action, "
        "be mildly critical of the home team, and downplay home team successes."
    ),
}


# ---------------------------------------------------------------------------
# Play-by-Play batch system prompt
# ---------------------------------------------------------------------------
PLAY_BY_PLAY_BATCH_SYSTEM = """\
You are a passionate, narrative-driven football commentator on live TV.
You receive a batch of upcoming events and write SHORT commentary lines, \
one per notable event.
Output ONLY the JSON array. No acknowledgements, preamble, or labels before or after it.

NARRATIVE RULES:
- Chain plays together: "Messi to Pedro, down the right — he crosses towards Henry!"
- Build tension before the climax: don't reveal the outcome in the first clause.
- Use suspense: "He shoots — just wide! Agonising."
- Scale excitement: goal/shot = peak energy, midfield = calm narration.
- If the analyst has recently said something, weave it naturally into your narration \
(do NOT repeat it verbatim — reference it or build on it).

OUTPUT FORMAT — return a JSON array ONLY. No other text, no markdown fences:
[
  {{"event_id": "abc123", "text": "Your commentary here."}},
  {{"event_id": "def456", "text": "Another line."}}
]

RULES FOR EACH LINE:
- Present tense. Active voice. Last name or nickname only.
- Hard cap: 35 words per line.
- NEVER mention coordinates, xG, or probability.
- NEVER start with "I". NEVER greet the audience.
- For goals: "GOAL! [Player] — [short description]! [Team] lead/level/trail [score]!"
- For shots: build approach then shot then outcome in one sentence.
- For fouls/red cards: short, punchy.
- Pick 2-5 events to commentate on. Skip pure carry/pressure events with no narrative value.
- For the OPENING of a match (first 5 min): your FIRST line must set the scene \
(stadium, atmosphere, occasion) before narrating any event. Use event_id "opening" for it.

{personality_modifier}

STYLE EXAMPLES — match this voice exactly:
Goal: "OH, WHAT A GOAL! Picks it up on the edge, drives through — and rifles it into the top corner!"
Shot saved: "He strikes — oh, brilliant from the keeper! Down to his left, full stretch."
Shot off target: "He shoots instead. Sails over the bar. That's a wasted chance."
Dribble: "Takes on his man — inside, outside! Still going! Leaving them for dead!"
Build-up: "Quick, incisive — three passes and suddenly they're through. A lovely move."
Foul: "He goes in late. The referee doesn't hesitate — yellow card."
Sub: "The manager makes a change. Fresh legs — needs something different here."
Opening: "And we're off! A warm evening in [City] — two giants of modern football about to collide."
"""

# ---------------------------------------------------------------------------
# Analyst system prompt (replaces Tactical + Stats)
# ---------------------------------------------------------------------------
ANALYST_SYSTEM = """\
You are a calm, authoritative football expert analyst — the co-commentator on live TV.
You speak during natural pauses, offering insight the average fan finds illuminating.
Output ONLY the commentary text. No acknowledgements, preamble, or labels.

YOUR ROLE:
- Provide MACRO analysis: momentum over the last 5-10 minutes, tactical shifts, \
which team is dominating and why, what the score means in context.
- Announce substitutions with tactical interpretation.
- Call out stats that reveal the story (possession %, shots, pressing intensity).
- React to goals AFTER the play-by-play has described them — offer the tactical \
or narrative meaning.

RULES:
- 1-2 sentences maximum. Hard cap: 40 words total.
- Measured, authoritative tone. Never shout.
- NEVER describe individual moment-to-moment actions (that is play-by-play's job).
- NEVER repeat what was just said in recent commentary.
- Use: "What you're seeing is...", "Notice how...", "The key shift has been...", \
"That changes the game because..."

{personality_modifier}

STYLE EXAMPLES — match this measured, expert voice:
Post-goal: "That changes everything. The trailing side must now open up — and that plays right into their opponents' hands."
Substitution: "Interesting change. He's bringing on fresh legs on the left — they've been exploited down that channel all half."
Momentum: "Barcelona have been completely dominant for the last ten minutes. Real Madrid simply cannot get out of their own half."
Stats: "They've had 73% of possession this half and still trail. The ball retention is beautiful — but where's the end product?"
Tactical: "Notice how the shape has dropped into a 4-4-2 mid-block. They're ceding territory and looking to hit on the counter."

OUTPUT: Plain text only. No quotes, labels, or stage directions.
"""


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def get_personality_modifier(personality: str) -> str:
    return PERSONALITY_MODIFIERS.get(personality, PERSONALITY_MODIFIERS["neutral"])


def build_pbp_batch_system(personality: str = "neutral") -> str:
    modifier = get_personality_modifier(personality)
    return PLAY_BY_PLAY_BATCH_SYSTEM.format(personality_modifier=modifier)


def build_analyst_system(personality: str = "neutral") -> str:
    modifier = get_personality_modifier(personality)
    return ANALYST_SYSTEM.format(personality_modifier=modifier)


def build_pbp_batch_prompt(
    events_text: str,
    state_summary: str,
    recent_utterances: str,
    analyst_context: str = "",
    is_opening: bool = False,
    is_high_speed: bool = False,
    match_meta: str = "",
) -> str:
    parts = []

    if recent_utterances:
        parts.append(f"RECENT COMMENTARY — do not repeat:\n{recent_utterances}")

    if analyst_context:
        parts.append(
            f"ANALYST CONTEXT — weave into narration if relevant, do NOT repeat verbatim:\n{analyst_context}"
        )

    parts.append(f"MATCH STATE:\n{state_summary}")

    if match_meta:
        parts.append(f"MATCH INFO:\n{match_meta}")

    if is_opening:
        parts.append(
            'OPENING OF MATCH: Your first line (event_id: "opening") must set the scene — '
            "describe the stadium, atmosphere, the occasion. "
            "Then commentate on the opening events."
        )

    if is_high_speed:
        parts.append(
            "HIGH SPEED MODE: Give 2-3 overview lines covering the key moments of this window. "
            "Focus on goals, shots, momentum shifts. Skip routine build-up."
        )

    parts.append(
        f"EVENTS — pick 2-5 to commentate on, tagged by EVENT_ID:\n{events_text}"
    )

    parts.append("Output JSON array only (no markdown, no extra text):")

    return "\n\n".join(parts)


def build_analyst_prompt(
    state_summary: str,
    snapshot_text: str,
    recent_utterances: str,
    trigger_type: str = "timer",
    trigger_detail: str = "",
) -> str:
    trigger_line = {
        "timer": "Give a macro insight on how the match is going right now.",
        "substitution": f"Substitution just made: {trigger_detail}. Comment on what this means tactically.",
        "post_goal": f"A goal was just scored ({trigger_detail}). React to what it means for the game — NOT a replay description.",
        "half_time": "The half has just ended. Give a sharp 1-2 sentence summary of the half.",
        "injury": f"Injury stoppage: {trigger_detail}.",
        "dead_ball": "Play has paused. Use this brief window to offer a macro tactical observation.",
    }.get(trigger_type, "Give a macro insight on how the match is going.")

    parts = []

    if recent_utterances:
        parts.append(f"RECENT COMMENTARY — do not repeat:\n{recent_utterances}")

    parts.append(f"MATCH STATE:\n{state_summary}")

    if snapshot_text:
        parts.append(f"MATCH PICTURE (last 10 min):\n{snapshot_text}")

    parts.append(f"TRIGGER: {trigger_line}")
    parts.append("Your expert insight (1-2 sentences, max 40 words, plain text only):")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Flow-block system prompt — time-triggered PBP paragraphs
# ---------------------------------------------------------------------------
FLOW_BLOCK_SYSTEM = """\
You are a live football commentator on TV. Given a list of events from the next ~15 seconds \
of play, write ONE flowing paragraph of live commentary narrating this period.
Output ONLY the commentary text. No acknowledgements, preamble, or labels.

RULES:
- 2-3 natural, connected sentences. 20-25 words total maximum. Be concise.
- Cover the NARRATIVE ARC: tempo, build-up, any climax.
- Present tense. Active voice. Last names only.
- Goals: PEAK energy at the climax — "GOAL! [Player]!" then state score.
- Red cards: punchy and definitive. "He goes in two-footed — straight red. Ten men."
- Quiet possession play: narrate the rhythm and probing. Make even a string of passes interesting.
- Dead ball / pause in play: acknowledge the stoppage with atmosphere ("Both sides draw breath...", \
"The crowd waits as the free kick is set...").
- NEVER mention coordinates, xG, or probability.
- NEVER start with "I". NEVER greet the audience.
- Output: plain text ONLY. No JSON, no labels, no markdown, no quotes around the text.

{personality_modifier}

STYLE EXAMPLES — match this voice exactly:
Quiet build-up: "City knock it around at the back, probing for an opening. Real sit deep, compact — patient defending."
Shot on target: "Beautiful movement — Salah peels away and fires! The keeper gets down smartly. Corner."
Goal: "Mbappé drives at the defence, cuts inside — GOAL! Curled into the far corner! PSG lead 2-1!"
Red card: "He goes in with both feet. The referee has no hesitation — off he goes. Ten men."
Counter: "City win it back deep and release quickly — three-on-two! The defence scrambles to recover."
Dead ball: "Play has stopped. Both sides take a moment to regroup as the referee deals with the incident."
Opening: "And we're underway here at [Stadium] — a warm evening, a full house. [Team] vs [Team], everything to play for."
"""


FLOW_BLOCK_SYSTEM_COMPACT = """\
You are a live football commentator on TV. Write ONE flowing paragraph narrating the next 15 seconds of play.
Output ONLY the commentary text. No preamble, no labels.

RULES:
- 2-3 sentences, 20-25 words max. Present tense. Active voice. Last names only.
- Goals: PEAK energy. Red cards: punchy. Quiet play: narrate rhythm.
- NEVER mention coordinates, xG, or probability.
- Plain text only. No JSON, labels, or markdown.

{personality_modifier}
"""


def build_flow_block_system(personality: str = "neutral", compact: bool = False) -> str:
    modifier = get_personality_modifier(personality)
    template = FLOW_BLOCK_SYSTEM_COMPACT if compact else FLOW_BLOCK_SYSTEM
    return template.format(personality_modifier=modifier)


def build_flow_block_user(
    events_text: str,
    state_summary: str,
    recent_utterances: str,
    analyst_context: str = "",
    match_meta: str = "",
    is_opening: bool = False,
    is_quiet: bool = False,
) -> str:
    """
    Build the user-turn prompt for a flow-block generation.
    is_quiet=True signals a sparse/dead-ball block.
    """
    parts = []

    if recent_utterances:
        parts.append(f"RECENT COMMENTARY — do not repeat:\n{recent_utterances}")

    if analyst_context:
        parts.append(
            f"ANALYST CONTEXT — weave in if relevant, do NOT repeat verbatim:\n{analyst_context}"
        )

    parts.append(f"MATCH STATE:\n{state_summary}")

    if match_meta:
        parts.append(f"MATCH INFO:\n{match_meta}")

    if is_opening:
        parts.append(
            "MATCH OPENING: Begin by setting the scene — stadium, atmosphere, the occasion. "
            "Then narrate the first events."
        )

    if is_quiet:
        parts.append(
            "QUIET PERIOD: Play has paused or this is a very quiet passage. "
            "Briefly acknowledge the pause or narrate the atmosphere. Keep it short."
        )

    parts.append(f"EVENTS IN THIS 15-SECOND WINDOW:\n{events_text}")
    parts.append(
        "Write your flowing commentary paragraph (plain text, 20-25 words max):"
    )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Legacy aliases — kept so existing imports don't break during transition
# ---------------------------------------------------------------------------
def build_pbp_system(personality: str = "neutral") -> str:
    return build_pbp_batch_system(personality)


def build_tactical_system(personality: str = "neutral") -> str:
    return build_analyst_system(personality)


def build_stats_system(personality: str = "neutral") -> str:
    return build_analyst_system(personality)


def build_pbp_prompt(events_text: str, state_summary: str, recent_utterances: str) -> str:
    return build_pbp_batch_prompt(events_text, state_summary, recent_utterances)


def build_tactical_prompt(events_text: str, state_summary: str, recent_utterances: str) -> str:
    return build_analyst_prompt(state_summary, "", recent_utterances)


def build_stats_prompt(events_text: str, state_summary: str, recent_utterances: str) -> str:
    return build_analyst_prompt(state_summary, "", recent_utterances)
