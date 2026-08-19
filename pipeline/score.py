"""Apply the propensity lookup tables to a current-season feeder DataFrame.

Ports the two v3 scoring notebooks (forwards + defensemen) into one module and
reproduces the PUBLISHED app output exactly, including the two subtle binning
facts verified against the live data:

  * Forwards bin on TOTAL +/-  (table +/- edges are [-inf,-6,0,5,inf]).
  * Defensemen bin on PER-GAME +/- (edges [-inf,-0.15,0.15,inf] ->
    negative/neutral/positive).

Bin edges are taken from the loaded tables themselves, never re-declared here.
"""
from __future__ import annotations

import pickle

import numpy as np
import pandas as pd

import common as c

# Per-game +/- bins for the defenseman model (from bin_metadata_dman.pkl).
DMAN_PM_BINS = [-np.inf, -0.15, 0.15, np.inf]
DMAN_PM_LABELS = ["negative", "neutral", "positive"]


def load_tables():
    def _load(name):
        with open(c.MODEL_DIR / name, "rb") as f:
            return pickle.load(f)
    return {
        "fwd_ppg": _load("propensity_lookup.pkl"),
        "fwd_pm": _load("propensity_lookup_pm.pkl"),
        "dman_ppg": _load("propensity_lookup_dman.pkl"),
        "dman_pm": _load("propensity_lookup_pm_dman.pkl"),
    }


def _row_pct(table_row) -> list[float]:
    """A lookup row -> percentages rounded to 1dp, in the table's column order."""
    return [round(float(v) * 100, 1) for v in table_row.values]


def _zeros(cols) -> list[float]:
    return [0.0] * len(cols)


def _argmax_label(probs, cols) -> str:
    return cols[int(np.argmax(probs))]


def _clamp(nhle, index) -> float:
    """Clamp NHLe into an IntervalIndex's covered range so out-of-range players
    (above the top bin / below the bottom) get the nearest edge bin's
    distribution instead of an all-zero row. Matches the published display."""
    lo, hi = index[0].left, index[-1].right
    eps = (hi - lo) * 1e-6
    return min(max(nhle, lo + eps), hi)


def _fwd_ppg_probs(table, nhle) -> list[float]:
    pos = table.index.get_indexer([_clamp(nhle, table.index)])[0]
    return _row_pct(table.iloc[pos]) if pos >= 0 else _zeros(c.FWD_PROB_COLS)


def _fwd_pm_probs(table, nhle, pm_total) -> list[float]:
    nhle_ix = table.index.levels[0]
    pm_ix = table.index.levels[1]
    npos = nhle_ix.get_indexer([_clamp(nhle, nhle_ix)])[0]
    ppos = pm_ix.get_indexer([pm_total])[0]
    if npos < 0 or ppos < 0:
        return _zeros(c.FWD_PROB_COLS)
    try:
        return _row_pct(table.loc[(nhle_ix[npos], pm_ix[ppos])])
    except KeyError:
        return _zeros(c.FWD_PROB_COLS)


def _dman_ppg_probs(table, nhle) -> list[float]:
    pos = table.index.get_indexer([_clamp(nhle, table.index)])[0]
    return _row_pct(table.iloc[pos]) if pos >= 0 else _zeros(c.DMAN_PROB_COLS)


def _dman_pm_probs(table, nhle, pm_label) -> list[float]:
    nhle_ix = table.index.levels[0]
    npos = nhle_ix.get_indexer([_clamp(nhle, nhle_ix)])[0]
    if npos < 0:
        return _zeros(c.DMAN_PROB_COLS)
    try:
        return _row_pct(table.loc[(nhle_ix[npos], pm_label)])
    except KeyError:
        return _zeros(c.DMAN_PROB_COLS)


def _score_forward(r, tables) -> dict:
    nhle = r["nhle"]
    ppg_p = _fwd_ppg_probs(tables["fwd_ppg"], nhle)
    pm_p = _fwd_pm_probs(tables["fwd_pm"], nhle, r["pm"])

    def proj(probs):
        if nhle >= c.FWD_NHLE_CAP:
            return "1st_liner"
        if sum(probs) == 0:
            return "n/a"
        return _argmax_label(probs, c.FWD_PROB_COLS)

    return {"ppg_p": ppg_p, "ppg_proj": proj(ppg_p),
            "pm_p": pm_p, "pm_proj": proj(pm_p)}


def _score_defense(r, tables) -> dict:
    nhle = r["nhle"]
    pm_pg = r["pm_pg"]
    pm_label = str(pd.cut([pm_pg], bins=DMAN_PM_BINS, labels=DMAN_PM_LABELS)[0])

    ppg_p = _dman_ppg_probs(tables["dman_ppg"], nhle)
    pm_p = _dman_pm_probs(tables["dman_pm"], nhle, pm_label)

    def proj(probs):
        if nhle >= c.DMAN_NHLE_CAP and pm_pg >= c.DMAN_PM_CAP:
            return "number_1"
        if sum(probs) == 0:
            return "top_pair" if nhle >= c.DMAN_NHLE_CAP else "n/a"
        return _argmax_label(probs, c.DMAN_PROB_COLS)

    return {"ppg_p": ppg_p, "ppg_proj": proj(ppg_p),
            "pm_p": pm_p, "pm_proj": proj(pm_p)}


def score(current: pd.DataFrame, tables=None) -> dict:
    """current: one row per current-season player with columns
    player, position, team, league, gp, ppg, pm (total +/-), szn_no, feeder_szns.
    Returns {"forwards": [...], "dmen": [...]}.
    """
    if tables is None:
        tables = load_tables()

    forwards, dmen = [], []
    for _, r in current.iterrows():
        league = r["league"]
        gp = int(r["gp"])
        if gp < c.SCORING_GP_MIN or league not in c.LEAGUE_TO_NHLE:
            continue
        ppg = float(r["ppg"])
        pm_total = int(r["pm"])
        nhle = round(c.LEAGUE_TO_NHLE[league] * ppg, 2)
        pm_pg = round(pm_total / gp, 3) if gp else 0.0
        szn = int(r.get("szn_no") or 1)

        base = {
            "player": r["player"],
            "pos": str(r["position"]).split("/")[0].strip(),
            "team": r["team"],
            "league": league,
            "gp": gp,
            "ppg": round(ppg, 2),
            "pm": pm_total,
            "pm_pg": pm_pg,
            "nhle": nhle,
            "szn": szn,
            "feeder": r.get("feeder_szns") or f"{league}: {szn}",
            "eligible": szn >= c.ELIG_MIN.get(league, 4),
            "sample": gp < c.LEAGUE_GP_FLOOR.get(league, c.SCORING_GP_MIN),
        }
        _ep = r.get("link")
        base["ep"] = _ep if isinstance(_ep, str) and _ep else None

        if c.is_defense(r["position"]):
            base.update(_score_defense({**base}, tables))
            dmen.append(base)
        else:
            base.update(_score_forward({**base}, tables))
            forwards.append(base)

    return {"forwards": forwards, "dmen": dmen}
