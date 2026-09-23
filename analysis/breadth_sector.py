"""S&P 500 breadth + sector/industry analysis.

Reads the OHLC and fundamentals CSVs produced by ``fetch_sp500_memory_software.py``
and writes a set of analysis CSVs (plus a JSON bundle for the HTML report) into
``data/analysis``.

Breadth is computed on the daily portion of ``sp500_ohlc.csv`` (the most recent
~2 years); the 10 years of weekly bars before that are used only for the long
term equal-weight vs cap-weight context series.

Usage:
    python analysis/breadth_sector.py [--data-dir data/weekly_reutin] [--out-dir data/analysis]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
ENC = "utf-8-sig"

# Horizons in trading days used throughout the report.
HORIZONS = {"1W": 5, "1M": 21, "3M": 63, "6M": 126, "12M": 252}

# Yahoo sector slugs -> display names, and a defensive/cyclical tag.
SECTOR_LABELS = {
    "technology": "Technology",
    "industrials": "Industrials",
    "financial-services": "Financial Services",
    "healthcare": "Healthcare",
    "consumer-cyclical": "Consumer Cyclical",
    "consumer-defensive": "Consumer Defensive",
    "utilities": "Utilities",
    "real-estate": "Real Estate",
    "communication-services": "Communication Services",
    "energy": "Energy",
    "basic-materials": "Basic Materials",
}
DEFENSIVE = {"consumer-defensive", "utilities", "healthcare", "real-estate"}

# yfinance occasionally returns a blank sector/industry; patch the few we know.
SECTOR_OVERRIDES = {"FISV": ("financial-services", "financial-data-stock-exchanges")}

# A name needs at least this many daily bars to be counted in breadth/returns;
# below it the series is a stub (delisted, or a Yahoo glitch) and only adds noise.
MIN_DAILY_BARS = 60


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def load(data_dir: Path):
    ohlc = pd.read_csv(data_dir / "sp500_ohlc.csv", encoding=ENC)
    ohlc["Date"] = pd.to_datetime(ohlc["Date"])
    fund = pd.read_csv(data_dir / "sp500_stocks.csv", encoding=ENC)
    for tkr, (sec, ind) in SECTOR_OVERRIDES.items():
        m = fund["Ticker"] == tkr
        fund.loc[m & fund["Sector"].isna(), "Sector"] = sec
        fund.loc[m & fund["Industry"].isna(), "Industry"] = ind

    # Drop names with no usable price history -- nothing can be computed from a
    # stub series, and they would show up as phantom members in the group tables.
    bars = ohlc[ohlc["Interval"] == "1d"].groupby("Ticker").size()
    usable = set(bars[bars >= MIN_DAILY_BARS].index)
    dropped = fund[~fund["Ticker"].isin(usable)]["Ticker"].tolist()
    if dropped:
        print(f"excluding {len(dropped)} ticker(s) with too little price history: {dropped}")
    fund = fund[~fund["Ticker"].isin(dropped)].copy()
    ohlc = ohlc[~ohlc["Ticker"].isin(dropped)].copy()

    # A missing market cap is a separate problem: yfinance intermittently returns 0
    # for a perfectly good name. Such a ticker keeps its price history and stays in
    # breadth, equal-weight and median stats -- it only drops out of anything
    # cap-weighted, where its implied share count is 0 and contributes nothing.
    no_cap = fund[fund["Market Cap"] <= 0]["Ticker"].tolist()
    if no_cap:
        print(f"no market cap (excluded from cap-weighted figures only): {no_cap}")

    fund["Sector"] = fund["Sector"].fillna("unknown")
    fund["Industry"] = fund["Industry"].fillna("unknown")
    return ohlc, fund, {"no_history": dropped, "no_cap": no_cap}


def pivot(ohlc: pd.DataFrame, interval: str, field: str) -> pd.DataFrame:
    sub = ohlc[ohlc["Interval"] == interval]
    return sub.pivot_table(index="Date", columns="Ticker", values=field).sort_index()


# --------------------------------------------------------------------------- #
# breadth
# --------------------------------------------------------------------------- #
def moving_average_breadth(close: pd.DataFrame) -> pd.DataFrame:
    """% of constituents trading above their 20/50/150/200 day moving average."""
    out = {}
    for n in (20, 50, 150, 200):
        ma = close.rolling(n, min_periods=n).mean()
        above = (close > ma) & close.notna() & ma.notna()
        valid = close.notna() & ma.notna()
        out[f"pct_above_{n}dma"] = 100 * above.sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)
    res = pd.DataFrame(out)
    res["n_valid_200"] = (close.notna() & close.rolling(200, min_periods=200).mean().notna()).sum(axis=1)
    return res


def advance_decline(close: pd.DataFrame) -> pd.DataFrame:
    """A/D line, A/D ratio, McClellan oscillator + summation index, breadth thrust."""
    chg = close.diff()
    adv = (chg > 0).sum(axis=1)
    dec = (chg < 0).sum(axis=1)
    unch = (chg == 0).sum(axis=1)
    total = adv + dec + unch
    net = adv - dec

    df = pd.DataFrame({"advances": adv, "declines": dec, "unchanged": unch, "net_advances": net})
    df["ad_line"] = net.cumsum()
    df["ad_ratio"] = adv / dec.replace(0, np.nan)
    # McClellan works on the ratio-adjusted net advances so it stays comparable
    # across a changing number of issues.
    rana = 1000 * net / total.replace(0, np.nan)
    df["mcclellan_osc"] = rana.ewm(span=19, adjust=False).mean() - rana.ewm(span=39, adjust=False).mean()
    df["mcclellan_sum"] = df["mcclellan_osc"].cumsum()
    # Zweig breadth thrust: 10-day EMA of advances / (advances + declines).
    df["breadth_thrust"] = (adv / (adv + dec).replace(0, np.nan)).ewm(span=10, adjust=False).mean()
    return df


def new_highs_lows(close: pd.DataFrame, window: int = 252) -> pd.DataFrame:
    """52-week new highs / new lows and the net high-low differential."""
    roll_max = close.rolling(window, min_periods=window).max()
    roll_min = close.rolling(window, min_periods=window).min()
    nh = (close >= roll_max) & roll_max.notna()
    nl = (close <= roll_min) & roll_min.notna()
    df = pd.DataFrame({"new_highs": nh.sum(axis=1), "new_lows": nl.sum(axis=1)})
    df["net_hl"] = df["new_highs"] - df["new_lows"]
    df["net_hl_10d"] = df["net_hl"].rolling(10).mean()
    df["pct_from_52w_high_median"] = 100 * (close / roll_max - 1).median(axis=1)
    return df


def index_series(close: pd.DataFrame, shares: pd.Series) -> pd.DataFrame:
    """Cap-weighted and equal-weighted index levels rebased to 100."""
    cols = [c for c in close.columns if c in shares.index]
    px = close[cols]
    cap = px.mul(shares[cols], axis=1)
    capw = cap.sum(axis=1, min_count=1)
    # Equal weight = compounded cross-sectional mean daily return.
    ew_ret = px.pct_change().mean(axis=1)
    eqw = (1 + ew_ret.fillna(0)).cumprod()
    df = pd.DataFrame({"cap_weighted": 100 * capw / capw.iloc[0], "equal_weighted": 100 * eqw / eqw.iloc[0]})
    df["ew_minus_cw"] = df["equal_weighted"] - df["cap_weighted"]
    df["ew_cw_ratio"] = df["equal_weighted"] / df["cap_weighted"]
    return df


def participation(close: pd.DataFrame) -> pd.DataFrame:
    """Share of constituents with a positive return over each horizon, plus the
    mean/median gap that shows how top-heavy the move is."""
    rows = []
    for name, n in HORIZONS.items():
        if len(close) <= n:
            continue
        ret = close.iloc[-1] / close.iloc[-1 - n] - 1
        ret = ret.dropna()
        rows.append(
            {
                "horizon": name,
                "days": n,
                "n": len(ret),
                "pct_positive": 100 * (ret > 0).mean(),
                "mean_ret": 100 * ret.mean(),
                "median_ret": 100 * ret.median(),
                "mean_minus_median": 100 * (ret.mean() - ret.median()),
                "pct_beat_index": np.nan,  # filled by caller
                "p10": 100 * ret.quantile(0.10),
                "p90": 100 * ret.quantile(0.90),
                "dispersion_p90_p10": 100 * (ret.quantile(0.90) - ret.quantile(0.10)),
            }
        )
    return pd.DataFrame(rows)


def drawdown_buckets(close: pd.DataFrame, window: int = 252) -> pd.DataFrame:
    """How far each constituent sits below its 52-week high, in buckets."""
    roll_max = close.rolling(window, min_periods=min(window, len(close))).max()
    dd = (close.iloc[-1] / roll_max.iloc[-1] - 1).dropna() * 100
    edges = [-100, -30, -20, -10, -5, -0.0001, 1e9]
    labels = ["<-30%", "-30~-20%", "-20~-10%", "-10~-5%", "-5~0%", "at 52w high"]
    cut = pd.cut(dd, bins=edges, labels=labels)
    res = cut.value_counts().reindex(labels).fillna(0).astype(int).rename("count").to_frame()
    res["pct"] = 100 * res["count"] / res["count"].sum()
    return res.reset_index(names="bucket")


def concentration(fund: pd.DataFrame, close: pd.DataFrame, shares: pd.Series) -> dict:
    """Cap concentration and how much of the index move the mega caps drove."""
    caps = fund.set_index("Ticker")["Market Cap"].astype(float)
    caps = caps[caps.index.isin(close.columns)].sort_values(ascending=False)
    total = caps.sum()
    out = {
        "top5_weight": 100 * caps.head(5).sum() / total,
        "top10_weight": 100 * caps.head(10).sum() / total,
        "top25_weight": 100 * caps.head(25).sum() / total,
        "hhi": float(((caps / total) ** 2).sum() * 10000),
    }
    n = HORIZONS["12M"]
    if len(close) > n:
        px0, px1 = close.iloc[-1 - n], close.iloc[-1]
        cap0 = (px0 * shares).dropna()
        cap1 = (px1 * shares).dropna()
        common = cap0.index.intersection(cap1.index)
        delta = (cap1[common] - cap0[common])
        idx_move = delta.sum()
        top10 = caps.index[:10].intersection(common)
        out["top10_share_of_12m_gain"] = float(100 * delta[top10].sum() / idx_move) if idx_move else np.nan
        out["index_12m_return"] = float(100 * (cap1[common].sum() / cap0[common].sum() - 1))
    out["top10_names"] = [
        {"ticker": t, "weight": float(100 * caps[t] / total)} for t in caps.head(10).index
    ]
    return out


# --------------------------------------------------------------------------- #
# sector / industry
# --------------------------------------------------------------------------- #
def group_returns(close: pd.DataFrame, fund: pd.DataFrame, shares: pd.Series, key: str,
                  min_members: int = 1) -> pd.DataFrame:
    """Cap- and equal-weighted returns per sector (or industry) over each horizon."""
    meta = fund.set_index("Ticker")
    members = {g: [t for t in df.index if t in close.columns] for g, df in meta.groupby(key)}
    rows = []
    for g, tickers in members.items():
        if len(tickers) < min_members:
            continue
        px = close[tickers]
        row = {key: g, "n": len(tickers), "market_cap": float(meta.loc[tickers, "Market Cap"].sum())}
        for name, n in HORIZONS.items():
            if len(px) <= n:
                row[f"cw_{name}"] = row[f"ew_{name}"] = row[f"med_{name}"] = np.nan
                continue
            px0, px1 = px.iloc[-1 - n], px.iloc[-1]
            valid = px0.notna() & px1.notna()
            sh = shares.reindex(tickers)
            cap0 = (px0 * sh)[valid].sum()
            cap1 = (px1 * sh)[valid].sum()
            row[f"cw_{name}"] = 100 * (cap1 / cap0 - 1) if cap0 else np.nan
            rets = px1[valid] / px0[valid] - 1
            row[f"ew_{name}"] = 100 * rets.mean()
            row[f"med_{name}"] = 100 * rets.median()
            if name == "3M":
                row["pct_positive_3M"] = 100 * (rets > 0).mean()
        rows.append(row)
    return pd.DataFrame(rows)


def group_breadth(close: pd.DataFrame, fund: pd.DataFrame, key: str, min_members: int = 1) -> pd.DataFrame:
    """% of each group's members above their 50/200 DMA and at/near 52w highs."""
    meta = fund.set_index("Ticker")
    ma50 = close.rolling(50, min_periods=50).mean().iloc[-1]
    ma200 = close.rolling(200, min_periods=200).mean().iloc[-1]
    last = close.iloc[-1]
    hi52 = close.rolling(252, min_periods=min(252, len(close))).max().iloc[-1]
    rows = []
    for g, df in meta.groupby(key):
        tickers = [t for t in df.index if t in close.columns]
        if len(tickers) < min_members:
            continue
        l, m50, m200, h = last[tickers], ma50[tickers], ma200[tickers], hi52[tickers]
        v50 = (l.notna() & m50.notna())
        v200 = (l.notna() & m200.notna())
        rows.append(
            {
                key: g,
                "n": len(tickers),
                "pct_above_50dma": 100 * ((l > m50) & v50).sum() / max(v50.sum(), 1),
                "pct_above_200dma": 100 * ((l > m200) & v200).sum() / max(v200.sum(), 1),
                "pct_within_5pct_of_52wh": 100 * ((l / h) >= 0.95).sum() / max(l.notna().sum(), 1),
                "median_pct_from_52wh": 100 * (l / h - 1).median(),
            }
        )
    return pd.DataFrame(rows)


def group_fundamentals(fund: pd.DataFrame, key: str, min_members: int = 1) -> pd.DataFrame:
    """Median valuation and consensus growth per group."""
    cols = {
        "PE Ratio": "median_pe",
        "Forward P/E Ratio": "median_fwd_pe",
        "Dividend Yield": "median_div_yield",
        "CurrentY成長": "median_cy_growth",
        "NextY成長": "median_ny_growth",
        "CurrentQ成長": "median_cq_growth",
        "NextQ成長": "median_nq_growth",
    }
    g = fund.groupby(key)
    res = g[list(cols)].median().rename(columns=cols)
    res["n"] = g.size()
    res = res[res["n"] >= min_members].reset_index()
    # PEG-style check: forward P/E paid per point of next-year growth.
    res["fwd_pe_over_ny_growth"] = res["median_fwd_pe"] / (res["median_ny_growth"] * 100).replace(0, np.nan)
    res["median_div_yield"] *= 100
    for c in ("median_cy_growth", "median_ny_growth", "median_cq_growth", "median_nq_growth"):
        res[c] *= 100
    return res


def sector_daily_series(close: pd.DataFrame, fund: pd.DataFrame, shares: pd.Series) -> pd.DataFrame:
    """Cap-weighted daily index per sector, rebased to 100, for the RS chart."""
    meta = fund.set_index("Ticker")
    out = {}
    for g, df in meta.groupby("Sector"):
        tickers = [t for t in df.index if t in close.columns]
        if not tickers:
            continue
        cap = close[tickers].mul(shares.reindex(tickers), axis=1).sum(axis=1, min_count=1)
        out[g] = 100 * cap / cap.iloc[0]
    return pd.DataFrame(out)


def leaders_laggards(close: pd.DataFrame, fund: pd.DataFrame, n: int = 15) -> tuple:
    meta = fund.set_index("Ticker")
    h = HORIZONS["3M"]
    ret = (close.iloc[-1] / close.iloc[-1 - h] - 1).dropna() * 100
    ret12 = (close.iloc[-1] / close.iloc[-1 - HORIZONS["12M"]] - 1).dropna() * 100 if len(close) > HORIZONS["12M"] else pd.Series(dtype=float)
    df = pd.DataFrame({"ret_3m": ret, "ret_12m": ret12})
    df = df.join(meta[["Short Name", "Sector", "Industry", "Market Cap"]], how="inner")
    df.index.name = "Ticker"
    df = df.reset_index()
    return df.nlargest(n, "ret_3m"), df.nsmallest(n, "ret_3m")


def rotation_table(group: pd.DataFrame, key: str) -> pd.DataFrame:
    """Rank each group on 12M vs 3M vs 1M performance so rotation shows up as a
    rank change rather than having to eyeball the return columns."""
    r = group[[key, "cw_1M", "cw_3M", "cw_12M"]].copy()
    for h in ("1M", "3M", "12M"):
        r[f"rank_{h}"] = r[f"cw_{h}"].rank(ascending=False, method="min")
    r["rank_change_12m_to_3m"] = r["rank_12M"] - r["rank_3M"]   # + = improving
    r["rank_change_3m_to_1m"] = r["rank_3M"] - r["rank_1M"]
    r["trend"] = np.select(
        [r["rank_change_12m_to_3m"] >= 3, r["rank_change_12m_to_3m"] <= -3],
        ["improving", "deteriorating"],
        default="stable",
    )
    return r.sort_values("rank_3M")


def regime_signals(breadth: pd.DataFrame, part: pd.DataFrame, conc: dict) -> list:
    """Turn the raw breadth series into a handful of named, checkable signals."""
    last = breadth.iloc[-1]
    sig = []

    def add(name, status, detail, value=None):
        sig.append({"signal": name, "status": status, "detail": detail, "value": value})

    p200, p50, p20 = last["pct_above_200dma"], last["pct_above_50dma"], last["pct_above_20dma"]
    add("Primary trend (% > 200DMA)",
        "bullish" if p200 >= 60 else ("neutral" if p200 >= 45 else "bearish"),
        f"{p200:.1f}% of constituents are above their 200-day average", round(float(p200), 1))
    add("Intermediate trend (% > 50DMA)",
        "bullish" if p50 >= 60 else ("neutral" if p50 >= 40 else "bearish"),
        f"{p50:.1f}% above the 50-day average", round(float(p50), 1))
    add("Short-term (% > 20DMA)",
        "oversold" if p20 <= 25 else ("overbought" if p20 >= 80 else "neutral"),
        f"{p20:.1f}% above the 20-day average", round(float(p20), 1))

    # Breadth divergence: index near its own high while participation is not.
    cw = breadth["cap_weighted"]
    idx_pctile = 100 * (cw.tail(126) <= cw.iloc[-1]).mean()
    brd_pctile = 100 * (breadth["pct_above_200dma"].tail(126) <= p200).mean()
    add("Breadth vs index divergence",
        "warning" if idx_pctile - brd_pctile >= 25 else "none",
        f"index sits at the {idx_pctile:.0f}th percentile of its own 6-month range "
        f"while % > 200DMA sits at the {brd_pctile:.0f}th",
        round(float(idx_pctile - brd_pctile), 1))

    mc = last["mcclellan_osc"]
    add("McClellan oscillator",
        "oversold" if mc <= -60 else ("overbought" if mc >= 60 else "neutral"),
        f"{mc:.0f} (19/39-day EMA spread of ratio-adjusted net advances)", round(float(mc), 1))

    net_hl = last["net_hl_10d"]
    add("Net new 52w highs (10d avg)",
        "bullish" if net_hl > 5 else ("bearish" if net_hl < -5 else "neutral"),
        f"{net_hl:+.1f} per day over the last 10 sessions", round(float(net_hl), 1))

    bt = last["breadth_thrust"]
    add("Zweig breadth thrust",
        "thrust" if bt >= 0.615 else ("washed out" if bt <= 0.40 else "neutral"),
        f"10-day EMA of advances/(advances+declines) = {bt:.3f}", round(float(bt), 3))

    p12 = part[part["horizon"] == "12M"]
    if len(p12):
        row = p12.iloc[0]
        add("Participation in the 12M advance",
            "narrow" if row["pct_beat_index"] < 45 else "broad",
            f"only {row['pct_beat_index']:.0f}% of names beat the index; mean {row['mean_ret']:.1f}% "
            f"vs median {row['median_ret']:.1f}%",
            round(float(row["pct_beat_index"]), 1))

    t10 = conc.get("top10_share_of_12m_gain")
    if t10 is not None and not pd.isna(t10):
        add("Mega-cap concentration",
            "extreme" if t10 >= 50 else ("elevated" if t10 >= 35 else "normal"),
            f"the 10 largest names are {conc['top10_weight']:.1f}% of index cap and drove "
            f"{t10:.0f}% of the 12-month cap gain",
            round(float(t10), 1))

    ratio = breadth["ew_cw_ratio"]
    chg = 100 * (ratio.iloc[-1] / ratio.iloc[-min(len(ratio), 252)] - 1)
    add("Equal-weight vs cap-weight",
        "cap-weight leading" if chg < -2 else ("equal-weight leading" if chg > 2 else "in line"),
        f"the equal-weight/cap-weight ratio is {chg:+.1f}% over 12 months", round(float(chg), 1))
    return sig


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.environ.get("FETCH_BASE", str(REPO / "data" / "weekly_reutin")))
    ap.add_argument("--out-dir", default=str(REPO / "data" / "analysis"))
    args = ap.parse_args()

    data_dir, out_dir = Path(args.data_dir), Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ohlc, fund, excluded = load(data_dir)
    daily = pivot(ohlc, "1d", "Close")
    weekly = pivot(ohlc, "1wk", "Close")

    # Share counts implied by the latest market cap; used as a static proxy for
    # index weights through time (ignores buybacks/issuance).
    last_px = daily.iloc[-1]
    caps = fund.set_index("Ticker")["Market Cap"].astype(float)
    shares = (caps / last_px.reindex(caps.index)).dropna()
    shares = shares[np.isfinite(shares)]

    asof = daily.index[-1].date().isoformat()
    print(f"as of {asof} | {daily.shape[1]} tickers | {len(daily)} daily bars")

    # ---- breadth ---------------------------------------------------------- #
    ma_b = moving_average_breadth(daily)
    ad = advance_decline(daily)
    nhnl = new_highs_lows(daily)
    idx = index_series(daily, shares)

    breadth = pd.concat([ma_b, ad, nhnl, idx], axis=1)
    breadth.index.name = "Date"
    breadth.to_csv(out_dir / "breadth_daily.csv", encoding=ENC)

    part = participation(daily)
    # % of names beating the cap-weighted index over the same window.
    for i, row in part.iterrows():
        n = int(row["days"])
        ret = (daily.iloc[-1] / daily.iloc[-1 - n] - 1).dropna()
        bench = idx["cap_weighted"].iloc[-1] / idx["cap_weighted"].iloc[-1 - n] - 1
        part.loc[i, "pct_beat_index"] = 100 * (ret > bench).mean()
        part.loc[i, "index_ret"] = 100 * bench
    part.to_csv(out_dir / "breadth_participation.csv", index=False, encoding=ENC)

    dd = drawdown_buckets(daily)
    dd.to_csv(out_dir / "breadth_drawdown_buckets.csv", index=False, encoding=ENC)

    conc = concentration(fund, daily, shares)
    signals = regime_signals(breadth, part, conc)
    pd.DataFrame(signals).to_csv(out_dir / "breadth_signals.csv", index=False, encoding=ENC)

    # Long-run equal vs cap weight using the weekly history spliced onto daily.
    wk_idx = index_series(weekly, shares)
    long_ratio = pd.concat(
        [
            (wk_idx["ew_cw_ratio"] / wk_idx["ew_cw_ratio"].iloc[-1]),
            (idx["ew_cw_ratio"] / idx["ew_cw_ratio"].iloc[0]),
        ]
    )
    long_ratio = long_ratio[~long_ratio.index.duplicated(keep="last")].sort_index()
    long_ratio.rename("ew_cw_ratio").to_frame().to_csv(out_dir / "breadth_ew_cw_long.csv", encoding=ENC)

    # ---- sector / industry ------------------------------------------------ #
    sec_ret = group_returns(daily, fund, shares, "Sector")
    sec_brd = group_breadth(daily, fund, "Sector")
    sec_fun = group_fundamentals(fund, "Sector")
    sector = sec_ret.merge(sec_brd.drop(columns="n"), on="Sector").merge(sec_fun.drop(columns="n"), on="Sector")
    sector["weight_pct"] = 100 * sector["market_cap"] / sector["market_cap"].sum()
    bench_3m = part.set_index("horizon").loc["3M", "index_ret"]
    bench_12m = part.set_index("horizon").loc["12M", "index_ret"] if "12M" in part["horizon"].values else np.nan
    sector["rs_3m"] = sector["cw_3M"] - bench_3m
    sector["rs_12m"] = sector["cw_12M"] - bench_12m
    sector["label"] = sector["Sector"].map(SECTOR_LABELS).fillna(sector["Sector"])
    sector["style"] = np.where(sector["Sector"].isin(DEFENSIVE), "defensive", "cyclical")
    sector = sector.sort_values("cw_3M", ascending=False)
    sector.to_csv(out_dir / "sector_summary.csv", index=False, encoding=ENC)

    MIN_IND = 3
    ind_ret = group_returns(daily, fund, shares, "Industry", min_members=MIN_IND)
    ind_brd = group_breadth(daily, fund, "Industry", min_members=MIN_IND)
    ind_fun = group_fundamentals(fund, "Industry", min_members=MIN_IND)
    industry = ind_ret.merge(ind_brd.drop(columns="n"), on="Industry").merge(ind_fun.drop(columns="n"), on="Industry")
    sec_of = fund.groupby("Industry")["Sector"].agg(lambda s: s.mode().iat[0] if len(s.mode()) else "unknown")
    industry["Sector"] = industry["Industry"].map(sec_of)
    industry["rs_3m"] = industry["cw_3M"] - bench_3m
    industry = industry.sort_values("cw_3M", ascending=False)
    industry.to_csv(out_dir / "industry_summary.csv", index=False, encoding=ENC)

    sec_rot = rotation_table(sector, "Sector")
    sec_rot["label"] = sec_rot["Sector"].map(SECTOR_LABELS).fillna(sec_rot["Sector"])
    sec_rot.to_csv(out_dir / "sector_rotation.csv", index=False, encoding=ENC)

    sec_series = sector_daily_series(daily, fund, shares)
    sec_series.to_csv(out_dir / "sector_daily_index.csv", encoding=ENC)

    lead, lag = leaders_laggards(daily, fund)
    lead.to_csv(out_dir / "leaders_3m.csv", index=False, encoding=ENC)
    lag.to_csv(out_dir / "laggards_3m.csv", index=False, encoding=ENC)

    # ---- JSON bundle for the HTML report ---------------------------------- #
    tail = breadth.tail(260).copy()
    tail.index = tail.index.strftime("%Y-%m-%d")
    bundle = {
        "asof": asof,
        "n_tickers": int(daily.shape[1]),
        "n_daily_bars": int(len(daily)),
        "daily_start": daily.index[0].date().isoformat(),
        "excluded": excluded,
        "breadth_dates": list(tail.index),
        "breadth": {c: [None if pd.isna(v) else round(float(v), 4) for v in tail[c]] for c in tail.columns},
        "participation": part.round(2).to_dict("records"),
        "drawdown_buckets": dd.round(2).to_dict("records"),
        "concentration": conc,
        "sector": sector.round(3).to_dict("records"),
        "sector_rotation": sec_rot.round(2).to_dict("records"),
        "signals": signals,
        "industry": industry.round(3).to_dict("records"),
        "sector_series": {
            "dates": list(sec_series.tail(260).index.strftime("%Y-%m-%d")),
            "data": {
                c: [None if pd.isna(v) else round(float(v / sec_series[c].tail(260).iloc[0] * 100), 3)
                    for v in sec_series[c].tail(260)]
                for c in sec_series.columns
            },
        },
        "leaders": lead.round(2).to_dict("records"),
        "laggards": lag.round(2).to_dict("records"),
        "latest": {c: (None if pd.isna(breadth[c].iloc[-1]) else round(float(breadth[c].iloc[-1]), 3))
                   for c in breadth.columns},
    }
    with open(out_dir / "analysis_bundle.json", "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, ensure_ascii=False, indent=1, default=str)

    print(f"wrote {len(list(out_dir.glob('*')))} files to {out_dir}")


if __name__ == "__main__":
    main()
