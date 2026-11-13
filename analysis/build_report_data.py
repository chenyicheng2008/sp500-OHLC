"""Condense the analysis CSVs into the single JSON payload the HTML report embeds.

Run ``analysis/breadth_sector.py`` first.

Usage:
    python analysis/build_report_data.py [--in-dir data/analysis] [--out data/analysis/report_data.json]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
ENC = "utf-8-sig"

# Chart window: one year of sessions, sampled weekly so the lines stay readable.
CHART_DAYS = 260

# Candlestick window: the last two weeks of sessions, plus the close before them as the base.
CANDLE_DAYS = 10


def pct_rank(series: pd.Series, window: int = 252) -> float:
    """Where today's reading sits inside its own trailing range, 0-100."""
    s = series.dropna().tail(window)
    if s.empty:
        return float("nan")
    return float(100 * (s < s.iloc[-1]).mean())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-dir", default=str(REPO / "data" / "analysis"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    d = Path(args.in_dir)
    out = Path(args.out) if args.out else d / "report_data.json"

    b = pd.read_csv(d / "breadth_daily.csv", index_col=0, parse_dates=True)
    read = lambda n: pd.read_csv(d / n).replace({np.nan: None})
    bundle = json.load(open(d / "analysis_bundle.json", encoding="utf-8"))

    # The two halves of the breadth-vs-index divergence, so the report can state
    # them rather than repeat a number that was true on some earlier run.
    cw = b["cap_weighted"]
    idx_pctile = float(100 * (cw.tail(126) <= cw.iloc[-1]).mean())
    brd_pctile = float(100 * (b["pct_above_200dma"].tail(126) <= b["pct_above_200dma"].iloc[-1]).mean())

    tail = b.tail(CHART_DAYS)
    wk = tail.resample("W-FRI").last().dropna(how="all")

    def series(col: str, rebase: bool = False) -> list:
        s = wk[col]
        if rebase:
            s = 100 * s / s.iloc[0]
        return [None if pd.isna(v) else round(float(v), 2) for v in s]

    ma_cols = ["pct_above_20dma", "pct_above_50dma", "pct_above_150dma", "pct_above_200dma"]
    payload = {
        "asof": str(b.index[-1].date()),
        "generated": dt.date.today().isoformat(),
        "n_tickers": bundle["n_tickers"],
        "n_daily_bars": bundle["n_daily_bars"],
        "daily_start": bundle["daily_start"],
        "excluded": bundle["excluded"],
        "divergence": {"index_pctile": round(idx_pctile, 1), "breadth_pctile": round(brd_pctile, 1)},
        "cap_off_high": round(float(100 * (cw.iloc[-1] / cw.max() - 1)), 2),
        "dates": [x.strftime("%Y-%m-%d") for x in wk.index],
        "ma20": series("pct_above_20dma"),
        "ma50": series("pct_above_50dma"),
        "ma200": series("pct_above_200dma"),
        "adline": [None if pd.isna(v) else round(float(v)) for v in wk["ad_line"]],
        "capw": series("cap_weighted", rebase=True),
        "eqw": series("equal_weighted", rebase=True),
        "nethl": [None if pd.isna(v) else round(float(v), 1) for v in wk["net_hl_10d"]],
        "latest": {
            c: (None if pd.isna(b[c].iloc[-1]) else round(float(b[c].iloc[-1]), 2))
            for c in ma_cols + ["new_highs", "new_lows", "net_hl", "net_hl_10d",
                                "mcclellan_osc", "breadth_thrust", "ad_line",
                                "cap_weighted", "equal_weighted"]
        },
        "pctile": {c: round(pct_rank(b[c]), 1) for c in ma_cols},
        "range1y": {
            c: {"min": round(float(b[c].dropna().tail(252).min()), 1),
                "med": round(float(b[c].dropna().tail(252).median()), 1),
                "max": round(float(b[c].dropna().tail(252).max()), 1)}
            for c in ma_cols
        },
        "adline_peak": {
            "val": round(float(b["ad_line"].max())),
            "date": str(b["ad_line"].idxmax().date()),
            "now": round(float(b["ad_line"].iloc[-1])),
        },
        "cap_peak": {"val": round(float(b["cap_weighted"].max()), 1),
                     "date": str(b["cap_weighted"].idxmax().date())},
        "signals": read("breadth_signals.csv").to_dict("records"),
        "participation": read("breadth_participation.csv").round(1).to_dict("records"),
        "drawdown": read("breadth_drawdown_buckets.csv").round(1).to_dict("records"),
        "concentration": json.load(open(d / "analysis_bundle.json", encoding="utf-8"))["concentration"],
        "sector": read("sector_summary.csv").round(2).to_dict("records"),
        # simulated semiconductor "sector" (a subset of technology), shown beside the 11
        "sector_sim": read("sector_semi_sim.csv").round(2).to_dict("records") if (d / "sector_semi_sim.csv").exists() else [],
        "rotation": read("sector_rotation.csv").round(1).to_dict("records"),
        "industry": read("industry_summary.csv").round(1).to_dict("records"),
        "leaders": read("leaders_3m.csv").round(1).to_dict("records"),
        "laggards": read("laggards_3m.csv").round(1).to_dict("records"),
    }

    # --- two-week candles, rebased so the close before the window = 100 ---------
    c = pd.read_csv(d / "index_ohlc_daily.csv", index_col=0, parse_dates=True).tail(CANDLE_DAYS + 1)
    base = float(c["Close"].iloc[0])
    payload["candles"] = {
        "base_date": c.index[0].date().isoformat(),
        "bars": [
            {"date": t.date().isoformat(),
             **{k.lower()[0]: round(100 * float(c.at[t, k]) / base, 3) for k in ("Open", "High", "Low", "Close")},
             "chg": round(100 * (float(c.at[t, "Close"]) / float(c["Close"].iloc[i]) - 1), 2),
             "adv": int(c.at[t, "advances"]), "dec": int(c.at[t, "declines"])}
            for i, t in enumerate(c.index[1:])
        ],
    }

    # --- catalogued events: inside the candle window, plus anything still ahead -----
    ev_path = REPO / "data" / "events" / "market_events.csv"
    events = pd.read_csv(ev_path, encoding=ENC).replace({np.nan: None}) if ev_path.exists() else pd.DataFrame()
    first = payload["candles"]["bars"][0]["date"]
    payload["events_all"] = events.to_dict("records") if len(events) else []
    if len(events):
        events = events[events["date"] >= first].sort_values(["date", "id"])
        events["upcoming"] = events["date"] > payload["asof"]
        payload["events"] = events.to_dict("records")
    else:
        payload["events"] = []

    # --- weekly + monthly KD crosses (kd_signals.py) ------------------------------
    kd_csv, kd_json = d / "kd_crosses.csv", d / "kd_bundle.json"
    if kd_csv.exists() and kd_json.exists():
        kb = json.load(open(kd_json, encoding="utf-8"))
        kb["crosses"] = pd.read_csv(kd_csv, encoding=ENC).round(2).replace({np.nan: None}).to_dict("records")
        payload["kd"] = kb

    # --- AI-concept (or sector) bull / bear regime (trend_regime.py) ------------------------------
    tr_json = d / "trend_regime_bundle.json"
    if tr_json.exists():
        tr = json.load(open(tr_json, encoding="utf-8"))
        td = pd.read_csv(d / "trend_regime_daily.csv", index_col=0, parse_dates=True)
        tw = pd.read_csv(d / "trend_regime_weekly.csv", index_col=0, parse_dates=True)
        col = lambda df, c: [None if pd.isna(v) else round(float(v), 1) for v in df[c]]
        tr["daily"] = {"dates": [x.strftime("%Y-%m-%d") for x in td.index],
                       **{c: col(td, c) for c in ("sec_bull", "sec_neither", "sec_bear", "sec_net", "mkt_net")}}
        tr["weekly"] = {"dates": [x.strftime("%Y-%m-%d") for x in tw.index],
                        **{c: col(tw, c) for c in ("sec_net", "mkt_net")},
                        "n_start": int(tw["sec_n"].iloc[0]), "n_end": int(tw["sec_n"].iloc[-1])}
        tr["latest"] = {c: round(float(td[c].iloc[-1]), 1)
                        for c in ("sec_bull", "sec_neither", "sec_bear", "sec_net", "mkt_bull", "mkt_bear", "mkt_net")}
        tr["weekly_latest"] = {c: round(float(tw[c].iloc[-1]), 1) for c in ("sec_net", "mkt_net")}
        tr["groups"] = read("trend_regime_groups.csv").to_dict("records")
        payload["trend"] = tr

    # --- long weekly breadth + rebuilt / official indices (breadth_sector.long_weekly) ---
    # S&P 500 as a whole, and the technology sector alone (the same 83 names as the rebuilt
    # tech index in 預警檢驗)
    def ma_payload(weekly_csv, daily_df):
        lw = pd.read_csv(weekly_csv, index_col=0, parse_dates=True)
        r1 = lambda v: None if pd.isna(v) else round(float(v), 1)
        trio = (("p4", "pct_above_4w"), ("p10", "pct_above_10w"), ("p40", "pct_above_40w"))
        ml = {"dates": [x.strftime("%Y-%m-%d") for x in lw.index],
              **{k: [r1(v) for v in lw[c]] for k, c in (("cw", "cap_weighted"), ("ew", "equal_weighted"), *trio,
                 ("off_cw", "official_cw"), ("off_ew", "official_ew")) if c in lw},
              "n_min": int(lw["n_valid"].min()), "n_max": int(lw["n_valid"].max()),
              "partial": bool(lw.index[-1] > pd.Timestamp(payload["asof"])),
              "pctile": {k: round(float(100 * (lw[c] < lw[c].iloc[-1]).mean()), 0) for k, c in trio},
              "median": {k: round(float(lw[c].median()), 1) for k, c in trio}}
        # the daily view at full resolution (the 1-year chart series above are thinned)
        bd = daily_df[daily_df["pct_above_20dma"].notna()]
        ml["daily"] = {"dates": [x.strftime("%Y-%m-%d") for x in bd.index],
                       "cw": [r1(100 * v / bd["cap_weighted"].iloc[0]) for v in bd["cap_weighted"]],
                       "ew": [r1(100 * v / bd["equal_weighted"].iloc[0]) for v in bd["equal_weighted"]],
                       **{k: [r1(v) for v in bd[c]] for k, c in (("p20", "pct_above_20dma"), ("p50", "pct_above_50dma"),
                                                                 ("p200", "pct_above_200dma"))}}
        return ml

    if (d / "breadth_long_weekly.csv").exists():
        payload["ma_long"] = ma_payload(d / "breadth_long_weekly.csv", b)
    if (d / "breadth_long_weekly_tech.csv").exists():
        payload["ma_long_tech"] = ma_payload(d / "breadth_long_weekly_tech.csv",
                                             pd.read_csv(d / "breadth_daily_tech.csv", index_col=0, parse_dates=True))
        payload["ma_long_tech"]["n"] = payload["ma_long_tech"]["n_max"]
    if (d / "breadth_long_weekly_semi.csv").exists():
        payload["ma_long_semi"] = ma_payload(d / "breadth_long_weekly_semi.csv",
                                             pd.read_csv(d / "breadth_daily_semi.csv", index_col=0, parse_dates=True))
        payload["ma_long_semi"]["n"] = payload["ma_long_semi"]["n_max"]

    # --- does the regime net warn of large falls? (regime_backtest.py) -------------
    bt_json = d / "regime_backtest.json"
    if bt_json.exists():
        bt = json.load(open(bt_json, encoding="utf-8"))
        bw = pd.read_csv(d / "regime_backtest_weekly.csv", index_col=0, parse_dates=True)
        bt["weekly"] = {"dates": [x.strftime("%Y-%m-%d") for x in bw.index],
                        **{c: [None if pd.isna(v) else round(float(v), 1) for v in bw[c]]
                           for c in ("net", "tech", "semi", "aihw", "tech_dd", "semi_dd", "aihw_dd", "tech_off", "tech_off_dd") if c in bw}}
        payload["backtest"] = bt

    txt = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    out.write_text(txt, encoding="utf-8")
    print(f"wrote {out} ({len(txt):,} bytes, {len(wk)} chart points)")


if __name__ == "__main__":
    main()
