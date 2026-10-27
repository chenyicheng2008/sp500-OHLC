"""Weekly + monthly KD (stochastic 9,3,3) crosses across S&P 500 constituents.

Flags names whose weekly and monthly KD cross in the same month inside an extreme
zone, then lines each one up against the factors that could explain it: sector,
returns, position vs moving averages, valuation, growth, and any large single-day
move or catalogued event inside the event window.

Run after ``breadth_sector.py`` (it reuses that module's loading and quality gates).

Usage:
    python analysis/kd_signals.py [--data-dir data/weekly_reutin] [--out-dir data/analysis]
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

KD_N = 9                   # RSV lookback; K and D both smooth with weight 1/3 (the 9,3,3 convention)
ZONES = {"primary": (80, 20), "watch": (70, 30)}
EVENT_WINDOW = 10          # sessions; a single-day move this recent is shown as a possible cause
BIG_MOVE = 0.08            # |one-day move| worth reporting as a factor


def bars(fields: dict, rule: str) -> dict:
    """Resample daily OHLC to `rule`, with the older weekly history spliced in front."""
    how = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    out = {}
    for f, agg in how.items():
        daily, weekly = fields[f]
        rd = daily.resample(rule).agg(agg)
        rw = weekly[weekly.index < daily.index[0]].resample(rule).agg(agg)
        s = pd.concat([rw, rd])
        out[f] = s[~s.index.duplicated(keep="last")].dropna(how="all")
    return out


def kd(b: dict, n: int = KD_N) -> tuple:
    """Taiwan-style KD: RSV over n bars, K = 2/3 K' + 1/3 RSV, D = 2/3 D' + 1/3 K, seeded at 50."""
    hh = b["High"].rolling(n, min_periods=n).max()
    ll = b["Low"].rolling(n, min_periods=n).min()
    rsv = 100 * (b["Close"] - ll) / (hh - ll).replace(0, np.nan)
    K = pd.DataFrame(np.nan, index=rsv.index, columns=rsv.columns)
    D = K.copy()
    k = pd.Series(50.0, index=rsv.columns)
    d = pd.Series(50.0, index=rsv.columns)
    for t in rsv.index:
        r = rsv.loc[t]
        ok = r.notna()
        k = k.where(~ok, 2 / 3 * k + 1 / 3 * r)
        d = d.where(~ok, 2 / 3 * d + 1 / 3 * k)
        K.loc[t] = k.where(ok)
        D.loc[t] = d.where(ok)
    return K, D


def crosses_in(K: pd.DataFrame, D: pd.DataFrame, at: list, kind: str) -> pd.DataFrame:
    """First K/D cross of `kind` on any bar in `at`, with K and D on the bar before it."""
    rows = {}
    for t in at:
        i = K.index.get_loc(t)
        if i == 0:
            continue
        k0, d0, k1, d1 = K.iloc[i - 1], D.iloc[i - 1], K.iloc[i], D.iloc[i]
        hit = ((k0 >= d0) & (k1 < d1)) if kind == "down" else ((k0 <= d0) & (k1 > d1))
        for tk in hit[hit].index:
            rows.setdefault(tk, {"bar": t.date().isoformat(), "k_before": float(k0[tk]),
                                 "d_before": float(d0[tk]), "k": float(k1[tk]), "d": float(d1[tk])})
    return pd.DataFrame.from_dict(rows, orient="index")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.environ.get("FETCH_BASE", str(REPO / "data" / "weekly_reutin")))
    ap.add_argument("--out-dir", default=str(REPO / "data" / "analysis"))
    ap.add_argument("--events", default=str(REPO / "data" / "events" / "market_events.csv"))
    args = ap.parse_args()
    out_dir = Path(args.out_dir)

    ohlc, fund, _ = load(Path(args.data_dir))
    close, _ = drop_empty_sessions(pivot(ohlc, "1d", "Close"))
    fields = {}
    for f in ["Open", "High", "Low", "Close"]:
        weekly, _ = drop_empty_sessions(pivot(ohlc, "1wk", f))
        fields[f] = (pivot(ohlc, "1d", f).reindex(close.index), weekly)

    W, M = bars(fields, "W-FRI"), bars(fields, "ME")
    Kw, Dw = kd(W)
    Km, Dm = kd(M)
    month = Km.index[-1].to_period("M")
    month_weeks = [t for t in Kw.index if t.to_period("M") == month]
    # The monthly bar is final only once the last session of the month is in the data.
    month_complete = (close.index[-1] + pd.offsets.BDay(1)).to_period("M") != month

    meta = fund.set_index("Ticker")
    last = close.iloc[-1]
    ret = lambda n: (last / close.iloc[-1 - n] - 1) * 100 if len(close) > n else pd.Series(np.nan, index=close.columns)
    ma50 = close.rolling(50, min_periods=50).mean().iloc[-1]
    ma200 = close.rolling(200, min_periods=200).mean().iloc[-1]
    hi52 = close.rolling(252, min_periods=min(252, len(close))).max().iloc[-1]
    sector_fpe = fund.groupby("Sector")["Forward P/E Ratio"].median()

    # Largest one-day move inside the event window, as a candidate cause.
    win = close.iloc[-(EVENT_WINDOW + 1):]
    chg = win.pct_change().iloc[1:]
    big_day = chg.abs().idxmax()
    big_move = pd.Series({t: chg.at[big_day[t], t] if pd.notna(big_day[t]) else np.nan for t in chg.columns})

    events = pd.read_csv(args.events, encoding=ENC) if Path(args.events).exists() else pd.DataFrame()

    def events_for(tk: str) -> list:
        if events.empty:
            return []
        hits = events[events["tickers"].fillna("").str.split("|").apply(lambda xs: tk in xs)]
        return hits["id"].tolist()

    rows = []
    for kind in ("down", "up"):
        wk = crosses_in(Kw, Dw, month_weeks, kind)
        mo = crosses_in(Km, Dm, [Km.index[-1]], kind)
        both = wk.index.intersection(mo.index)
        for tk in both:
            w, m = wk.loc[tk], mo.loc[tk]
            hi_ok = {z: (w.k_before >= hi and m.k_before >= hi) for z, (hi, lo) in ZONES.items()}
            lo_ok = {z: (w.k_before <= lo and m.k_before <= lo) for z, (hi, lo) in ZONES.items()}
            ok = hi_ok if kind == "down" else lo_ok
            zone = "primary" if ok["primary"] else ("watch" if ok["watch"] else None)
            if zone is None:
                continue
            sec = meta.at[tk, "Sector"] if tk in meta.index else "unknown"
            fpe = meta.at[tk, "Forward P/E Ratio"] if tk in meta.index else np.nan
            bd = big_day.get(tk)
            mv = big_move.get(tk)
            rows.append({
                "Ticker": tk, "kind": kind, "zone": zone,
                "name": meta.at[tk, "Short Name"] if tk in meta.index else "",
                "Sector": sec, "Industry": meta.at[tk, "Industry"] if tk in meta.index else "",
                "w_bar": w.bar, "w_k_before": w.k_before, "w_k": w.k, "w_d": w.d,
                "m_bar": m.bar, "m_k_before": m.k_before, "m_k": m.k, "m_d": m.d,
                "ret_1m": ret(21).get(tk), "ret_3m": ret(63).get(tk), "ret_12m": ret(252).get(tk),
                "pct_from_52wh": 100 * (last[tk] / hi52[tk] - 1),
                "above_50dma": bool(last[tk] > ma50[tk]) if pd.notna(ma50[tk]) else None,
                "above_200dma": bool(last[tk] > ma200[tk]) if pd.notna(ma200[tk]) else None,
                "fwd_pe": fpe, "sector_fwd_pe": sector_fpe.get(sec),
                "ny_growth": (meta.at[tk, "NextY成長"] * 100) if tk in meta.index and pd.notna(meta.at[tk, "NextY成長"]) else np.nan,
                "big_move_date": bd.date().isoformat() if pd.notna(bd) and abs(mv) >= BIG_MOVE else None,
                "big_move": 100 * mv if pd.notna(mv) and abs(mv) >= BIG_MOVE else None,
                "event_ids": "|".join(events_for(tk)),
            })
    crosses = pd.DataFrame(rows)
    crosses.to_csv(out_dir / "kd_crosses.csv", index=False, encoding=ENC)

    # Universe baseline, so each group's factors can be read against the market as a whole.
    universe = pd.DataFrame({
        "ret_1m": ret(21), "ret_3m": ret(63), "ret_12m": ret(252),
        "pct_from_52wh": 100 * (last / hi52 - 1),
    })
    base = {
        "n": int(close.shape[1]),
        "ret_1m": float(universe["ret_1m"].median()), "ret_3m": float(universe["ret_3m"].median()),
        "ret_12m": float(universe["ret_12m"].median()), "pct_from_52wh": float(universe["pct_from_52wh"].median()),
        "fwd_pe": float(fund["Forward P/E Ratio"].median()),
        "ny_growth": float(fund["NextY成長"].median() * 100),
        "sector_share": (fund["Sector"].value_counts(normalize=True) * 100).round(1).to_dict(),
    }

    def series(tks: list, K: pd.DataFrame, D: pd.DataFrame, n: int) -> dict:
        idx = K.index[-n:]
        return {
            "dates": [t.date().isoformat() for t in idx],
            "data": {tk: {"k": [None if pd.isna(v) else round(float(v), 1) for v in K.loc[idx, tk]],
                          "d": [None if pd.isna(v) else round(float(v), 1) for v in D.loc[idx, tk]]}
                     for tk in tks},
        }

    # What each event's named tickers did on that session, from our own closes --
    # so the report states the move it measured, not the figure an article quoted.
    day_chg = close.pct_change() * 100
    event_moves = {}
    for _, ev in events.iterrows() if not events.empty else []:
        when = pd.Timestamp(ev["date"])
        if when not in day_chg.index or pd.isna(ev.get("tickers")):
            continue
        moves = {tk: round(float(day_chg.at[when, tk]), 1)
                 for tk in str(ev["tickers"]).split("|") if tk in day_chg.columns and pd.notna(day_chg.at[when, tk])}
        if moves:
            event_moves[ev["id"]] = moves

    tks = crosses["Ticker"].tolist() if len(crosses) else []
    bundle = {
        "params": {"n": KD_N, "zones": ZONES, "event_window": EVENT_WINDOW, "big_move_pct": BIG_MOVE * 100},
        "month": str(month), "month_complete": bool(month_complete),
        "month_weeks": [t.date().isoformat() for t in month_weeks],
        "last_weekly_bar": Kw.index[-1].date().isoformat(),
        "event_moves": event_moves,
        "universe": base,
        "weekly_series": series(tks, Kw, Dw, 30),
        "monthly_series": series(tks, Km, Dm, 18),
        "scan": {
            "weekly_down": int(crosses_in(Kw, Dw, [Kw.index[-1]], "down").shape[0]),
            "weekly_up": int(crosses_in(Kw, Dw, [Kw.index[-1]], "up").shape[0]),
            "monthly_down": int(crosses_in(Km, Dm, [Km.index[-1]], "down").shape[0]),
            "monthly_up": int(crosses_in(Km, Dm, [Km.index[-1]], "up").shape[0]),
        },
    }
    with open(out_dir / "kd_bundle.json", "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, ensure_ascii=False, indent=1, default=str)

    for kind, label in (("down", "high-zone cross down"), ("up", "low-zone cross up")):
        sub = crosses[crosses["kind"] == kind] if len(crosses) else crosses
        for zone in ZONES:
            names = sub[sub["zone"] == zone]["Ticker"].tolist() if len(sub) else []
            print(f"{label} [{zone} {ZONES[zone]}]: {len(names)} {names}")
    print(f"monthly bar {month} {'complete' if month_complete else 'still in progress'}; "
          f"weekly bars checked: {bundle['month_weeks']}")


if __name__ == "__main__":
    main()
