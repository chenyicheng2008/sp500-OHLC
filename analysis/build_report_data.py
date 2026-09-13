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
        "rotation": read("sector_rotation.csv").round(1).to_dict("records"),
        "industry": read("industry_summary.csv").round(1).to_dict("records"),
        "leaders": read("leaders_3m.csv").round(1).to_dict("records"),
        "laggards": read("laggards_3m.csv").round(1).to_dict("records"),
    }

    txt = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    out.write_text(txt, encoding="utf-8")
    print(f"wrote {out} ({len(txt):,} bytes, {len(wk)} chart points)")


if __name__ == "__main__":
    main()
