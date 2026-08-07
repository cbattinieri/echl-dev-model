"""Build docs/data/players.json for the ECHL Rookie Dev Model app.

Data source (matches the productionalization decision — EP -> CSV snapshot):
  * EP API  — used when EP_API_KEY is set AND (--refresh is passed OR no snapshot
              exists). Refreshes data/feeder_snapshot.csv, then scores off it.
  * CSV snapshot — the default, keyless path. Reads the committed
              data/feeder_snapshot.csv. This is what CI runs and what keeps the
              app updating after the EP trial key expires (drop in a fresh CSV).

Usage:
    python pipeline/build.py              # score off the committed snapshot
    EP_API_KEY=xxx python pipeline/build.py --refresh   # re-pull from EP first

Never commit EP_API_KEY. The snapshot CSV is the durable, shareable artifact.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # make siblings importable

import pandas as pd

import common as c
import score as scoring


def _load_snapshot() -> tuple[pd.DataFrame, str]:
    """Returns (careers_df, source). EP if allowed+available, else the CSV."""
    import os
    want_refresh = "--refresh" in sys.argv
    have_key = bool(os.environ.get("EP_API_KEY"))
    if have_key and (want_refresh or not c.SNAPSHOT_CSV.exists()):
        import ep_pull
        df = ep_pull.build_snapshot()
        c.DATA_DIR.mkdir(exist_ok=True)
        df.to_csv(c.SNAPSHOT_CSV, index=False)
        print(f"  refreshed snapshot -> {c.SNAPSHOT_CSV} ({len(df):,} rows)")
        return df, "ep"
    if not c.SNAPSHOT_CSV.exists():
        # No data and no key (fresh clone / CI before the first pull): don't crash
        # the deploy — emit an empty placeholder so the app loads honestly empty.
        print(f"No snapshot at {c.SNAPSHOT_CSV} and no EP_API_KEY.\n"
              f"  Writing placeholder players.json. To populate: set EP_API_KEY and "
              f"run `python pipeline/build.py --refresh`, or drop a feeder CSV there "
              f"with columns: {', '.join(c.SNAPSHOT_COLS)}")
        return None, "placeholder"
    df = pd.read_csv(c.SNAPSHOT_CSV).drop(columns=["Unnamed: 0"], errors="ignore")
    return df, "snapshot"


def _write_placeholder() -> None:
    payload = {
        "meta": {
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "season": c.TARGET_SEASON,
            "source": "placeholder",
            "counts": {"forwards": 0, "dmen": 0, "excluded_pro": 0},
        },
        "forwards": [],
        "dmen": [],
    }
    c.PLAYERS_JSON.parent.mkdir(parents=True, exist_ok=True)
    c.PLAYERS_JSON.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote placeholder {c.PLAYERS_JSON} (0 players — awaiting first data pull)")


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("gp", "g", "a", "tp", "ppg", "pim", "+/-"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "league_level" not in df.columns:
        df["league_level"] = None  # CSV fallback may lack it; slug set still works
    df = df[df["team"].astype(str).str.lower() != "totals"]
    df = df.dropna(subset=["player", "season", "league"])
    # Strip trailing " (POS)" the EP scraper appends to names (EP API names are
    # already clean); do it uniformly so career-history joins stay consistent.
    df["player"] = df["player"].astype(str).str.replace(r"\s*\([^)]*\)\s*$", "", regex=True).str.strip()
    return df


def _feeder_seasons(careers: pd.DataFrame) -> pd.DataFrame:
    """Per-player total feeder seasons (szn_no) + 'lg: n, lg: n' summary."""
    per_lg = (
        careers.groupby(["player", "league"])["season"].nunique().reset_index()
        .rename(columns={"season": "n"})
    )
    per_lg["league_szn"] = per_lg["league"] + ": " + per_lg["n"].astype(str)
    summary = (
        per_lg.sort_values(["player", "n", "league"], ascending=[True, False, True])
        .groupby("player")["league_szn"].apply(lambda x: ", ".join(x))
        .reset_index().rename(columns={"league_szn": "feeder_szns"})
    )
    total = (
        careers.groupby("player")["season"].nunique().reset_index()
        .rename(columns={"season": "szn_no"})
    )
    return summary.merge(total, on="player")


def _pro_experienced(careers: pd.DataFrame) -> set:
    """Players who are no longer first-year ECHL candidates: anyone with ANY
    pro-league career row — whether they played games, were signed to a pro club
    for an upcoming season (future-season roster row, e.g. Cody Morgan -> ECHL
    Fort Wayne 2026-27), or were rostered pro this season without dressing (0-GP
    entry, e.g. Jake O'Brien -> AHL Coachella Valley 2025-26). Being on a pro
    roster at all = already turned pro. Pro is detected via EP leagueLevel
    (dynamic, catches pro leagues outside PRO_LEAGUES) + a slug set."""
    is_pro = careers["league"].isin(c.PRO_LEAGUES) | careers["league_level"].map(c.is_pro_level)
    return set(careers.loc[is_pro, "player"]) | _manual_excludes()


def _manual_excludes() -> set:
    """Names in data/pro_exclude.txt (one per line, '#' comments) are always
    dropped. Safety net for the CSV fallback: a hand-downloaded feeder CSV may
    contain ONLY feeder-league rows (no AHL/NHL/etc.), so the pro-filter can't
    see that a player turned pro — list them here to exclude them anyway. Match
    is exact against the cleaned player name shown in the app."""
    f = c.DATA_DIR / "pro_exclude.txt"
    if not f.exists():
        return set()
    return {ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")}


def _current_players(careers: pd.DataFrame, season: str) -> pd.DataFrame:
    """One aggregated row per player for the target season (handles trades),
    excluding anyone who has already played pro games."""
    pro = _pro_experienced(careers)
    cur = careers[careers["season"] == season].copy()
    cur = cur[cur["league"].isin(c.FEEDER_LEAGUES)]
    cur = cur[~cur["player"].isin(pro)]
    if cur.empty:
        return cur
    cur = cur.sort_values("gp", ascending=False)
    agg = cur.groupby("player", as_index=False).agg(
        position=("position", "first"),
        team=("team", "first"),          # team with most GP
        league=("league", "first"),      # league with most GP
        gp=("gp", "sum"),
        tp=("tp", "sum"),
        pm=("+/-", "sum"),
    )
    agg["ppg"] = (agg["tp"] / agg["gp"]).where(agg["gp"] > 0, 0).round(4)
    return agg


def main():
    careers, source = _load_snapshot()
    if careers is None:
        _write_placeholder()
        return
    careers = _clean(careers)
    print(f"Snapshot: {len(careers):,} feeder rows, "
          f"{careers['player'].nunique():,} players (source: {source})")

    pro = _pro_experienced(careers)
    cur_universe = careers[(careers["season"] == c.TARGET_SEASON)
                           & careers["league"].isin(c.FEEDER_LEAGUES)]["player"]
    excluded_pro = cur_universe[cur_universe.isin(pro)].nunique()
    print(f"Excluded {excluded_pro} current feeder players who already played pro")

    current = _current_players(careers, c.TARGET_SEASON)
    if current.empty:
        sys.exit(f"No {c.TARGET_SEASON} rows in snapshot for {c.FEEDER_LEAGUES}.")
    current = current.merge(_feeder_seasons(careers), on="player", how="left")
    current["szn_no"] = current["szn_no"].fillna(1).astype(int)

    result = scoring.score(current)
    f, d = result["forwards"], result["dmen"]
    print(f"Scored: {len(f)} forwards, {len(d)} defensemen")

    payload = {
        "meta": {
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "season": c.TARGET_SEASON,
            "source": source,
            "counts": {"forwards": len(f), "dmen": len(d), "excluded_pro": int(excluded_pro)},
        },
        "forwards": f,
        "dmen": d,
    }
    c.PLAYERS_JSON.parent.mkdir(parents=True, exist_ok=True)
    c.PLAYERS_JSON.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {c.PLAYERS_JSON}  "
          f"({c.PLAYERS_JSON.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
