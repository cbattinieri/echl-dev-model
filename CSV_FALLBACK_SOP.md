# SOP — Running the ECHL Dev Model from CSVs (EP API fallback)

Use this when the EliteProspects API is unavailable — trial key expired/revoked,
pricing changed, endpoint or auth broke, or throttling makes a pull impractical.
The scoring pipeline is designed to run **entirely off a CSV** with no API access.

---

## TL;DR

1. Get a feeder-league CSV (or several) and combine them into one file.
2. Save it as `data/feeder_snapshot.csv` (schema below).
3. Run `python pipeline/build.py` (no `EP_API_KEY`, no `--refresh`).
4. Validate the printed counts + spot-check, commit, push. Done.

The pipeline **does not use `playerID` or `DOB`** for anything — scoring,
eligibility, and the pro-filter are all name/season/league based. A CSV missing
those columns works fine. The one thing that *does* matter is covered under
**⚠️ The pro-filter** below.

---

## 1. Required CSV schema

One row per **player-season-league** (a player appears on multiple rows — one per
season, plus any league they played in that season). Header, exact names:

```
player,team,gp,g,a,tp,ppg,pim,+/-,link,season,league,playername,position,league_level
```

| Column | Required? | Notes |
|---|---|---|
| `player` | **yes** | Full name. The join key. Trailing `" (POS)"` is auto-stripped. |
| `gp` | **yes** | Games played (int). |
| `tp` | **yes** | Total points. `ppg` is recomputed as `tp/gp`, so `tp` is what matters. |
| `ppg` | recommended | Used only if present in current-season aggregation; `tp/gp` is authoritative. |
| `+/-` | **yes** | Plus/minus (total). Drives the ± model. Use `0` if truly unavailable. |
| `season` | **yes** | Format `YYYY-YYYY`, e.g. `2025-2026`. Must match `TARGET_SEASON` in `pipeline/common.py`. |
| `league` | **yes** | **Slug**, lowercase: `ncaa`, `ohl`, `whl`, `qmjhl`, `usports` (+ pro slugs, see below). |
| `position` | **yes** | Contains `D` ⇒ defenseman, else forward. |
| `team` | recommended | Display + trade aggregation; also part of the compare/export key. |
| `g`, `a`, `pim` | optional | Carried through; not used in scoring. |
| `link` | optional | EP URL for reference. Not required. |
| `playername` | optional | Legacy duplicate of `player`. |
| `league_level` | optional | If present and starts with `pro`, flags a pro row. Usually absent in CSVs — the `league` slug set is the fallback (see below). |

**Not needed at all:** `playerID`, `DOB`, `birth year`, `nhle_ppg` (recomputed),
`draft`, `height/weight`. Their absence changes nothing.

---

## 2. What the CSV must contain to be correct

Two things beyond "current-season scoring":

**(a) Career history for `feeder_szns` / eligibility.** Eligibility ("ECHL Likely")
= total feeder seasons ≥ a per-league threshold (NCAA 4, CHL/USports 3). That count
comes from **all** of a player's feeder rows across seasons in the file. If the CSV
is current-season-only, every player shows `szn: 1` and almost no one is "ECHL
Likely." Include prior feeder seasons (the repo's training CSVs cover 2019-20→) so
season counts are right.

**(b) ⚠️ The pro-filter — the one real gotcha.** Players who've already turned pro
(Celebrini, Will Smith, Jake O'Brien, etc.) are dropped by detecting **pro-league
rows** in their career. The API returns those rows automatically; a
hand-downloaded feeder-only CSV **will not**, so those players reappear in the pool.

Two ways to keep the filter working:

- **Preferred — include pro rows.** In the same file, include each such player's
  pro-league season rows, with `league` set to the correct **slug**:
  `nhl, ahl, echl, sphl, fphl, khl, shl, liiga, czechia, slovakia, del, nl` … (full
  set in `pipeline/common.py → PRO_LEAGUES`). Any career row with one of those
  slugs (any GP, any season) disqualifies the player. `league_level` starting with
  `pro` also works if your source provides it.
- **Fallback — manual exclude list.** If you can't get pro rows, list names in
  `data/pro_exclude.txt` (one per line, `#` for comments). Those are always dropped.
  Match the **exact** name as shown in the app. Keep this file updated each refresh.

---

## 3. Where to get the CSV

- **EliteProspects site export / league stat pages** for `ncaa, ohl, whl, qmjhl,
  usports` for `2025-2026` (and prior seasons for history).
- **A scraper** producing the schema above (the original training CSVs came from
  `TopDownHockey_Scraper`, the same tool the Vet Tracker uses — note it has been
  unreliable; verify output isn't all-zero GP before trusting it).
- **The committed training CSVs** in the model's source folder already provide
  2019-20→2023-24 history for the feeder leagues; you mainly need to append the
  current season.

Combine per-league / per-season files into one `data/feeder_snapshot.csv`
(concatenate rows; identical headers). Order doesn't matter.

---

## 4. Run + deploy

```bash
cd ~/OneDrive/batt_analytics/echl-dev-model
# no EP_API_KEY set, no --refresh -> reads data/feeder_snapshot.csv
"C:/Users/cbatt/AppData/Local/Python/pythoncore-3.14-64/python.exe" pipeline/build.py
```

Expected output:
```
Snapshot: <N> feeder rows, <M> players (source: snapshot)
Excluded <K> current feeder players who already played pro
Scored: <F> forwards, <D> defensemen
Wrote .../docs/data/players.json
```

Then commit + push (Pages auto-deploys):
```bash
git add data/feeder_snapshot.csv docs/data/players.json
git commit -m "data: refresh from CSV snapshot $(date -u +%F)"
git push
```

The GitHub Action also runs `build.py` off the committed snapshot on each push, so
CI reproduces the same `players.json` with no key required.

---

## 5. Validation checklist (do every time)

- `source: snapshot` in the run log (confirms it did **not** try the API).
- Forward/defense counts are in the expected ballpark (roughly ~2,000 F / ~1,000 D
  for a full feeder season).
- `Excluded K … already played pro` is **> 0**. If it's `0`, your pro rows /
  `pro_exclude.txt` aren't being picked up — the pool will wrongly include NHL/AHL
  players. Fix before pushing.
- Spot-check: known graduated pros (e.g. Celebrini, Jake O'Brien) are **absent**;
  a known senior (e.g. an NCAA 4th-year) is present and flagged ECHL Likely.
- Open `docs/data/players.json`: `meta.source` = `snapshot`, and probability rows
  each sum to ~100.

---

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `No {season} rows in snapshot` | `season` values don't match `TARGET_SEASON`; or no current-season rows. Fix season strings / add the season. |
| Everyone `szn: 1`, almost none ECHL Likely | No historical rows — add prior feeder seasons. |
| `Excluded 0 … already played pro` | No pro-league rows and no `pro_exclude.txt` — add one. |
| NHL/AHL players showing in the pool | Same as above — pro-filter has nothing to match on. |
| Wrong league not scoring | `league` must be the lowercase **slug** (`ncaa`, not `NCAA`). |
| A player double-counts / bad current stats | Multiple current-season teams (trade) — that's handled (rows are aggregated by player); just ensure no pre-summed `totals` row (those are dropped by team name `totals`). |

---

## 7. What never needs the API

NHLe factors, propensity tables (`model/*.pkl`), bin edges, tier labels,
eligibility thresholds, and the pro-league slug set all live in the repo. The API
is *only* a convenience for fetching fresh rows; every transformation runs offline
from the CSV. Switching to CSVs is a data-sourcing change, not a model change.
