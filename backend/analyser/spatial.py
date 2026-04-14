# backend/analyser/spatial.py
# Convert StatsBomb (x, y) coordinates to natural language descriptions.
# StatsBomb pitch: 120 × 80. Origin bottom-left from attacking team's perspective.
# x = 0 (own goal) → 120 (opponent's goal)
# y = 0 (right side from attacking pov) → 80 (left side)

from __future__ import annotations


def coords_to_description(
    x: float,
    y: float,
    attacking_direction: str = "left_to_right",  # "left_to_right" or "right_to_left"
) -> str:
    """
    Convert StatsBomb coords to a natural language pitch location.

    Examples:
        (2, 40)   → "in their own defensive third"
        (60, 40)  → "in the centre of midfield"
        (110, 10) → "in the right side of the box"
        (118, 40) → "at the edge of the six-yard box"
        (95, 64)  → "in the left channel, approaching the box"
    """
    # Flip if team is attacking right-to-left
    if attacking_direction == "right_to_left":
        x = 120.0 - x
        y = 80.0 - y

    # ---- Lateral zone ----
    if y < 18:
        lateral = "on the right flank"
    elif y < 30:
        lateral = "on the right side"
    elif y < 50:
        lateral = "centrally"
    elif y < 62:
        lateral = "on the left side"
    else:
        lateral = "on the left flank"

    # ---- Depth zone ----
    if x < 18:
        depth = "deep in their own half"
        # Close to own goal line
        if x < 6:
            depth = "right in front of their own goal"
        lateral_override = None

        if y < 18 or y > 62:
            return f"deep on the {'right' if y < 40 else 'left'} touchline"
        return f"{depth}"

    elif x < 40:
        depth = "in their own defensive third"
    elif x < 60:
        depth = "in their own half"
    elif x < 80:
        depth = "in the centre of midfield"
    elif x < 92:
        depth = "in the attacking half"
    elif x < 102:
        # Approaching the box
        if y < 18 or y > 62:
            channel = "right" if y < 40 else "left"
            return f"in the {channel} channel, approaching the box"
        return "just outside the penalty area"
    elif x < 114:
        # Inside the box
        if y < 18:
            return "in the right side of the box"
        elif y > 62:
            return "in the left side of the box"
        elif y < 30:
            return "in the right side of the box"
        elif y > 50:
            return "in the left side of the box"
        else:
            return "inside the penalty area"
    else:
        # Six-yard box territory
        if 30 <= y <= 50:
            return "at the edge of the six-yard box"
        elif y < 30:
            return "at the near post on the right"
        else:
            return "at the near post on the left"

    return f"{lateral}, {depth}"


def coords_to_zone(x: float, y: float) -> str:
    """Return a short zone label for use in frontend/logging."""
    if x < 40:
        zone = "DEF"
    elif x < 80:
        zone = "MID"
    elif x < 102:
        zone = "ATT"
    else:
        zone = "BOX"

    if y < 26:
        side = "R"
    elif y > 54:
        side = "L"
    else:
        side = "C"

    return f"{zone}-{side}"


def pass_description(
    start: tuple[float, float],
    end: tuple[float, float],
    pass_type: str | None = None,
    is_cross: bool = False,
    is_through_ball: bool = False,
) -> str:
    """
    Produce a natural-language description of a pass from start to end.
    """
    start_desc = coords_to_description(*start)
    end_desc = coords_to_description(*end)

    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dist = (dx**2 + dy**2) ** 0.5

    if is_cross:
        return f"A cross from {start_desc} into {end_desc}"
    if is_through_ball:
        return f"A through ball from {start_desc} into {end_desc}"
    if dist > 40:
        return f"A long ball from {start_desc} to {end_desc}"
    if dist > 20:
        return f"A forward pass from {start_desc} to {end_desc}"
    return f"A short pass {start_desc}"
