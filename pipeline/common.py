"""Shared constants + helpers for the ECHL Rookie Dev Model pipeline.

All model-side constants (NHLe factors, GP floors, bin edges) are the SAME
values the training notebooks baked into the propensity tables. Bin edges are
read straight off the loaded lookup tables at runtime (see score.py) so they can
never drift from the tables they index.
"""
from __future__ import annotations

from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "model"
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
SNAPSHOT_CSV = DATA_DIR / "feeder_snapshot.csv"
PLAYERS_JSON = DOCS_DIR / "data" / "players.json"

# ── Season / league scope ────────────────────────────────────────────────────
# Feeder leagues scored each season. ncaa-iii is a training-history league only,
# not part of the current-season scoring universe (matches the v3 notebooks).
TARGET_SEASON = "2025-2026"
FEEDER_LEAGUES = ("ncaa", "ohl", "whl", "qmjhl", "usports")
# Leagues kept when building career history from EP (drives feeder_szns).
HISTORY_LEAGUES = ("ncaa", "ncaa-iii", "ohl", "whl", "qmjhl", "usports")

# Professional leagues. A current feeder player who has ANY career game in one of
# these — or any EP row whose leagueLevel is professional — has already turned pro
# and is NOT a first-year ECHL candidate, so they're dropped from the population
# (e.g. Celebrini, Will Smith, who now play in the NHL). leagueLevel is the
# primary, dynamic signal; this slug set is a belt-and-suspenders fallback for the
# CSV path, which may not carry leagueLevel.
PRO_LEAGUES = frozenset({
    "nhl", "ahl", "echl", "sphl", "fphl",                 # North America
    "khl", "vhl", "mhl",                                  # Russia
    "shl", "allsvenskan", "hockeyallsvenskan",            # Sweden
    "liiga", "mestis",                                    # Finland
    "czechia", "extraliga", "chance-liga",               # Czechia
    "slovakia", "extraliga-slovakia",                    # Slovakia
    "del", "del2", "nl", "sl",                            # Germany / Switzerland
    "icehl", "ligue-magnus",                              # Austria / France
})


def is_pro_level(level) -> bool:
    """True if an EP leagueLevel string denotes a professional league."""
    return str(level or "").lower().startswith("pro")

SCORING_GP_MIN = 10  # hard floor — below this NHLe is too noisy to show

# ── NHLe conversion (points-per-game -> NHL-equivalent PPG) ───────────────────
# Reconciles exactly with the training tables and ncaa-arc-model/common.py.
LEAGUE_TO_NHLE = {
    "ncaa": 0.194,
    "ncaa-iii": 0.092,
    "ohl": 0.144,
    "whl": 0.141,
    "qmjhl": 0.113,
    "usports": 0.125,
}

# ── Reliability floor: GP below this (≈25% of a season) => sample_flag ─────────
# From bin_metadata_dman.pkl; league-based, so position-independent.
LEAGUE_GP_FLOOR = {"ohl": 17, "whl": 17, "qmjhl": 17, "ncaa": 9, "usports": 7}

# ── Cap overrides (from the training notebooks / bin_metadata) ────────────────
FWD_NHLE_CAP = 0.31   # forwards: nhle >= this => 1st_liner regardless of bin
DMAN_NHLE_CAP = 0.20  # defensemen dual-condition cap (with pm) => number_1
DMAN_PM_CAP = 0.42

# ── Eligibility ──────────────────────────────────────────────────────────────
# "ECHL eligible" = far enough through feeder eligibility to be a realistic
# first-year ECHL candidate. Derived rule (season-count based, no DOB needed):
# reproduces every eligible/ineligible label in the published app. League key is
# the player's CURRENT feeder league; value is the total feeder-season minimum.
#   NOTE: this rule is a documented reconstruction of the (previously manual)
#   `eligible` flag — adjust ELIG_MIN if the desired definition changes.
ELIG_MIN = {"ncaa": 4, "ncaa-iii": 4, "ohl": 3, "whl": 3, "qmjhl": 3, "usports": 3}

# ── Probability column order (must match the pkl table columns AND the app) ────
FWD_PROB_COLS = ["1st_liner", "2nd_liner", "bottom_six_two_way", "checking", "fringe"]
DMAN_PROB_COLS = ["bottom_pair", "fringe", "middle_pair", "number_1", "top_pair"]

# Snapshot / career CSV schema (matches the TopDownHockey scraper columns the
# training notebooks used, so a hand-downloaded CSV can drop straight in).
SNAPSHOT_COLS = [
    "player", "team", "gp", "g", "a", "tp", "ppg", "pim", "+/-",
    "link", "season", "league", "playername", "position", "league_level",
]


def is_defense(position) -> bool:
    """D if the position string contains 'D' (matches the v3 notebooks)."""
    return "D" in str(position or "").upper()
