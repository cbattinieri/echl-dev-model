"""Pull current-season feeder-league data from the EliteProspects API and write
data/feeder_snapshot.csv — the keyless snapshot everything downstream reads.

Snapshot = every feeder-league season row (history + current) for each player who
appears in a feeder league this season. That's enough to compute both the
current-season stat line AND each player's career feeder-season counts, so the
scorer never needs to touch the API again.

Auth: reads EP_API_KEY from the environment ONLY. The key is passed inline at
invocation and never written to the repo, a file, or a log:
    EP_API_KEY=xxxxx python pipeline/ep_pull.py

EP gotchas handled (learned in ncaa-arc-model): the default urllib User-Agent is
403-blocked, and throttle responses come back as HTTP 200 with a {"message": ...}
body and no data.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

import common as c

API_KEY = os.environ.get("EP_API_KEY", "")
BASE = "https://api.eliteprospects.com/v1"
UA = "Mozilla/5.0 (batt-analytics echl-dev-model research)"
PAGE = 1000
SLEEP = 0.34  # ~3 req/s — tier-safe on the full-access key
KEEP_STATS_TYPE = "default"  # regular season


class RateLimited(Exception):
    pass


def _get(path: str, params: dict) -> dict:
    params = {**params, "apiKey": API_KEY}
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.loads(r.read().decode())
            if isinstance(d, dict) and d.get("message") and "data" not in d:
                raise RateLimited(d["message"])
            return d
        except RateLimited as e:
            wait = 20 * (attempt + 1)
            print(f"    throttled ({str(e)[:40]}); wait {wait}s", flush=True)
            time.sleep(wait)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503):
                wait = 15 * (attempt + 1)
                print(f"    HTTP {e.code}; wait {wait}s", flush=True)
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"    net {str(e)[:40]}; retry", flush=True)
            time.sleep(10)
    raise RuntimeError(f"giving up after retries: {path} {params}")


def _paged(path: str, params: dict):
    offset = 0
    while True:
        d = _get(path, {**params, "limit": PAGE, "offset": offset})
        rows = d.get("data", []) or []
        yield from rows
        total = (d.get("_meta", {}) or {}).get("totalRecords", 0)
        offset += PAGE
        time.sleep(SLEEP)
        if offset >= total or not rows:
            break


def pull_universe(season: str) -> dict:
    """{player_id: name} for everyone with a row in a feeder league this season."""
    ids: dict[str, str] = {}
    for lg in c.FEEDER_LEAGUES:
        n = 0
        for row in _paged("player-stats", {"league": lg, "season": season}):
            p = row.get("player") or {}
            pid = p.get("id")
            if pid is not None:
                ids[str(pid)] = p.get("name")
                n += 1
        print(f"  {lg} {season}: {n} rows | universe now {len(ids)}", flush=True)
    return ids


def _career_rows(pid: str):
    for r in _paged("player-stats", {"player": pid}):
        if r.get("statsType") != KEEP_STATS_TYPE:
            continue
        lg = (r.get("league") or {}).get("slug")
        team = r.get("team") or {}
        level = ((team.get("league") or {}) or {}).get("leagueLevel")
        # Keep feeder rows (scoring + feeder_szns) AND pro rows (so build.py can
        # drop players who've already turned pro). Skip everything else.
        if lg not in c.HISTORY_LEAGUES and lg not in c.PRO_LEAGUES \
                and not c.is_pro_level(level):
            continue
        rs = r.get("regularStats") or {}
        p = r.get("player") or {}
        yield {
            "player": p.get("name"),
            "team": team.get("name"),
            "gp": rs.get("GP"),
            "g": rs.get("G"),
            "a": rs.get("A"),
            "tp": rs.get("PTS"),
            "ppg": rs.get("PPG"),
            "pim": rs.get("PIM"),
            "+/-": rs.get("PM"),
            "link": f"https://www.eliteprospects.com/player/{p.get('id')}",
            "season": (r.get("season") or {}).get("slug"),
            "league": lg,
            "playername": p.get("name"),
            "position": p.get("position"),
            "league_level": level,
        }


def build_snapshot(season: str = c.TARGET_SEASON) -> pd.DataFrame:
    if not API_KEY:
        sys.exit("Set EP_API_KEY in the environment.")
    print(f"Building feeder snapshot for {season} from EliteProspects...")
    ids = pull_universe(season)
    print(f"universe: {len(ids)} players; pulling careers...", flush=True)
    recs = []
    for i, pid in enumerate(ids, 1):
        recs.extend(_career_rows(pid))
        if i % 100 == 0:
            print(f"    {i}/{len(ids)} careers", flush=True)
    df = pd.DataFrame.from_records(recs, columns=c.SNAPSHOT_COLS)
    return df


def main():
    df = build_snapshot()
    c.DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(c.SNAPSHOT_CSV, index=False)
    print(f"\nWrote {c.SNAPSHOT_CSV}  ({len(df):,} rows, "
          f"{df['player'].nunique():,} players)")


if __name__ == "__main__":
    main()
