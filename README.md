# 🏒 ECHL Player Development Model

Propensity-based projections for college and major junior players transitioning to their first ECHL season. Built by Batt Analytics.

**Live site:** `https://cbattinieri.github.io/echl-dev-model/`

---

## What it does

Scores every current-season forward and defenseman in the NCAA, OHL, WHL, QMJHL, and USports against historical ECHL rookie outcomes. Outputs a probability distribution across five lineup-fit tiers for each player.

**Forwards:** 1st Liner · 2nd Liner · Bottom 6 / Two-Way · Checking · Fringe  
**Defensemen:** Number One D · Top Pair · Middle Pair · Bottom Pair · Fringe

---

## How it works

Player scoring rates are translated to NHL-equivalent PPG (NHLe), then matched against propensity lookup tables built from 400+ historical ECHL rookie seasons (2020–21 through 2024–25). A second model layer adds per-game +/- as a secondary signal.

---

## Updating projections

When new scoring data is available mid-season, update the `const P` (forwards) and `const D` (defensemen) arrays in `docs/index.html` and push to main. GitHub Pages serves the update within ~30 seconds.

---

## Repository structure

```
docs/
  index.html        ← the app (GitHub Pages serves this)
README.md
.gitignore
```

---

## Model files (not in this repo)

The underlying propensity lookup tables (`.pkl` files) and Jupyter notebooks that generate them are maintained separately. Contact the model owner for access.
