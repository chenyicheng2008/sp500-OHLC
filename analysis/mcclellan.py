"""McClellan oscillator study shared by the S&P 500 report and the ^SOX review.

Asked 2026-11-21: 「SP500及費城半導體指數兩篇, 加入麥克連擺盪指標圖及分析」. The oscillator
itself comes from ``breadth_sector.advance_decline`` (19/39-day EMA spread of ratio-adjusted
net advances, RANA x 1000). This module turns an oscillator, its summation index and the
index it describes into one payload: the chart series, the current reading, what followed
past extreme readings (declustered, against every day as the base), and a simple
divergence check. The page draws and words it with ``mcclellan_view.js``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

WARMUP = 39        # the slow EMA needs this many sessions before the spread means anything
GAP = 10           # an extreme reading within GAP sessions of the previous one is the same episode
FWD = (10, 20)     # sessions after a signal
RECENT, PRIOR = 20, 60
DIV_TOL = 5.0      # oscillator points


def thresholds(osc: pd.Series, fixed: float | None = None) -> tuple[float, float]:
    """±fixed when given (the S&P 500 signal board uses ±60); otherwise the series' own
    10th / 90th percentiles, rounded to 10 -- a small group swings much wider."""
    if fixed is not None:
        return -fixed, fixed
    o = osc.dropna()
    return float(10 * round(o.quantile(0.10) / 10)), float(10 * round(o.quantile(0.90) / 10))


def study(osc: pd.Series, summ: pd.Series, idx: pd.Series, fixed: float | None = None) -> dict:
    df = pd.DataFrame({"osc": osc, "sum": summ, "idx": idx}).dropna().iloc[WARMUP:]
    o, x = df["osc"], df["idx"]
    lo, hi = thresholds(o, fixed)
    n = len(df)

    def fwd(i, h):
        return round(float(100 * (x.iloc[i + h] / x.iloc[i] - 1)), 2) if i + h < n else None

    sign = np.sign(o)
    flips = np.nonzero(sign.diff().fillna(0).values != 0)[0]
    last_flip = int(flips[-1]) if len(flips) else None

    signals = {}
    for kind, cond in (("oversold", o <= lo), ("overbought", o >= hi)):
        rows, last = [], -10 ** 9
        for i in np.nonzero(cond.values)[0]:
            if i - last > GAP:
                rows.append({"date": df.index[i].date().isoformat(), "osc": round(float(o.iloc[i]), 1),
                             **{f"f{h}": fwd(i, h) for h in FWD}})
            last = i
        done = [r for r in rows if r[f"f{FWD[-1]}"] is not None]
        vals = [r[f"f{FWD[-1]}"] for r in done]
        signals[kind] = {"rows": rows, "n": len(rows), "n_done": len(done),
                         "median": round(float(np.median(vals)), 2) if vals else None,
                         "pos": int(sum(v > 0 for v in vals))}
    base = [fwd(i, FWD[-1]) for i in range(n)]
    base = [b for b in base if b is not None]

    # divergence: the last RECENT sessions against the PRIOR sessions before them
    rec, pri = df.iloc[-RECENT:], df.iloc[-PRIOR:-RECENT]
    div = {"idx_low_recent": round(float(rec["idx"].min()), 2), "idx_low_prior": round(float(pri["idx"].min()), 2),
           "osc_low_recent": round(float(rec["osc"].min()), 1), "osc_low_prior": round(float(pri["osc"].min()), 1),
           "idx_high_recent": round(float(rec["idx"].max()), 2), "idx_high_prior": round(float(pri["idx"].max()), 2),
           "osc_high_recent": round(float(rec["osc"].max()), 1), "osc_high_prior": round(float(pri["osc"].max()), 1)}
    # the oscillator's lows/highs count as different only beyond DIV_TOL points
    lower_low, higher_high = div["idx_low_recent"] < div["idx_low_prior"], div["idx_high_recent"] > div["idx_high_prior"]
    dlow, dhigh = div["osc_low_recent"] - div["osc_low_prior"], div["osc_high_recent"] - div["osc_high_prior"]
    div["tol"] = DIV_TOL
    div["kind"] = ("positive" if lower_low and dlow >= DIV_TOL else
                   "confirmed_down" if lower_low and dlow <= -DIV_TOL else
                   "flat_down" if lower_low else
                   "negative" if higher_high and dhigh <= -DIV_TOL else
                   "confirmed_up" if higher_high and dhigh >= DIV_TOL else
                   "flat_up" if higher_high else "none")

    cur = float(o.iloc[-1])
    return {
        "dates": [d.date().isoformat() for d in df.index],
        "osc": [round(float(v), 1) for v in o], "sum": [round(float(v), 0) for v in df["sum"]],
        "idx": [round(float(v), 2) for v in x],
        "lo": lo, "hi": hi, "fixed": fixed is not None, "warmup": WARMUP, "gap": GAP, "fwd": list(FWD),
        "recent": RECENT, "prior": PRIOR,
        "now": {"osc": round(cur, 1), "sum": round(float(df["sum"].iloc[-1]), 0),
                "zone": "oversold" if cur <= lo else "overbought" if cur >= hi else "neutral",
                "pctile": round(float(100 * (o < cur).mean()), 0),
                "min": round(float(o.min()), 1), "min_date": o.idxmin().date().isoformat(),
                "max": round(float(o.max()), 1), "max_date": o.idxmax().date().isoformat(),
                "since_cross": n - 1 - last_flip if last_flip is not None else None,
                "cross_date": df.index[last_flip].date().isoformat() if last_flip is not None else None,
                "above_zero": cur > 0,
                "sum_chg10": round(float(df["sum"].iloc[-1] - df["sum"].iloc[-11]), 0)},
        "signals": signals,
        "base": {"n": len(base), "median": round(float(np.median(base)), 2), "pos": int(sum(b > 0 for b in base))},
        "div": div,
    }
