"""Does the AI-hardware bull/bear net warn of large falls in tech and semiconductors?

Reads the weekly net written by ``trend_regime.py`` and sets it against two weekly
indices rebuilt from our own closes:

    tech    Yahoo sector ``technology``                         (S&P 500 members)
    semi    Yahoo industries ``semiconductors`` + ``semiconductor-equipment-materials``

Both are cap-weighted with shares = latest market cap / latest close, held constant,
and chain-linked week to week so a name entering the data does not jump the level.
Today's constituents only -- survivorship bias, same as the regime's long run.

Outputs ``regime_backtest_weekly.csv`` (the time series for the chart) and
``regime_backtest.json`` (correlations, net-bucket table, signal tests, drawdown
episodes, current reading). Every window here overlaps its neighbours, so the
counts are descriptive, not significance tests; the bundle carries the number of
non-overlapping windows so the page can say how small the sample really is.

Run after ``trend_regime.py``.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from breadth_sector import ENC, load, pivot, drop_empty_sessions
from trend_regime import classify, DAILY_MA

REPO = Path(__file__).resolve().parent.parent
H = 13                      # forward / backward horizon, weeks
BIG_DROP = -0.10            # "large fall": max drawdown within the next H weeks
EPISODE_DD = -0.15          # peak-to-trough drawdown that counts as an episode
# Cycles: a turning point is confirmed once the series reverses by at least R from it
# (zig-zag). The answer depends on R, so several are reported; MAIN_SWING drives the chart.
SPREAD_SWINGS = (40, 60, 80)          # points of 多空排列差
MAIN_SWING = 60
INDEX_SWING = 0.15                    # index reversal, same size as an episode
# Divergence between the spread's highs and the index's highs (asked 2026-11-09).
# A spread high = the highest reading within ±DIV_K weeks, at least DIV_LEVEL. For two
# consecutive highs, the index high "at" each is its max within ±DIV_W weeks.
#   A ("多空強、指數弱"): spread holds or rises (≥ previous − DIV_TOL) but the index does not
#     clear the previous high -- the pattern the user described.
#   B ("指數強、多空弱", classic top divergence): index makes a higher high while the spread's
#     high is more than DIV_TOL lower.
DIV_K, DIV_LEVEL, DIV_W, DIV_TOL = 6, 40, 3, 5
# Horizons for "what came after": the eye judges a divergence over about a year, so the
# max dip is reported at 13/26/52 weeks, against every week the index sat at its high
# (within AT_HIGH of its running high) -- B requires an index high, so that is the fair base.
DIV_HORIZONS = (13, 26, 52)
AT_HIGH = 0.01
BUCKETS = [-101, -50, -20, 20, 50, 80, 101]
INDICES = {
    "tech": ("科技類股", lambda m: m["Sector"] == "technology"),
    "semi": ("半導體（含設備）", lambda m: m["Industry"].isin(["semiconductors", "semiconductor-equipment-materials"])),
}


# Official counterparts, fetched by the daily job into index_ohlc.csv (asked 2026-11-13:
# 「加抓 ^SP500-45 官方指數並列比較」). Drawn beside the rebuilt index and compared in a
# table; the rebuilt one still drives every statistic, so the long run stays comparable.
OFFICIAL = {"tech": ("^SP500-45", "S&P 500 資訊科技（官方）")}


def official_weekly(data_dir: Path, sym: str):
    """Weekly (W-FRI) closes of an official index from index_ohlc.csv, or None if absent."""
    p = data_dir / "index_ohlc.csv"
    if not p.exists():
        return None
    io = pd.read_csv(p, encoding=ENC)
    io["Date"] = pd.to_datetime(io["Date"])
    s = io[io["Ticker"] == sym].set_index("Date")["Close"].dropna().sort_index()
    if s.empty:
        return None
    return s, s.resample("W-FRI").last().dropna()


def compare_official(df: pd.DataFrame, key: str, daily_last, off_daily: pd.Series) -> dict:
    """Rebuilt vs official over their common weeks: returns, drawdown, tracking."""
    a, b = df[key], df[key + "_off"]
    both = a.notna() & b.notna()
    a, b = a[both], b[both]
    ra, rb_ = a.pct_change().dropna(), b.pct_change().dropna()
    diff = ra - rb_

    def ret(x, n):
        return round(float(100 * (x.iloc[-1] / x.iloc[-1 - n] - 1)), 1) if len(x) > n else None

    def side(x):
        return {"total": round(float(100 * (x.iloc[-1] / x.iloc[0] - 1)), 1), "ret_1y": ret(x, 52), "ret_13w": ret(x, 13),
                "dd_now": round(float(100 * (x.iloc[-1] / x.cummax().iloc[-1] - 1)), 1),
                "peak": x.idxmax().date().isoformat(),
                "max_dd": round(float(100 * (x / x.cummax() - 1).min()), 1)}
    return {"start": a.index[0].date().isoformat(), "end": a.index[-1].date().isoformat(), "weeks": int(len(a)),
            "official_last": off_daily.index[-1].date().isoformat(),
            "lags": bool(off_daily.index[-1] < daily_last),
            "rebuilt": side(a), "official": side(b),
            "corr_wk": round(float(ra.corr(rb_)), 3),
            "te_ann": round(float(100 * diff.std() * np.sqrt(52)), 1),
            "beta": round(float(np.cov(ra, rb_)[0, 1] / rb_.var()), 2)}


def weekly_closes(ohlc: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily, _ = drop_empty_sessions(pivot(ohlc, "1d", "Close"))
    wh, _ = drop_empty_sessions(pivot(ohlc, "1wk", "Close"))
    w = pd.concat([wh[wh.index < daily.index[0]].resample("W-FRI").last(), daily.resample("W-FRI").last()])
    return daily, w[~w.index.duplicated(keep="last")].dropna(how="all")


def chain_index(w: pd.DataFrame, shares: pd.Series, cols: list) -> pd.Series:
    """Cap-weighted, chain-linked: each week's return weights names by last week's cap."""
    px = w[cols]
    r = px.pct_change(fill_method=None)
    cap = px.mul(shares.reindex(cols), axis=1).shift(1)
    ok = r.notna() & cap.notna()
    ret = (r.where(ok) * cap.where(ok)).sum(axis=1) / cap.where(ok).sum(axis=1)
    return 100 * (1 + ret.fillna(0)).cumprod()


def fwd_max_dd(s: pd.Series, h: int = H) -> pd.Series:
    v, out = s.values, np.full(len(s), np.nan)
    for i in range(len(v) - h):
        out[i] = v[i + 1:i + h + 1].min() / v[i] - 1
    return pd.Series(out, index=s.index)


def rank_corr(a: pd.Series, b: pd.Series) -> float:
    ok = a.notna() & b.notna()
    return round(float(a[ok].rank().corr(b[ok].rank())), 2)


def declustered(cond: pd.Series, gap: int = H) -> list:
    """First week of each run of triggers; a new trigger needs `gap` quiet weeks."""
    out, last = [], None
    for t in cond.index[cond.fillna(False)]:
        if last is None or (t - last).days > 7 * gap:
            out.append(t)
            last = t
    return out


def episodes(level: pd.Series, net: pd.Series) -> list:
    """Peak-to-trough falls past EPISODE_DD, and when net first crossed below zero around them."""
    peak_v, peak_t, eps, cur = level.iloc[0], level.index[0], [], None
    for t, v in level.items():
        if v >= peak_v:
            if cur:                                    # back at a new high: the episode is over
                eps.append(cur); cur = None
            peak_v, peak_t = v, t
        elif cur is None and v / peak_v - 1 <= EPISODE_DD:
            cur = {"peak": peak_t, "open": False}
        if cur is not None:
            seg = level.loc[cur["peak"]:t]
            cur.update(trough=seg.idxmin(), depth=seg.min() / seg.iloc[0] - 1)
    if cur:                                            # still below the old high at the data date
        cur["open"] = True
        eps.append(cur)
    rows = []
    for e in eps:
        pk, tr = e["peak"], e["trough"]
        win = net.loc[pk - pd.Timedelta(weeks=H): tr]
        cross = win[(win <= 0) & (win.shift(1) > 0)].index
        c = cross.min() if len(cross) else None
        # the spread's own high in the year before the index peak; at the start of the series
        # the window is cut short, so the lead is unknown rather than zero
        prior = net.loc[pk - pd.Timedelta(weeks=52): pk]
        full = prior.index[0] > net.index[0] or pk - pd.Timedelta(weeks=52) >= net.index[0]
        rows.append({
            "peak": pk.date().isoformat(), "trough": tr.date().isoformat(), "depth": round(100 * e["depth"], 1),
            "spread_hi": round(float(prior.max()), 1) if full else None,
            "spread_hi_date": prior.idxmax().date().isoformat() if full else None,
            "spread_hi_lead": int((pk - prior.idxmax()).days // 7) if full else None,
            "ongoing": e["open"],
            "net_at_peak": round(float(net.get(pk, np.nan)), 1),
            "net_min": round(float(net.loc[pk:tr].min()), 1),
            "cross": c.date().isoformat() if c is not None else None,
            "lead_weeks": int((c - pk).days // 7) if c is not None else None,
            # index level at the cross relative to the peak, and what was still to come
            "at_cross": round(100 * (level[c] / level[pk] - 1), 1) if c is not None and c >= pk else None,
            "cross_to_peak": round(100 * (level[pk] / level[c] - 1), 1) if c is not None and c < pk else None,
            "cross_to_trough": round(100 * (level[tr] / level[c] - 1), 1) if c is not None else None,
        })
    return rows


def zigzag(v: np.ndarray, r: float) -> list:
    """Alternating turning points [(i, 'P'|'T')]: each confirmed by a reversal of at least r."""
    piv, hi, lo, trend = [], 0, 0, 0
    for i in range(1, len(v)):
        if trend >= 0 and v[i] > v[hi]:
            hi = i
        if trend <= 0 and v[i] < v[lo]:
            lo = i
        if trend >= 0 and v[hi] - v[i] >= r:
            piv.append((hi, "P")); trend, lo = -1, i
        elif trend <= 0 and v[i] - v[lo] >= r:
            piv.append((lo, "T")); trend, hi = 1, i
    return piv


def cycle_stats(piv: list) -> dict:
    P = [i for i, k in piv if k == "P"]
    T = [i for i, k in piv if k == "T"]
    pp, tt = np.diff(P), np.diff(T)
    up = [b[0] - a[0] for a, b in zip(piv, piv[1:]) if a[1] == "T"]
    dn = [b[0] - a[0] for a, b in zip(piv, piv[1:]) if a[1] == "P"]
    f = lambda x: round(float(x), 1)
    return {"n_peaks": len(P), "n_troughs": len(T), "n_cycles": len(pp),
            "pp": [int(x) for x in pp], "pp_mean": f(pp.mean()) if len(pp) else None,
            "pp_median": f(np.median(pp)) if len(pp) else None,
            "tt_mean": f(tt.mean()) if len(tt) else None, "tt_median": f(np.median(tt)) if len(tt) else None,
            "min": int(pp.min()) if len(pp) else None, "max": int(pp.max()) if len(pp) else None,
            "up_mean": f(np.mean(up)) if up else None, "down_mean": f(np.mean(dn)) if dn else None}


def cycle_study(df: pd.DataFrame) -> dict:
    """Average cycle of the spread under several swing sizes, against the indices' own cycles."""
    net = df["net"].values
    dates = [d.date().isoformat() for d in df.index]
    rows = []
    for r in SPREAD_SWINGS:
        rows.append({"series": "net", "swing": r, **cycle_stats(zigzag(net, r))})
    for k in INDICES:
        rows.append({"series": k, "swing": round(100 * INDEX_SWING),
                     **cycle_stats(zigzag(np.log(df[k].values), np.log(1 / (1 - INDEX_SWING))))})
    main = zigzag(net, MAIN_SWING)
    legs = []
    for (a, ka), (b, _) in zip(main, main[1:]):
        legs.append({"dir": "up" if ka == "T" else "down", "start": dates[a], "end": dates[b], "weeks": b - a,
                     "from": round(float(net[a]), 1), "to": round(float(net[b]), 1),
                     **{k: round(100 * float(df[k].iloc[b] / df[k].iloc[a] - 1), 1) for k in INDICES}})
    # the leg still open at the data date: from the last turning point to now (not confirmed)
    if main:
        a, ka = main[-1]
        legs.append({"dir": "down" if ka == "P" else "up", "start": dates[a], "end": None, "weeks": len(net) - 1 - a,
                     "from": round(float(net[a]), 1), "to": round(float(net[-1]), 1), "open": True,
                     **{k: round(100 * float(df[k].iloc[-1] / df[k].iloc[a] - 1), 1) for k in INDICES}})
    # autocorrelation: where the series best resembles itself again (a weak, model-free cycle estimate)
    x = pd.Series(net - net.mean())
    lags = range(1, min(260, len(net) // 2))
    ac = np.array([x.autocorr(l) for l in lags])
    zero = next((l for l, a in zip(lags, ac) if a < 0), None)
    lo_lag = int(np.argmin(ac)) + 1
    peaks = [(l, a) for l, a in zip(list(lags)[1:-1], ac[1:-1]) if l > lo_lag and a > ac[l - 2] and a >= ac[l]]
    best = max(peaks, key=lambda t: t[1]) if peaks else None
    return {"main_swing": MAIN_SWING, "index_swing": round(100 * INDEX_SWING), "table": rows,
            "pivots": [{"date": dates[i], "kind": k, "value": round(float(net[i]), 1)} for i, k in main],
            "legs": legs,
            "acf": {"zero": zero, "min_lag": lo_lag, "min": round(float(ac[lo_lag - 1]), 2),
                    "peak_lag": best[0] if best else None, "peak": round(float(best[1]), 2) if best else None}}


def constituents(daily: pd.DataFrame, meta: pd.DataFrame, tickers: list, group_of: dict) -> list:
    """One row per name: identity, size, its current MA alignment and recent moves."""
    px = daily[tickers]
    state = classify(px, *DAILY_MA).iloc[-1]
    lab = {1.0: "bull", 0.0: "neither", -1.0: "bear"}
    last = px.ffill().iloc[-1]
    m1 = last / px.ffill().iloc[-22] - 1
    hi = px.iloc[-252:].max()
    cap = meta["Market Cap"].reindex(tickers)
    tot = cap.sum()
    rows = []
    for t in tickers:
        rows.append({"ticker": t, "name": str(meta.at[t, "Short Name"]) if t in meta.index else t,
                     "group": group_of.get(t), "industry": meta.at[t, "Industry"] if t in meta.index else None,
                     "cap_bn": round(float(cap[t]) / 1e9, 1) if pd.notna(cap[t]) else None,
                     "weight": round(100 * float(cap[t] / tot), 2) if pd.notna(cap[t]) and tot else None,
                     "state": lab.get(state[t]) if pd.notna(state[t]) else None,
                     "ret_1m": round(100 * float(m1[t]), 1) if pd.notna(m1[t]) else None,
                     "from_high": round(100 * float(last[t] / hi[t] - 1), 1) if pd.notna(hi[t]) else None})
    return sorted(rows, key=lambda r: -(r["cap_bn"] or 0))


def spread_highs(net: np.ndarray) -> list:
    out = []
    for i in range(len(net)):
        win = net[max(0, i - DIV_K): i + DIV_K + 1]
        if net[i] >= DIV_LEVEL and net[i] == win.max() and (not out or i - out[-1] > DIV_K):
            out.append(i)
    return out


def divergence_study(df: pd.DataFrame) -> dict:
    net, n = df["net"].values, len(df)
    dates = [d.date().isoformat() for d in df.index]
    highs = spread_highs(net)
    res = {"k": DIV_K, "level": DIV_LEVEL, "w": DIV_W, "tol": DIV_TOL, "horizon": H,
           "highs": [{"date": dates[i], "value": round(float(net[i]), 1)} for i in highs], "by_index": {}}
    for k in INDICES:
        lv = df[k].values
        near = lambda i: max(range(max(0, i - DIV_W), min(n, i + DIV_W + 1)), key=lambda j: lv[j])
        def dip(i, h):          # max fall within h weeks after week i (None until h weeks have passed)
            return round(100 * float(lv[i:i + h + 1].min() / lv[i] - 1), 1) if i + h < n else None

        def weeks_down(i, thr):  # weeks until the index first sits thr below its level at week i
            hit = np.nonzero(lv[i:] / lv[i] - 1 <= thr)[0]
            return int(hit[0]) if len(hit) else None

        def after(b):
            done = b + 2 * H < n
            return {"complete": done,
                    "ret13": round(100 * float(lv[b + H] / lv[b] - 1), 1) if b + H < n else None,
                    "ret26": round(100 * float(lv[b + 2 * H] / lv[b] - 1), 1) if done else None,
                    "mdd26": round(100 * float(lv[b:min(n, b + 2 * H + 1)].min() / lv[b] - 1), 1),
                    **{f"dip{h}": dip(b, h) for h in DIV_HORIZONS},
                    "w5": weeks_down(b, -0.05), "w10": weeks_down(b, -0.10), "weeks_left": n - 1 - b,
                    # a high is only known once DIV_K more weeks have passed without a higher one
                    "confirm": dates[min(b + DIV_K, n - 1)], "confirm_pending": b + DIV_K > n - 1}
        rows, base = [], []
        for a, b in zip(highs, highs[1:]):
            ia, ib = near(a), near(b)
            hold, new_hi = net[b] >= net[a] - DIV_TOL, lv[ib] > lv[ia]
            typ = "A" if hold and not new_hi else "B" if new_hi and not hold else None
            out = after(b)
            base.append(out)
            if typ:
                rows.append({"type": typ, "h1": dates[a], "h1_val": round(float(net[a]), 1),
                             "h2": dates[b], "h2_val": round(float(net[b]), 1),
                             "i1": dates[ia], "i2": dates[ib], "i1_lvl": round(float(lv[ia]), 2), "i2_lvl": round(float(lv[ib]), 2),
                             "idx_chg": round(100 * float(lv[ib] / lv[ia] - 1), 1), **out})
        def summ(xs):
            done = [x for x in xs if x["complete"]]
            med = lambda key: round(float(np.median([x[key] for x in done])), 1) if done else None
            return {"n": len(xs), "n_done": len(done), "hits": sum(x["mdd26"] <= 100 * BIG_DROP for x in done),
                    "med_ret13": med("ret13"), "med_ret26": med("ret26"), "med_mdd26": med("mdd26")}
        def horizons(xs):       # median max dip and the share of ≥5% / ≥10% dips, per horizon
            out = {}
            for h in DIV_HORIZONS:
                v = np.array([x for x in xs if x is not None], dtype=float)
                out[str(h)] = {"n": int(len(v)),
                               "median": round(float(np.median(v)), 1) if len(v) else None,
                               "p5": round(100 * float((v <= -5).mean()), 1) if len(v) else None,
                               "p10": round(100 * float((v <= -10).mean()), 1) if len(v) else None}
            return out
        at_high = [i for i in range(n) if lv[i] >= (1 - AT_HIGH) * lv[:i + 1].max()]
        hz = {"at_high": {}, "A": {}, "B": {}}
        for h in DIV_HORIZONS:
            hz["at_high"][str(h)] = horizons([dip(i, h) for i in at_high])[str(h)]
            for t in ("A", "B"):
                hz[t][str(h)] = horizons([r[f"dip{h}"] for r in rows if r["type"] == t])[str(h)]
        res["by_index"][k] = {"rows": rows, "summary": {
            "A": summ([r for r in rows if r["type"] == "A"]), "B": summ([r for r in rows if r["type"] == "B"]),
            "all_highs": summ(base)}, "horizons": hz, "n_at_high": len(at_high)}
    res["horizons"] = list(DIV_HORIZONS)
    res["at_high"] = round(100 * AT_HIGH)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.environ.get("FETCH_BASE", str(REPO / "data" / "weekly_reutin")))
    ap.add_argument("--out-dir", default=str(REPO / "data" / "analysis"))
    args = ap.parse_args()
    out_dir = Path(args.out_dir)

    ohlc, fund, _ = load(Path(args.data_dir))
    daily, w = weekly_closes(ohlc)
    meta = fund.set_index("Ticker")
    last = daily.ffill().iloc[-1].reindex(meta.index)
    shares = (meta["Market Cap"] / last).replace([np.inf, -np.inf, 0], np.nan).dropna()

    reg = json.load(open(out_dir / "trend_regime_bundle.json", encoding="utf-8"))
    net = pd.read_csv(out_dir / "trend_regime_weekly.csv", index_col=0, parse_dates=True)["sec_net"]
    members = set(reg["group_of"])

    df = pd.DataFrame({"net": net})
    info = {}
    for key, (label, sel) in INDICES.items():
        cols = [t for t in meta.index[sel(meta)] if t in w.columns and t in shares.index]
        lvl = chain_index(w, shares, cols)
        df[key] = lvl
        overlap = [t for t in cols if t in members]
        info[key] = {"label": label, "n": len(cols), "overlap_n": len(overlap),
                     "overlap_cap": round(100 * float(meta.loc[overlap, "Market Cap"].sum() / meta.loc[cols, "Market Cap"].sum()), 0)}
    # The regime universe itself as an equal-weight index (asked 2026-11-13): each week the
    # mean return of the members priced both weeks, chain-linked, so a name that lists later
    # (SNDK, 2025-02) joins without a jump. Drawn on the timeline only -- it is built from
    # the same names the spread counts, so it is kept out of every warning statistic.
    ew_cols = [t for t in reg["group_of"] if t in w.columns]
    ew_ret = w[ew_cols].pct_change(fill_method=None).mean(axis=1)
    df["aihw"] = 100 * (1 + ew_ret.fillna(0)).cumprod()
    off_daily = {}
    for key, (sym, _) in OFFICIAL.items():
        got = official_weekly(Path(args.data_dir), sym)
        if got is not None:
            off_daily[key], df[key + "_off"] = got[0], got[1]
    df = df.dropna(subset=["net", "tech", "semi"])
    for key in off_daily:
        # start the official line on the rebuilt one, at the first week both exist
        k0 = df[key + "_off"].first_valid_index()
        df[key + "_off"] = df[key + "_off"] / df.loc[k0, key + "_off"] * 100
        df[key + "_off_dd"] = 100 * (df[key + "_off"] / df[key + "_off"].cummax() - 1)
    for key in list(INDICES) + ["aihw"]:
        df[key] = 100 * df[key] / df[key].iloc[0]                  # rebase to the first net week
        df[key + "_dd"] = 100 * (df[key] / df[key].cummax() - 1)

    for key in off_daily:          # official line rebased onto the rebuilt level at its first week
        k0 = df[key + "_off"].first_valid_index()
        df[key + "_off"] = df[key + "_off"] * df.loc[k0, key] / 100
    out = df[["net", "tech", "semi", "aihw", "tech_dd", "semi_dd", "aihw_dd"] +
             [c for k in OFFICIAL for c in (k + "_off", k + "_off_dd") if c in df]].round(2)
    out.index.name = "Date"
    out.to_csv(out_dir / "regime_backtest_weekly.csv", encoding=ENC)

    d4 = df["net"] - df["net"].shift(4)
    # The weekly bars are labelled with their Friday, so mid-week the last one is partial and
    # dated after the data. asof is the last *trading day*; the week label is kept separately.
    res = {"asof": daily.index[-1].date().isoformat(), "last_week": df.index[-1].date().isoformat(),
           "week_partial": bool(df.index[-1] > daily.index[-1]), "start": df.index[0].date().isoformat(),
           "weeks": len(df), "horizon": H, "big_drop": round(100 * BIG_DROP), "episode_dd": round(100 * EPISODE_DD),
           "universe_label": reg["universe"]["label"], "n_members": reg["n_members"],
           "indices": info, "independent_windows": len(df) // H, "by_index": {}}
    for key in INDICES:
        lvl = df[key]
        mdd, fr, past = fwd_max_dd(lvl), lvl.shift(-H) / lvl - 1, lvl / lvl.shift(H) - 1
        base = mdd.notna()
        near_high = lvl / lvl.cummax() - 1 > -0.03
        buckets = []
        cut = pd.cut(df["net"], BUCKETS)
        for iv, grp in df[base].groupby(cut[base], observed=True):
            m = mdd[grp.index]
            buckets.append({"lo": int(iv.left), "hi": int(iv.right), "weeks": len(grp),
                            "p_big": round(100 * float((m <= BIG_DROP).mean()), 1),
                            "med_fwd_ret": round(100 * float(fr[grp.index].median()), 1),
                            "med_fwd_mdd": round(100 * float(m.median()), 1)})
        signals = []
        for sid, label, cond in [
            ("cross0", "多空排列差由正轉負（跌破 0）", (df["net"] < 0) & (df["net"].shift(1) >= 0)),
            ("drop50", "4 週內多空排列差下降 50 點以上", d4 <= -50),
            ("diverge", "指數距高點 3% 以內，多空排列差卻 ≤ 0", near_high & (df["net"] <= 0)),
            ("deep40", "多空排列差跌破 -40", (df["net"] <= -40) & (df["net"].shift(1) > -40)),
        ]:
            idx = declustered(cond)
            done = [t for t in idx if base[t]]
            signals.append({"id": sid, "label": label, "n": len(idx), "n_done": len(done),
                            "hits": int(sum(mdd[t] <= BIG_DROP for t in done)),
                            "med_fwd_ret": round(100 * float(fr[done].median()), 1) if done else None,
                            "dates": [t.date().isoformat() for t in idx],
                            "pending": [t.date().isoformat() for t in idx if not base[t]]})
        res["by_index"][key] = {
            "base_p_big": round(100 * float((mdd[base] <= BIG_DROP).mean()), 1),
            "base_med_fwd_ret": round(100 * float(fr[base].median()), 1),
            "corr_past": rank_corr(df["net"], past), "corr_fwd_mdd": rank_corr(df["net"], mdd),
            "corr_fwd_ret": rank_corr(df["net"], fr),
            "buckets": buckets, "signals": signals, "episodes": episodes(lvl, df["net"]),
            "dd_now": round(float(df[key + "_dd"].iloc[-1]), 1),
            "peak": lvl.idxmax().date().isoformat(),
        }
    crosses = df.index[(df["net"] < 0) & (df["net"].shift(1) >= 0)]
    res["zero_crosses"] = [t.date().isoformat() for t in crosses]
    res["cycles"] = cycle_study(df)
    res["divergence"] = divergence_study(df)
    # constituent lists: the regime universe (every name counts once in the spread) and each
    # rebuilt index (cap-weighted)
    res["constituents"] = {"universe": constituents(daily, meta, [t for t in reg["group_of"] if t in daily.columns], reg["group_of"])}
    for key, (label, sel) in INDICES.items():
        cols = [t for t in meta.index[sel(meta)] if t in w.columns and t in shares.index]
        res["constituents"][key] = constituents(daily, meta, [t for t in cols if t in daily.columns], reg["group_of"])
    res["ew"] = {"label": reg["universe"]["label"] + "等權重", "n": len(ew_cols),
                 "n_start": int(w[ew_cols].loc[df.index[0]].notna().sum()),
                 "dd_now": round(float(df["aihw_dd"].iloc[-1]), 1),
                 "peak": df["aihw"].idxmax().date().isoformat(),
                 "ret_1y": round(float(100 * (df["aihw"].iloc[-1] / df["aihw"].iloc[-53] - 1)), 1),
                 "tech_ret_1y": round(float(100 * (df["tech"].iloc[-1] / df["tech"].iloc[-53] - 1)), 1),
                 "semi_ret_1y": round(float(100 * (df["semi"].iloc[-1] / df["semi"].iloc[-53] - 1)), 1)}
    res["official"] = {key: {"symbol": sym, "label": label, "available": key in off_daily,
                             **(compare_official(df, key, daily.index[-1], off_daily[key]) if key in off_daily else {})}
                       for key, (sym, label) in OFFICIAL.items()}
    res["net_now"] = round(float(df["net"].iloc[-1]), 1)
    res["d4_now"] = round(float(d4.iloc[-1]), 1)
    with open(out_dir / "regime_backtest.json", "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)

    print(f"backtest {res['start']} → {res['asof']}, {res['weeks']} weeks ({res['independent_windows']} non-overlapping {H}w windows)")
    for key, r in res["by_index"].items():
        print(f"  {key}: corr past {r['corr_past']} fwd-mdd {r['corr_fwd_mdd']} fwd-ret {r['corr_fwd_ret']}; "
              f"base P(≤{res['big_drop']}%) {r['base_p_big']}%; {len(r['episodes'])} episodes; dd now {r['dd_now']}%")
        for s in r["signals"]:
            print(f"    {s['id']}: {s['hits']}/{s['n_done']} hits, median fwd {s['med_fwd_ret']}%, pending {s['pending']}")
    for row in res["cycles"]["table"]:
        print(f"  cycle {row['series']} swing {row['swing']}: {row['n_cycles']} cycles, peak-peak mean {row['pp_mean']} "
              f"median {row['pp_median']} ({row['min']}-{row['max']}), up {row['up_mean']} down {row['down_mean']}")
    print(f"  acf: {res['cycles']['acf']}")
    print(f"  ew {res['ew']}")
    for k, o in res["official"].items():
        print(f"  official {k} {o['symbol']}: " + (f"{o['weeks']}w, corr {o['corr_wk']}, TE {o['te_ann']}%, beta {o['beta']}, "
              f"1y rebuilt {o['rebuilt']['ret_1y']}% vs official {o['official']['ret_1y']}%, dd {o['rebuilt']['dd_now']} vs "
              f"{o['official']['dd_now']}" if o["available"] else "index_ohlc.csv missing -- not compared"))
    for k, v in res["divergence"]["by_index"].items():
        print(f"  divergence {k}: " + ", ".join(f"{t} {s['n']} ({s['hits']}/{s['n_done']} fell ≥{-round(100*BIG_DROP)}% in 26w, "
              f"median 26w {s['med_ret26']}%)" for t, s in v["summary"].items()))

if __name__ == "__main__":
    main()
