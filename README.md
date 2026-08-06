# 🏒 ECHL Rookie Development Model

Propensity-based projections for college and major-junior players transitioning
to their first ECHL season. Built by Batt Analytics.

**Live site:** `https://cbattinieri.github.io/echl-dev-model/`

---

## What it does

Scores every current-season forward and defenseman in the NCAA, OHL, WHL, QMJHL,
and USports against historical ECHL rookie outcomes, and outputs a probability
distribution across five lineup-fit tiers per player.

**Compare & export** (ported from the Veteran Tracker): check up to 5 rows to build
a shortlist, open a side-by-side **Compare** grid (best value per row highlighted,
both models shown), and **export** either your shortlist or the full filtered list
to `.xlsx` (via SheetJS).

The population is **dynamic**: players who have already played professional games
(NHL, AHL, ECHL, top European leagues, …) are dropped automatically — the model
projects a player's *first* pro season, so someone like Celebrini or Will Smith
(now in the NHL) is not a candidate. See "Model notes → population" below.

**Forwards:** 1st Liner · 2nd Liner · Bottom 6 / Two-Way · Checking · Fringe
**Defensemen:** Number One D · Top Pair · Middle Pair · Bottom Pair · Fringe

Each player is scored by two models: **PPG** (NHLe scoring rate only) and
**PPG + / −** (adds on-ice-impact context).

---

## Architecture (productionalized)

```
pipeline/
  common.py    constants — NHLe factors, GP floors, eligibility, league scope
  ep_pull.py   EliteProspects API client → data/feeder_snapshot.csv
  score.py     the model — propensity lookups → tier probabilities (ports the
               v3 forward + defenseman scoring notebooks)
  build.py     orchestrator: load data → score → docs/data/players.json
model/         propensity lookup tables (.pkl) + committed here
data/
  feeder_snapshot.csv   the keyless data snapshot (see below)
docs/
  index.html            the app — fetches data/players.json at runtime
  data/players.json     generated model output
.github/workflows/update_data.yml   scheduled/CI rebuild + deploy
```

Python pipeline → static JSON → static HTML. The app has **no** hardcoded data;
it loads `docs/data/players.json` at runtime.

---

## Data source & fallback (EP → CSV snapshot)

The EliteProspects API is the primary source; a committed CSV snapshot is the
durable, keyless fallback. `build.py` picks automatically:

| Condition | Source |
|---|---|
| `EP_API_KEY` set **and** `--refresh` (or no snapshot yet) | EP API → refresh `data/feeder_snapshot.csv`, then score |
| otherwise (the default) | read the committed `data/feeder_snapshot.csv` |

So the app keeps updating after the EP trial key expires: everything downstream
reads the snapshot. To refresh data, either re-pull from EP (below) or drop a
hand-downloaded feeder CSV at `data/feeder_snapshot.csv` with columns:
`player, team, gp, g, a, tp, ppg, pim, +/-, link, season, league, playername, position`
(the same schema the feeder-league CSVs already use).

> **The EP key is a secret.** It is read **only** from the `EP_API_KEY`
> environment variable, passed inline at invocation, and never written to the
> repo, a file, or a log.

---

## Run locally

```bash
pip install -r requirements.txt

# Score off the committed snapshot (keyless):
python pipeline/build.py

# Or re-pull the current season from EP first (trial key required):
EP_API_KEY="your_key" python pipeline/build.py --refresh

# Preview:
python -m http.server 8000 --directory docs   # http://localhost:8000
```

`build.py` writes `docs/data/players.json`. Commit both the JSON and (if you
refreshed) `data/feeder_snapshot.csv`, then push — GitHub Pages redeploys.

---

## Updating the salary-cap / season each year

Set `TARGET_SEASON` in `pipeline/common.py` (e.g. `"2026-2027"`). NHLe factors,
GP floors, eligibility thresholds, and the propensity tables live in
`common.py` / `model/` and rarely change.

---

## Deploy

- Scheduled + push-triggered rebuild via `.github/workflows/update_data.yml`.
- Runs keyless off the committed snapshot by default; if the `EP_API_KEY` repo
  secret is set, it re-pulls from EP first.
- GitHub Pages serves `docs/`.

---

## Model notes

- **NHLe:** `nhle_ppg = LEAGUE_TO_NHLE[league] × ppg` (ncaa .194, ohl .144,
  whl .141, qmjhl .113, usports .125) — identical to the training tables.
- **Binning:** rounded NHLe → right-closed bins from the propensity tables;
  out-of-range NHLe is clamped to the nearest edge bin (elite players get the
  top-bin distribution rather than an empty bar).
- **+/− :** forwards bin on **total** +/−; defensemen on **per-game** +/−
  (negative / neutral / positive) — matching how each table was trained.
- **Cap overrides:** forwards with NHLe ≥ 0.31 → 1st Liner; defensemen with
  NHLe ≥ 0.20 **and** per-game +/− ≥ 0.42 → Number One D.
- **`sample`:** GP below ~25% of a season (league-specific floor) → flagged.
- **`eligible` ("ECHL Likely"):** far enough through feeder eligibility to be a
  realistic first-year ECHL candidate (NCAA ≥4 seasons; CHL/USports ≥3). Rule in
  `common.ELIG_MIN`.
- **Population (pro filter):** any current feeder player with career games in a
  pro league is dropped. Detection uses EP's `leagueLevel` (dynamic) plus
  `common.PRO_LEAGUES` (fallback for the CSV path). Count reported as
  `meta.excluded_pro`.
