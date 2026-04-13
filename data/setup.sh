#!/bin/bash
# data/setup.sh
# Download a selection of StatsBomb open-data matches for MatchCaster.
# Requires: git, curl

set -e

STATSBOMB_REPO="https://github.com/statsbomb/open-data.git"
TMP_DIR="/tmp/statsbomb-open-data"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== MatchCaster Data Setup ==="
echo "Cloning StatsBomb open-data (sparse)..."

# Sparse clone — only the events and lineups directories
if [ ! -d "$TMP_DIR" ]; then
  git clone --depth=1 --filter=blob:none --sparse "$STATSBOMB_REPO" "$TMP_DIR"
  cd "$TMP_DIR"
  git sparse-checkout set data/events data/lineups data/matches
else
  echo "StatsBomb data already cloned at $TMP_DIR"
  cd "$TMP_DIR"
  git pull --depth=1 origin main 2>/dev/null || true
fi

cd "$SCRIPT_DIR"
mkdir -p matches lineups

echo ""
echo "Copying selected matches..."

# -----------------------------------------------------------------------
# Curated match IDs — high-drama, lots of events, goals, tactical interest
# All from StatsBomb free open-data
# -----------------------------------------------------------------------

# La Liga 2015/16
MATCHES=(
  "69249"   # Barcelona vs Real Madrid (El Clasico)
  "69251"   # Real Madrid vs Atletico
)

# FIFA World Cup 2018 — available in full free tier
WC_MATCHES=(
  "7562"    # France vs Croatia (final) — if available
  "7559"    # Belgium vs France (semi)
)

# UEFA Euro 2020 — free in StatsBomb open data
EURO_MATCHES=(
  "3788741"  # England vs Germany
  "3788768"  # Italy vs Spain (semi)
  "3788769"  # Italy vs England (final)
)

# Combine all
ALL_MATCHES=("${MATCHES[@]}" "${WC_MATCHES[@]}" "${EURO_MATCHES[@]}")

FOUND=0
for match_id in "${ALL_MATCHES[@]}"; do
  src="$TMP_DIR/data/events/${match_id}.json"
  if [ -f "$src" ]; then
    cp "$src" "matches/${match_id}.json"
    echo "  ✓ Copied events: ${match_id}.json"
    FOUND=$((FOUND + 1))
  fi

  lineup_src="$TMP_DIR/data/lineups/${match_id}.json"
  if [ -f "$lineup_src" ]; then
    cp "$lineup_src" "lineups/${match_id}.json"
    echo "  ✓ Copied lineup: ${match_id}.json"
  fi
done

if [ "$FOUND" -eq 0 ]; then
  echo ""
  echo "WARNING: No known match IDs found. The StatsBomb data structure may have changed."
  echo "Copying any available events as fallback..."
  # Copy first 3 JSON files found in events
  COUNT=0
  for f in "$TMP_DIR/data/events/"*.json; do
    if [ $COUNT -ge 3 ]; then break; fi
    id=$(basename "$f" .json)
    cp "$f" "matches/"
    echo "  ✓ Copied events: ${id}.json"
    lineup="$TMP_DIR/data/lineups/${id}.json"
    [ -f "$lineup" ] && cp "$lineup" "lineups/"
    COUNT=$((COUNT + 1))
  done
fi

echo ""
echo "=== Done ==="
echo "Matches in data/matches/: $(ls matches/*.json 2>/dev/null | wc -l | tr -d ' ')"
echo "Lineups in data/lineups/: $(ls lineups/*.json 2>/dev/null | wc -l | tr -d ' ')"
echo ""
echo "Start the backend with: cd ../backend && uvicorn main:app --reload"
