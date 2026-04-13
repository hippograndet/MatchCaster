# backend/enrichment/team_colors.py
# Hardcoded primary/secondary colors for teams in StatsBomb open data.
# Format: "Team Name" → {"primary": "#hex", "secondary": "#hex"}

TEAM_COLORS: dict[str, dict[str, str]] = {
    # --- UEFA Euro 2020 ---
    "Italy":          {"primary": "#003DA5", "secondary": "#FFFFFF"},
    "Turkey":         {"primary": "#E30A17", "secondary": "#FFFFFF"},
    "Belgium":        {"primary": "#1E1E1E", "secondary": "#E30A17"},
    "Finland":        {"primary": "#FFFFFF", "secondary": "#003580"},
    "Denmark":        {"primary": "#C60C30", "secondary": "#FFFFFF"},
    "Russia":         {"primary": "#FFFFFF", "secondary": "#003DA5"},

    # --- FIFA World Cup 2018 ---
    "Egypt":          {"primary": "#CC0000", "secondary": "#FFFFFF"},
    "Saudi Arabia":   {"primary": "#006C35", "secondary": "#FFFFFF"},
    "Australia":      {"primary": "#FFDE00", "secondary": "#003DA5"},
    "Peru":           {"primary": "#D91023", "secondary": "#FFFFFF"},

    # --- La Liga (StatsBomb free) ---
    "Barcelona":      {"primary": "#A50044", "secondary": "#004D98"},
    "Real Madrid":    {"primary": "#FFFFFF", "secondary": "#FEBE10"},
    "Valencia":       {"primary": "#FFFFFF", "secondary": "#FF7C00"},
    "Atlético Madrid":{"primary": "#CE3524", "secondary": "#273E8A"},
    "Sevilla":        {"primary": "#FFFFFF", "secondary": "#D4000D"},
    "Villarreal":     {"primary": "#FFED00", "secondary": "#005C8B"},
    "Athletic Club":  {"primary": "#EE2523", "secondary": "#FFFFFF"},

    # --- Premier League (StatsBomb free) ---
    "Arsenal":        {"primary": "#EF0107", "secondary": "#FFFFFF"},
    "Chelsea":        {"primary": "#034694", "secondary": "#FFFFFF"},
    "Liverpool":      {"primary": "#C8102E", "secondary": "#F6EB61"},
    "Manchester City":{"primary": "#6CABDD", "secondary": "#FFFFFF"},
    "Manchester United":{"primary":"#DA291C", "secondary": "#FBE122"},
    "Tottenham Hotspur":{"primary":"#132257","secondary":"#FFFFFF"},
    "Leicester City": {"primary": "#003090", "secondary": "#FDBE11"},

    # --- Champions League / International ---
    "France":         {"primary": "#002395", "secondary": "#ED2939"},
    "Germany":        {"primary": "#000000", "secondary": "#D00027"},
    "Spain":          {"primary": "#AA151B", "secondary": "#F1BF00"},
    "England":        {"primary": "#FFFFFF", "secondary": "#CF081F"},
    "Portugal":       {"primary": "#006600", "secondary": "#CC0000"},
    "Netherlands":    {"primary": "#FF4F00", "secondary": "#FFFFFF"},
    "Brazil":         {"primary": "#009C3B", "secondary": "#FFDF00"},
    "Argentina":      {"primary": "#74ACDF", "secondary": "#FFFFFF"},
    "Croatia":        {"primary": "#FF0000", "secondary": "#FFFFFF"},
    "Uruguay":        {"primary": "#5EB6E4", "secondary": "#FFFFFF"},
    "Mexico":         {"primary": "#006847", "secondary": "#CE1126"},
    "Japan":          {"primary": "#003DA5", "secondary": "#BC002D"},
    "South Korea":    {"primary": "#003DA5", "secondary": "#CD2E3A"},
    "Morocco":        {"primary": "#C1272D", "secondary": "#006233"},
    "Senegal":        {"primary": "#00853F", "secondary": "#FDEF42"},
    "USA":            {"primary": "#002868", "secondary": "#BF0A30"},
    "Switzerland":    {"primary": "#FF0000", "secondary": "#FFFFFF"},
    "Sweden":         {"primary": "#006AA7", "secondary": "#FECC02"},
    "Poland":         {"primary": "#FFFFFF", "secondary": "#DC143C"},
    "Colombia":       {"primary": "#FCD116", "secondary": "#003087"},
    "Serbia":         {"primary": "#C6363C", "secondary": "#0C4076"},
}


def get_team_colors(team_name: str) -> dict[str, str]:
    """Return primary/secondary colors for a team, with a sensible fallback."""
    return TEAM_COLORS.get(team_name, {"primary": "#888888", "secondary": "#FFFFFF"})
