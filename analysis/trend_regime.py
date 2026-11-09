"""Bull / bear share of a sector over time, from moving-average alignment.

Each constituent is classified every session:

    bull     close > MA_fast > MA_slow      (多頭排列)
    bear     close < MA_fast < MA_slow      (空頭排列)
    neither  anything else                  (整理 / 轉折)

Daily view: 50- and 200-day averages on the daily slice (about a year of usable
history once the 200-day average exists). Long-run view: 10- and 40-week averages
on weekly bars -- the older ``1wk`` history with the daily slice resampled onto it
-- which reaches back a decade. The long run uses today's constituents, so it
carries survivorship bias: names that left the index are missing from the past.

Run after ``breadth_sector.py``.

Usage:
    python analysis/trend_regime.py [--sector technology]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from breadth_sector import ENC, load, pivot, drop_empty_sessions

REPO = Path(__file__).resolve().parent.parent
DAILY_MA = (50, 200)
WEEKLY_MA = (10, 40)
LOOKBACK = {"1M": 21, "3M": 63}   # sessions, for "then vs now" comparisons
STATES = ("bull", "neither", "bear")


def classify(close: pd.DataFrame, fast: int, slow: int) -> pd.DataFrame:
    """+1 bull, -1 bear, 0 neither, NaN while either average is still warming up."""
    f = close.rolling(fast, min_periods=fast).mean()
    s = close.rolling(slow, min_periods=slow).mean()
    valid = close.notna() & f.notna() & s.notna()
    state = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    state[(close > f) & (f > s)] = 1.0
    state[(close < f) & (f < s)] = -1.0
    return state.where(valid)


def shares(state: pd.DataFrame) -> pd.DataFrame:
    n = state.notna().sum(axis=1)
    out = pd.DataFrame({
        "bull": 100 * (state == 1).sum(axis=1) / n,
        "neither": 100 * (state == 0).sum(axis=1) / n,
        "bear": 100 * (state == -1).sum(axis=1) / n,
        "n": n,
    })
    out["net"] = out["bull"] - out["bear"]
    return out[n > 0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.environ.get("FETCH_BASE", str(REPO / "data" / "weekly_reutin")))
    ap.add_argument("--out-dir", default=str(REPO / "data" / "analysis"))
    ap.add_argument("--sector", default="technology")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)

    ohlc, fund, _ = load(Path(args.data_dir))
    daily, _ = drop_empty_sessions(pivot(ohlc, "1d", "Close"))
    weekly_hist, _ = drop_empty_sessions(pivot(ohlc, "1wk", "Close"))
    weekly = pd.concat([
        weekly_hist[weekly_hist.index < daily.index[0]].resample("W-FRI").last(),
        daily.resample("W-FRI").last(),
    ])
    weekly = weekly[~weekly.index.duplicated(keep="last")].dropna(how="all")

    meta = fund.set_index("Ticker")
    members = [t for t in meta.index[meta["Sector"] == args.sector] if t in daily.columns]
    if not members:
        raise SystemExit(f"no constituents with price history in sector {args.sector!r}")

    # --- daily: sector vs whole market --------------------------------------
    d_state = classify(daily, *DAILY_MA)
    d_sec, d_mkt = shares(d_state[members]), shares(d_state)
    first = max(d_sec.index[0], d_mkt.index[0])
    daily_out = d_sec.add_prefix("sec_").join(d_mkt.add_prefix("mkt_"), how="inner").loc[first:]
    daily_out.index.name = "Date"
    daily_out.round(2).to_csv(out_dir / "trend_regime_daily.csv", encoding=ENC)

    # --- weekly long run ------------------------------------------------------
    w_state = classify(weekly, *WEEKLY_MA)
    w_members = [t for t in members if t in w_state.columns]
    w_sec, w_mkt = shares(w_state[w_members]), shares(w_state)
    weekly_out = w_sec.add_prefix("sec_").join(w_mkt.add_prefix("mkt_"), how="inner")
    weekly_out = weekly_out[weekly_out["sec_n"] >= 10]          # too few names early on to mean anything
    weekly_out.index.name = "Date"
    weekly_out.round(2).to_csv(out_dir / "trend_regime_weekly.csv", encoding=ENC)

    # --- industries inside the sector, now vs 1M / 3M ago ---------------------
    last = d_state.index[-1]
    rows = []
    for ind, grp in meta.loc[members].groupby("Industry"):
        tks = grp.index.tolist()
        row = {"Industry": ind, "n": len(tks)}
        for lab, back in [("now", 0)] + list(LOOKBACK.items()):
            st = d_state[tks].iloc[-1 - back]
            m = st.notna().sum()
            row[f"bull_{lab}"] = 100 * (st == 1).sum() / m if m else np.nan
            row[f"bear_{lab}"] = 100 * (st == -1).sum() / m if m else np.nan
            row[f"net_{lab}"] = row[f"bull_{lab}"] - row[f"bear_{lab}"]
        rows.append(row)
    industry = pd.DataFrame(rows).sort_values(["net_now", "n"], ascending=[False, False])
    industry.round(1).to_csv(out_dir / "trend_regime_industry.csv", index=False, encoding=ENC)

    # --- transitions over the last month: where the ratio's change came from ---
    back = LOOKBACK["1M"]
    then, now = d_state[members].iloc[-1 - back], d_state[members].iloc[-1]
    lab = {1.0: "bull", 0.0: "neither", -1.0: "bear"}
    matrix = {a: {b: 0 for b in STATES} for a in STATES}
    moved = {}
    for t in members:
        if pd.isna(then[t]) or pd.isna(now[t]):
            continue
        a, b = lab[then[t]], lab[now[t]]
        matrix[a][b] += 1
        if a != b:
            moved.setdefault(f"{a}->{b}", []).append(t)

    # Current state of every member, for the name lists.
    names = {s: sorted(t for t in members if pd.notna(now[t]) and lab[now[t]] == s) for s in STATES}

    sec_hist = daily_out["sec_net"]
    wk_hist = weekly_out["sec_net"]
    bundle = {
        "sector": args.sector,
        "asof": last.date().isoformat(),
        "ma_daily": DAILY_MA, "ma_weekly": WEEKLY_MA,
        "n_members": len(members),
        "daily_start": daily_out.index[0].date().isoformat(),
        "weekly_start": weekly_out.index[0].date().isoformat(),
        "then_date": d_state.index[-1 - back].date().isoformat(),
        "transitions": matrix,
        "moved": {k: sorted(v) for k, v in moved.items()},
        "names_now": names,
        "industry_of": {t: meta.at[t, "Industry"] for t in members},
        "lookback": {k: {"date": d_state.index[-1 - v].date().isoformat(),
                         **{c: round(float(daily_out[c].iloc[-1 - v]), 1)
                            for c in ("sec_bull", "sec_bear", "sec_net", "mkt_bull", "mkt_bear", "mkt_net")}}
                     for k, v in LOOKBACK.items() if len(daily_out) > v},
        # Where today's net reading sits in its own history, daily (~1y) and weekly (~10y).
        "pctile_daily": round(float(100 * (sec_hist < sec_hist.iloc[-1]).mean()), 1),
        "pctile_weekly": round(float(100 * (wk_hist < wk_hist.iloc[-1]).mean()), 1),
        "weekly_extremes": {
            "max": {"date": wk_hist.idxmax().date().isoformat(), "net": round(float(wk_hist.max()), 1)},
            "min": {"date": wk_hist.idxmin().date().isoformat(), "net": round(float(wk_hist.min()), 1)},
        },
    }
    with open(out_dir / "trend_regime_bundle.json", "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, ensure_ascii=False, indent=1, default=str)

    t = daily_out.iloc[-1]
    print(f"{args.sector}: {len(members)} names, as of {bundle['asof']}")
    print(f"  daily  bull {t.sec_bull:.1f}%  neither {t.sec_neither:.1f}%  bear {t.sec_bear:.1f}%  "
          f"net {t.sec_net:+.1f} (market net {t.mkt_net:+.1f}); 1y percentile {bundle['pctile_daily']}")
    print(f"  weekly net {wk_hist.iloc[-1]:+.1f}, {bundle['weekly_start']} on; 10y percentile {bundle['pctile_weekly']}")
    print(f"  1M transitions: {bundle['moved']}")


if __name__ == "__main__":
    main()
