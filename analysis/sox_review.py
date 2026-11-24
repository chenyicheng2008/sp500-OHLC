"""Review page for the PHLX Semiconductor index (^SOX).

Asked 2026-11-21: 「費城半導體指數檢視並發佈」. Reads the official ^SOX daily bars that the
fetch step saves in ``data/weekly_reutin/index_ohlc.csv`` and writes one self-contained,
dated page ``analysis/reports/sox_review_<asof>.html`` (data, CSS and JS inlined; the CSS is
taken from ``report_template.html`` so the page matches the other reports).

Every figure on the page comes from the payload built here; the page's prose picks its
words from those figures at render time. ^SOX can run one session ahead of the S&P 500
constituent data, so the comparison with the rebuilt semiconductor index uses only the
weeks both have.

Run after ``regime_backtest.py`` (it reads that script's weekly output for the comparison).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from mcclellan import study as mcclellan_study

REPO = Path(__file__).resolve().parent.parent
ENC = "utf-8-sig"
SYM = "^SOX"
EPISODE = -0.20          # a drawdown this deep from the running high counts as an episode
BIG_DAY = -5.0           # a "large" one-day fall, percent
CANDLE_DAYS = 130        # about six months of daily bars in the K-line chart


def load_sox(data_dir: Path) -> pd.DataFrame:
    io = pd.read_csv(data_dir / "index_ohlc.csv", encoding=ENC, parse_dates=["Date"])
    s = io[io["Ticker"] == SYM].set_index("Date")[["Open", "High", "Low", "Close"]].dropna().sort_index()
    if len(s) < 260:
        raise SystemExit(f"{SYM}: only {len(s)} bars in index_ohlc.csv -- not enough for a review")
    return s


def episodes(c: pd.Series, now_dd: float) -> list:
    """Every fall of at least EPISODE from a running high, peak -> trough -> new high."""
    out, peak_d, peak_v, cur = [], c.index[0], c.iloc[0], None
    for d, v in c.items():
        if v >= peak_v:
            if cur is not None:
                cur["recovered"] = d
                out.append(cur)
                cur = None
            peak_d, peak_v = d, v
            continue
        dd = v / peak_v - 1
        if dd <= EPISODE:
            if cur is None:
                cur = {"peak": peak_d, "peak_v": peak_v, "hit": d, "trough": d, "depth": dd, "recovered": None}
            elif dd < cur["depth"]:
                cur["trough"], cur["depth"] = d, dd
    if cur is not None:
        out.append(cur)
    rows = []
    for e in out:
        wk = lambda a, b: int(round((b - a).days / 7))
        rows.append({"peak": e["peak"].date().isoformat(), "peak_v": round(float(e["peak_v"]), 2),
                     "hit": e["hit"].date().isoformat(), "trough": e["trough"].date().isoformat(),
                     "depth": round(100 * e["depth"], 1),
                     "further": round(100 * (e["depth"] - EPISODE), 1),
                     "w_down": wk(e["peak"], e["trough"]),
                     "recovered": e["recovered"].date().isoformat() if e["recovered"] is not None else None,
                     "w_up": wk(e["trough"], e["recovered"]) if e["recovered"] is not None else None,
                     "ongoing": e["recovered"] is None,
                     # did this episode, at some point, sit as deep as today's drawdown?
                     "reached_now": bool(e["depth"] <= now_dd)})
    return rows


def last_as_low(x: pd.Series, skip: int = 13):
    """The last week, more than `skip` weeks back, when the reading was at or below today's --
    the weeks just before are usually the same slide and say nothing."""
    cur, past = x.iloc[-1], x.iloc[:-skip]
    hit = past[past <= cur]
    return hit.index[-1].date().isoformat() if len(hit) else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.environ.get("FETCH_BASE", str(REPO / "data" / "weekly_reutin")))
    ap.add_argument("--analysis-dir", default=str(REPO / "data" / "analysis"))
    ap.add_argument("--out-dir", default=str(REPO / "analysis" / "reports"))
    args = ap.parse_args()
    A = Path(args.analysis_dir)

    s = load_sox(Path(args.data_dir))
    c = s["Close"]
    asof = c.index[-1]
    r = 100 * c.pct_change()
    ma50, ma200 = c.rolling(50).mean(), c.rolling(200).mean()
    ath_d = c.idxmax()
    dd_now = c.iloc[-1] / c.max() - 1
    prev_year = c[c.index.year < asof.year]

    def ret(n):
        return round(float(100 * (c.iloc[-1] / c.iloc[-1 - n] - 1)), 1) if len(c) > n else None

    # the last time the 50-day average crossed the 200-day one, and which way
    rel = (ma50 - ma200).dropna()
    flips = rel.index[np.sign(rel).diff().fillna(0) != 0]
    cross = None
    if len(flips):
        d = flips[-1]
        cross = {"date": d.date().isoformat(), "kind": "death" if rel[d] < 0 else "golden"}

    eps = episodes(c, dd_now)
    depths = sorted([e["depth"] for e in eps])
    rank = depths.index(round(100 * dd_now, 1)) + 1 if eps and eps[-1]["ongoing"] else None

    big = r[r <= BIG_DAY]
    by_year = {int(y): int(n) for y, n in big.groupby(big.index.year).size().items()}
    years = list(range(c.index[0].year, asof.year + 1))
    worst = [{"date": d.date().isoformat(), "pct": round(float(v), 2),
              "dd": round(float(100 * (c[d] / c[:d].max() - 1)), 1)} for d, v in r.nsmallest(10).items()]

    # weekly long run, plus the rebuilt S&P 500 semiconductor index on the weeks both have
    w = c.resample("W-FRI").last().dropna()
    long = {"dates": [d.date().isoformat() for d in w.index], "close": [round(float(v), 2) for v in w],
            "dd": [round(float(v), 1) for v in 100 * (w / w.cummax() - 1)]}
    comp = None
    bw_p, bj_p = A / "regime_backtest_weekly.csv", A / "regime_backtest.json"
    if bw_p.exists() and bj_p.exists():
        bw = pd.read_csv(bw_p, index_col=0, parse_dates=True)
        bj = json.load(open(bj_p, encoding="utf-8"))
        last_member = pd.Timestamp(bj["asof"])
        wc = c[c.index <= last_member].resample("W-FRI").last().dropna()     # same cut-off as the members
        both = bw.index.intersection(wc.index)
        a, b = bw.loc[both, "semi"], wc.loc[both]
        k0 = both[0]
        long["rebuilt"] = [round(float(bw.loc[d, "semi"] / bw.loc[k0, "semi"] * w.loc[k0]), 2) if d in bw.index and d >= k0 else None
                           for d in w.index]
        side = lambda x: {"total": round(float(100 * (x.iloc[-1] / x.iloc[0] - 1)), 1),
                          "y1": round(float(100 * (x.iloc[-1] / x.iloc[-53] - 1)), 1),
                          "peak": x.idxmax().date().isoformat(),
                          "dd": round(float(100 * (x.iloc[-1] / x.max() - 1)), 1)}
        # the rebuilt index's members, one row each (asked 2026-11-24: 「和 S&P 500 半導體成分股比較..列出個股」)
        cons = bj["constituents"]["semi"]
        tick = [m["ticker"] for m in cons]
        o = pd.read_csv(Path(args.data_dir) / "sp500_ohlc.csv", encoding=ENC, usecols=["Ticker", "Date", "Close", "Interval"])
        o = o[(o["Interval"] == "1d") & o["Ticker"].isin(tick)]
        o["Date"] = pd.to_datetime(o["Date"])
        px = o.pivot_table(index="Date", columns="Ticker", values="Close").sort_index()
        px = px[px.index <= last_member]
        at_peak = px[px.index <= ath_d].iloc[-1] if (px.index <= ath_d).any() else None
        rr = lambda t, n: round(float(100 * (px[t].iloc[-1] / px[t].iloc[-1 - n] - 1)), 1) if px[t].notna().sum() > n else None
        members = []
        for m in cons:
            t = m["ticker"]
            col = px[t].dropna() if t in px else pd.Series(dtype=float)
            ma50_t, ma200_t = col.rolling(50).mean(), col.rolling(200).mean()
            members.append({**m, "r3m": rr(t, 63) if t in px else None, "r1y": rr(t, 252) if t in px else None,
                            "since_peak": round(float(100 * (col.iloc[-1] / at_peak[t] - 1)), 1)
                            if at_peak is not None and t in at_peak and not pd.isna(at_peak[t]) else None,
                            "a50": bool(col.iloc[-1] > ma50_t.iloc[-1]) if len(col) >= 50 else None,
                            "a200": bool(col.iloc[-1] > ma200_t.iloc[-1]) if len(col) >= 200 else None})
        comp_members = {"rows": members, "peak_date": ath_d.date().isoformat(), "asof": bj["asof"]}
        comp = {"start": k0.date().isoformat(), "end": both[-1].date().isoformat(), "member_asof": bj["asof"],
                "weeks": int(len(both)), "corr": round(float(a.pct_change().corr(b.pct_change())), 3),
                "sox": side(b), "rebuilt": side(a), "n": bj["indices"]["semi"]["n"],
                "net_now": bj["net_now"], "universe": bj["universe_label"], "overlap_n": bj["indices"]["semi"]["overlap_n"],
                "members": comp_members}

    # events from the hand-kept list, with ^SOX's own move that day (our closes, not the article's)
    ev = pd.read_csv(REPO / "data" / "events" / "market_events.csv", encoding=ENC)
    start = c.index[-CANDLE_DAYS]
    events = []
    for _, e in ev.iterrows():
        d = pd.Timestamp(e["date"])
        if d < start:
            continue
        events.append({"id": e["id"], "date": e["date"], "cat": e["category"], "title": e["title"], "detail": e["detail"],
                       "source": e["source_name"], "url": e["source_url"],
                       "move": round(float(r[d]), 2) if d in r.index and not np.isnan(r[d]) else None,
                       "upcoming": bool(d > asof)})

    k = s.iloc[-CANDLE_DAYS:]
    candles = {"dates": [d.date().isoformat() for d in k.index],
               **{f: [round(float(v), 2) for v in k[F]] for f, F in (("o", "Open"), ("h", "High"), ("l", "Low"), ("c", "Close"))},
               "ma50": [round(float(v), 2) for v in ma50.iloc[-CANDLE_DAYS:]],
               "ma200": [round(float(v), 2) for v in ma200.iloc[-CANDLE_DAYS:]]}

    # breadth inside the group we can measure: the S&P 500 semiconductor names (the same 18 as
    # the rebuilt index), not ^SOX's own members -- several of those are not in our data
    breadth, mcc = None, None
    sd_p, sw_p, all_p = A / "breadth_daily_semi.csv", A / "breadth_long_weekly_semi.csv", A / "breadth_daily.csv"
    if sd_p.exists() and sw_p.exists() and all_p.exists():
        sd = pd.read_csv(sd_p, index_col=0, parse_dates=True)
        sw = pd.read_csv(sw_p, index_col=0, parse_dates=True)
        mk = pd.read_csv(all_p, index_col=0, parse_dates=True)
        r1 = lambda v: None if pd.isna(v) else round(float(v), 1)
        wsox = c[c.index <= sd.index[-1]].resample("W-FRI").last().reindex(sw.index)
        p40, p10 = sw["pct_above_40w"], sw["pct_above_10w"]
        breadth = {
            "n": int(sw["n_valid"].max()), "asof": sd.index[-1].date().isoformat(),
            "now": {k: r1(sd[c_].iloc[-1]) for k, c_ in (("p20", "pct_above_20dma"), ("p50", "pct_above_50dma"), ("p200", "pct_above_200dma"))},
            "mkt": {k: r1(mk[c_].iloc[-1]) for k, c_ in (("p20", "pct_above_20dma"), ("p50", "pct_above_50dma"), ("p200", "pct_above_200dma"))},
            "nh": int(sd["new_highs"].iloc[-1]), "nl": int(sd["new_lows"].iloc[-1]),
            "nh20": int(sd["new_highs"].tail(20).sum()), "nl20": int(sd["new_lows"].tail(20).sum()),
            "ad_chg20": int(sd["ad_line"].iloc[-1] - sd["ad_line"].iloc[-21]),
            "adv": int(sd["advances"].iloc[-1]), "dec": int(sd["declines"].iloc[-1]),
            "w": {"dates": [d.date().isoformat() for d in sw.index], "p10": [r1(v) for v in p10], "p40": [r1(v) for v in p40],
                  "sox": [None if pd.isna(v) else round(float(v), 2) for v in wsox]},
            "p40_now": r1(p40.iloc[-1]), "p40_pctile": round(float(100 * (p40 < p40.iloc[-1]).mean()), 0),
            "p40_median": r1(p40.median()), "p10_now": r1(p10.iloc[-1]),
            "p10_pctile": round(float(100 * (p10 < p10.iloc[-1]).mean()), 0), "p10_median": r1(p10.median()),
            "p40_last_as_low": last_as_low(p40), "skip": 13,
        }
        mcc = mcclellan_study(sd["mcclellan_osc"], sd["mcclellan_sum"], c.reindex(sd.index))

    payload = {
        "asof": asof.date().isoformat(), "generated": date.today().isoformat(), "start": c.index[0].date().isoformat(),
        "n_bars": int(len(c)), "symbol": SYM,
        "close": round(float(c.iloc[-1]), 2), "chg": round(float(r.iloc[-1]), 2),
        "ath": round(float(c.max()), 2), "ath_date": ath_d.date().isoformat(), "dd": round(float(100 * dd_now), 1),
        "ytd": round(float(100 * (c.iloc[-1] / prev_year.iloc[-1] - 1)), 1) if len(prev_year) else None,
        "r1y": ret(252), "r3m": ret(63), "r1m": ret(21),
        "ma50": round(float(ma50.iloc[-1]), 2), "ma200": round(float(ma200.iloc[-1]), 2),
        "vs_ma200": round(float(100 * (c.iloc[-1] / ma200.iloc[-1] - 1)), 1),
        "vs_ma50": round(float(100 * (c.iloc[-1] / ma50.iloc[-1] - 1)), 1),
        "cross": cross, "episode_thr": round(100 * EPISODE), "episodes": eps, "rank": rank, "n_eps": len(eps),
        "big_day": BIG_DAY, "by_year": [{"year": y, "n": by_year.get(y, 0)} for y in years],
        "worst": worst, "worst_rank_last": int((r < r.iloc[-1]).sum()) + 1 if r.iloc[-1] < 0 else None,
        "long": long, "candles": candles, "events": events, "comp": comp, "breadth": breadth, "mcc": mcc,
    }

    tpl = (REPO / "analysis" / "report_template.html").read_text(encoding="utf-8")
    css = tpl[tpl.index("<style>") + len("<style>"): tpl.index("</style>")]
    mcc_js = (REPO / "analysis" / "mcclellan_view.js").read_text(encoding="utf-8")
    page = (PAGE.replace("__CSS__", css).replace("__MCC_JS__", mcc_js)
            .replace("__DATA__", json.dumps(payload, ensure_ascii=False, separators=(",", ":"))))
    out = Path(args.out_dir) / f"sox_review_{payload['asof']}.html"
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({len(page):,} bytes); {SYM} {payload['close']} on {payload['asof']}, "
          f"{payload['dd']}% from the {payload['ath_date']} high, rank {rank} of {len(eps)} episodes")


PAGE = r"""<meta charset="utf-8">
<title>費城半導體指數檢視</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700&family=Noto+Serif+TC:wght@600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>__CSS__
.mast-in,.wrap{padding-left:max(16px,env(safe-area-inset-left,0px)); padding-right:max(16px,env(safe-area-inset-right,0px))}
.lead{color:var(--ink-2); font-size:14.5px; max-width:70ch; margin:10px 0 0}
td.l{text-align:left; white-space:normal; min-width:220px}
.ev-up{color:var(--ink-3)}
#t-mem th:nth-child(2),#t-mem th:nth-child(3),#t-mem th:nth-child(11),#t-mem th:nth-child(14){text-align:left}
</style>

<header class="mast"><div class="mast-in">
  <p class="kicker">PHLX SEMICONDUCTOR INDEX · <span id="m-sym"></span></p>
  <h1 id="m-h1">—</h1>
  <p class="dek" id="m-dek">—</p>
  <div class="stamp"><span>資料日 <b id="m-asof"></b></span><span>報告產出 <b id="m-gen"></b></span><span>資料起點 <b id="m-start"></b></span></div>
  <div class="stats" id="m-stats"></div>
</div></header>

<div class="wrap">
<section id="long">
  <div class="sec-head"><span class="sec-no"></span><h2>長期走勢與回檔</h2></div>
  <p class="sec-sub" id="long-sub">—</p>
  <figure class="panel">
    <div class="panel-head"><h3>週收盤（對數刻度）與距歷史高點的跌幅</h3><p id="long-def">—</p></div>
    <div class="rb-row" id="long-rb" style="padding:10px 20px 0"></div>
    <div class="legend" id="long-lg"></div>
    <div class="panel-body"><div id="c-long"></div></div>
    <figcaption id="long-cap"></figcaption>
  </figure>
  <div class="tw"><table id="t-eps"><caption>歷次回檔<small id="eps-cap">—</small></caption></table></div>
</section>

<section id="recent">
  <div class="sec-head"><span class="sec-no"></span><h2>近半年日K與均線</h2></div>
  <p class="sec-sub" id="recent-sub">—</p>
  <figure class="panel">
    <div class="panel-head"><h3>日K、50 日與 200 日均線</h3><p>標記的編號對應下方事件表；漲跌幅都是本資料的收盤計算。</p></div>
    <div class="legend" id="k-lg"></div>
    <div class="panel-body"><div id="c-k"></div></div>
    <figcaption id="k-cap"></figcaption>
  </figure>
  <div class="tw"><table id="t-ev"><caption>事件<small>事件內容引自所列來源；漲跌幅是 ^SOX 當日收盤變化，由本資料計算，不採用文章數字。同日事件不代表因果。</small></caption></table></div>
</section>

<section id="breadth">
  <div class="sec-head"><span class="sec-no"></span><h2>成分股廣度</h2></div>
  <p class="sec-sub" id="br-sub">—</p>
  <div class="tw"><table id="t-br"><caption>目前讀數<small id="br-cap">—</small></caption></table></div>
  <figure class="panel">
    <div class="panel-head"><h3>週收盤與站上週均線的比例</h3><p id="br-def">—</p></div>
    <div class="rb-row" id="br-rb" style="padding:10px 20px 0"></div>
    <div class="legend" id="br-lg"></div>
    <div class="panel-body"><div id="c-br"></div></div>
    <figcaption id="br-fig"></figcaption>
  </figure>
</section>

<section id="mcc">
  <div class="sec-head"><span class="sec-no"></span><h2>麥克連擺盪指標</h2></div>
  <p class="sec-sub" id="mcc-sub">—</p>
  <figure class="panel">
    <div class="panel-head"><h3>麥克連擺盪指標（McClellan Oscillator）</h3><p id="mcc-def">—</p></div>
    <div class="rb-row" id="mcc-rb" style="padding:10px 20px 0"></div>
    <div class="legend" id="mcc-lg"></div>
    <div class="panel-body"><div id="c-mcc"></div></div>
    <figcaption id="mcc-cap"></figcaption>
    <ul class="take" id="mcc-take" style="padding:0 20px 8px; margin-top:0"></ul>
  </figure>
</section>

<section id="days">
  <div class="sec-head"><span class="sec-no"></span><h2>單日重挫</h2></div>
  <p class="sec-sub" id="days-sub">—</p>
  <figure class="panel">
    <div class="panel-head"><h3 id="yr-h">—</h3><p>每一年單日收盤跌幅達門檻的交易日數；當年未過完的年份只算到資料日。</p></div>
    <div class="panel-body"><div id="c-yr"></div></div>
  </figure>
  <div class="tw"><table id="t-worst"><caption>資料期間最大的十次單日跌幅<small>「當時距高點」是該日收盤距之前歷史高點的跌幅。</small></caption></table></div>
</section>

<section id="comp">
  <div class="sec-head"><span class="sec-no"></span><h2>和 S&amp;P 500 半導體成分股比較</h2></div>
  <p class="sec-sub" id="comp-sub">—</p>
  <div class="tw"><table id="t-comp"><caption>^SOX 與重建的 S&amp;P 500 半導體指數<small id="comp-cap">—</small></caption></table></div>
  <p class="lead" id="mem-sub">—</p>
  <div class="tw"><table id="t-mem"><caption>重建指數的成分股<small id="mem-cap">—</small></caption></table></div>
</section>

<section id="method">
  <div class="sec-head"><span class="sec-no"></span><h2>方法與限制</h2></div>
  <ul class="take" id="m-list" style="margin-top:14px"></ul>
</section>

<footer id="foot"></footer>
</div>
<div id="tip"></div>
<script>__MCC_JS__</script>
<script>
(function () {
  "use strict";
  var D = __DATA__;
  var $ = function (id) { return document.getElementById(id); };
  var css = function (v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); };
  var NS = "http://www.w3.org/2000/svg";
  function el(tag, at, txt) {
    var e = document.createElementNS(NS, tag);
    for (var k in at) if (at[k] !== null && at[k] !== undefined) e.setAttribute(k, at[k]);
    if (txt !== undefined) e.textContent = txt;
    return e;
  }
  function svg(w, h) { var s = el("svg", { width: w, height: h, viewBox: "0 0 " + w + " " + h }); s.style.display = "block"; return s; }
  var pct = function (v, d) { return v === null || v === undefined ? "—" : (v > 0 ? "+" : "") + v.toFixed(d === undefined ? 1 : d) + "%"; };
  var num = function (v) { return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); };
  var MONO = "IBM Plex Mono, monospace";
  var tip = $("tip");
  function showTip(html, ev) {
    tip.innerHTML = html; tip.style.opacity = 1;
    var x = ev.clientX + 14, y = ev.clientY + 14, r = tip.getBoundingClientRect();
    if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - 14;
    if (y + r.height > innerHeight - 8) y = ev.clientY - r.height - 14;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  function hideTip() { tip.style.opacity = 0; }
  function fillTable(id, head, rows) {
    var t = $(id), cap = t.querySelector("caption");
    t.innerHTML = ""; if (cap) t.appendChild(cap);
    var th = document.createElement("thead"), tr = document.createElement("tr");
    head.forEach(function (h) { var c = document.createElement("th"); c.innerHTML = h; tr.appendChild(c); });
    th.appendChild(tr); t.appendChild(th);
    var tb = document.createElement("tbody");
    rows.forEach(function (r) {
      var row = document.createElement("tr");
      r.forEach(function (c, i) {
        var td = document.createElement("td");
        if (c && typeof c === "object") { td.innerHTML = c.html; if (c.cls) td.className = c.cls; if (c.color) td.style.color = c.color; }
        else { td.innerHTML = c; if (i > 0) td.className = "n"; }
        row.appendChild(td);
      });
      tb.appendChild(row);
    });
    t.appendChild(tb);
  }
  var wk = function (n) { return n === null ? "—" : n + " 週"; };
  var ordinal = function (k) { return k === 1 ? "最深" : "第 " + k + " 深"; };

  /* ---------------- static text ---------------- */
  function renderStatic() {
    var E = D.episodes, cur = E.length && E[E.length - 1].ongoing ? E[E.length - 1] : null;
    $("m-sym").textContent = D.symbol;
    $("m-asof").textContent = D.asof; $("m-gen").textContent = D.generated; $("m-start").textContent = D.start;
    $("m-h1").textContent = cur
      ? "費城半導體指數距高點 " + pct(D.dd) + "，" + D.start.slice(0, 4) + " 年以來" + ordinal(D.rank) + "的回檔"
      : "費城半導體指數距高點 " + pct(D.dd) + (D.dd > -5 ? "，接近歷史高點" : "");
    var below200 = D.vs_ma200 < 0, below50 = D.vs_ma50 < 0;
    $("m-dek").textContent = "收盤 " + num(D.close) + "（當日 " + pct(D.chg, 2) + "），歷史高點 " + num(D.ath) + " 在 " + D.ath_date + "。" +
      "目前" + (below50 && below200 ? "同時在 50 日與 200 日均線之下" : below200 ? "在 200 日均線之下、50 日均線之上" : below50 ? "在 50 日均線之下、仍守住 200 日均線" : "站在 50 日與 200 日均線之上") +
      "（距 200 日均線 " + pct(D.vs_ma200) + "）" +
      (D.cross ? "；50 日均線最近一次" + (D.cross.kind === "death" ? "跌破" : "站上") + " 200 日均線是在 " + D.cross.date : "") + "。";
    var stat = function (k, v, n) { return "<div class='stat'><div class='stat-k'>" + k + "</div><div class='stat-v'>" + v + "</div><div class='stat-n'>" + n + "</div></div>"; };
    $("m-stats").innerHTML =
      stat("收盤", num(D.close), "當日 " + pct(D.chg, 2)) +
      stat("距歷史高點", pct(D.dd), "高點 " + D.ath_date) +
      stat("今年以來", pct(D.ytd), "近 1 年 " + pct(D.r1y)) +
      stat("近 3 個月", pct(D.r3m), "近 1 個月 " + pct(D.r1m)) +
      stat("距 200 日均線", pct(D.vs_ma200), "距 50 日均線 " + pct(D.vs_ma50));

    // episodes
    var done = E.filter(function (e) { return !e.ongoing; });
    var deeper = done.filter(function (e) { return e.depth <= D.dd; });
    $("long-sub").textContent = D.start.slice(0, 4) + " 年以來，^SOX 從歷史高點回檔 " + Math.abs(D.episode_thr) + "% 以上共 " + E.length + " 次" +
      (cur ? "（含目前這一次）" : "") + "。" + (cur
        ? "目前距高點 " + pct(D.dd) + "，在這 " + E.length + " 次裡排" + ordinal(D.rank) + "；已結束的 " + done.length + " 次中，" +
          (deeper.length ? deeper.length + " 次曾跌得比現在更深（" + deeper.map(function (e) { return e.peak.slice(0, 7) + " 高點起的 " + pct(e.depth); }).join("、") + "）。"
            : "沒有一次跌得比現在更深。")
        : "目前不在 " + Math.abs(D.episode_thr) + "% 以上的回檔中。");
    $("long-def").textContent = "上：週收盤，對數刻度，同樣的漲跌幅在不同年代一樣高。下：距之前歷史高點的跌幅；色塊是跌幅達 " + Math.abs(D.episode_thr) + "% 的期間。" +
      (D.comp ? "虛線是用 S&P 500 半導體成分股重建的指數，從 " + D.comp.start + " 起和 ^SOX 對齊，只到 " + D.comp.member_asof + "。" : "");
    var fmtRow = function (e) {
      return [e.peak, { html: num(e.peak_v), cls: "n" }, e.hit, e.trough, { html: pct(e.depth), cls: "n", color: css("--neg") },
        { html: pct(e.further), cls: "n" }, { html: wk(e.w_down), cls: "n" },
        e.ongoing ? { html: "進行中", cls: "n" } : e.recovered, { html: e.ongoing ? "—" : wk(e.w_up), cls: "n" }];
    };
    fillTable("t-eps", ["高點", "高點收盤", "跌破 -" + Math.abs(D.episode_thr) + "%", "最低點", "最大跌幅", "跌破後再跌", "高點到最低", "回到高點", "最低到回高"],
      E.slice().reverse().map(fmtRow));
    var med = function (a) { var s = a.slice().sort(function (x, y) { return x - y; }); return s.length ? s[Math.floor((s.length - 1) / 2)] : null; };
    var ups = done.map(function (e) { return e.w_up; }), downs = done.map(function (e) { return e.w_down; });
    $("eps-cap").textContent = "新到舊。「跌破後再跌」是從第一次跌到 -" + Math.abs(D.episode_thr) + "% 之後，還要再跌多少才見底。已結束的 " + done.length +
      " 次：高點到最低中位數 " + wk(med(downs)) + "，最低到回到高點中位數 " + wk(med(ups)) + "。" +
      (cur ? "進行中的一次，最低點與跌幅都只算到資料日。" : "") + "樣本只有個位數，只能看大致範圍。";

    // recent
    $("recent-sub").textContent = "近 " + D.candles.dates.length + " 個交易日（" + D.candles.dates[0] + " 起）。近 1 個月 " + pct(D.r1m) +
      "、近 3 個月 " + pct(D.r3m) + "；50 日均線 " + num(D.ma50) + "、200 日均線 " + num(D.ma200) + "，收盤" +
      (below200 ? "在 200 日均線之下 " + Math.abs(D.vs_ma200).toFixed(1) + "%" : "在 200 日均線之上 " + D.vs_ma200.toFixed(1) + "%") + "。";
    var CAT = { macro: "經濟", industry: "產業", stock: "個股" };
    fillTable("t-ev", ["編號", "日期", "類別", "事件", "^SOX 當日", "來源"], D.events.slice().reverse().map(function (e) {
      return [e.id, e.date, CAT[e.cat] || e.cat, { html: "<b>" + e.title + "</b><br><span style='color:var(--ink-2)'>" + e.detail + "</span>", cls: "l" },
        e.upcoming ? { html: "即將", cls: "n ev-up" } : { html: pct(e.move, 2), cls: "n", color: e.move < 0 ? css("--neg") : e.move > 0 ? css("--pos") : null },
        { html: "<a href='" + e.url + "' target='_blank' rel='noopener'>" + e.source + "</a>", cls: "l" }];
    }));

    // big days
    var thisYear = D.by_year[D.by_year.length - 1], other = D.by_year.slice(0, -1);
    var maxPrev = other.reduce(function (a, b) { return b.n > a.n ? b : a; }, { n: -1 });
    $("yr-h").textContent = "每年單日跌幅 ≥ " + Math.abs(D.big_day) + "% 的天數";
    $("days-sub").textContent = thisYear.year + " 年到資料日為止，單日跌幅 ≥ " + Math.abs(D.big_day) + "% 的有 " + thisYear.n + " 天；" +
      (thisYear.n > maxPrev.n ? "比資料期間任何一個完整年度都多（之前最多是 " + maxPrev.year + " 年 " + maxPrev.n + " 天）。"
        : thisYear.n === maxPrev.n ? "和之前最多的 " + maxPrev.year + " 年一樣多。" : "之前最多的是 " + maxPrev.year + " 年 " + maxPrev.n + " 天。") +
      (D.worst_rank_last ? "資料日當天 " + pct(D.chg, 2) + "，在 " + D.n_bars + " 個交易日中排第 " + D.worst_rank_last + " 大跌幅。" : "");
    fillTable("t-worst", ["日期", "單日跌幅", "當時距高點"], D.worst.map(function (w) {
      return [w.date, { html: pct(w.pct, 2), cls: "n", color: css("--neg") }, { html: pct(w.dd), cls: "n" }];
    }));

    // comparison
    var C = D.comp;
    if (C) {
      $("comp-sub").textContent = "^SOX 是費城證交所編的半導體指數，成分包含不在 S&P 500 裡的公司，加權方式也和我們的重建不同。重建指數用 Yahoo 產業為半導體與半導體設備的 S&P 500 成分股 " +
        C.n + " 檔，市值加權、固定股數、逐週連鎖。兩者週報酬相關 " + C.corr.toFixed(2) + "，" + (C.corr >= 0.9 ? "大致同步" : "差異明顯") + "；" +
        (C.sox.peak !== C.rebuilt.peak ? "週收盤高點的週別不同：^SOX 在 " + C.sox.peak + " 那週，重建指數在 " + C.rebuilt.peak + " 那週。" : "週收盤高點落在同一週（" + C.sox.peak + " 那週）。") +
        "另外，" + C.universe + "名單（和重建半導體指數重疊 " + C.overlap_n + " 檔）的週線多空排列差目前 " + (C.net_now > 0 ? "+" : "") + C.net_now.toFixed(1) + "。";
      var row = function (lab, k) { return [lab, { html: pct(C.sox[k]), cls: "n" }, { html: pct(C.rebuilt[k]), cls: "n" }]; };
      fillTable("t-comp", ["項目", "^SOX", "重建（" + C.n + " 檔）"], [
        row("期間報酬（" + C.start + " 起）", "total"), row("近 52 週", "y1"), row("距期間高點", "dd"),
        ["週收盤高點（週別）", C.sox.peak, C.rebuilt.peak]]);
      $("comp-cap").textContent = "只比較兩者都有的週（" + C.start + " 至 " + C.end + " 那週）。成分股資料到 " + C.member_asof +
        (C.member_asof < D.asof ? "，比 ^SOX 少了 " + D.asof + " 那個交易日，所以這張表的 ^SOX 數字和上方不同。" : "。") +
        "重建指數用今天的成分名單往回推，有存活者偏差，長期報酬偏高。";
      renderMembers(C);
    } else {
      $("comp-sub").textContent = "資料夾裡沒有重建半導體指數的輸出，這一節略過。";
      $("t-comp").closest(".tw").style.display = "none";
    }

    // breadth of the S&P 500 semiconductor names
    var BR = D.breadth;
    if (BR) {
      var vs = function (a, b) { return Math.abs(a - b) < 3 ? "和全市場差不多" : a > b ? "高於全市場" : "低於全市場"; };
      $("br-sub").textContent = "^SOX 自己的成分股（含不在 S&P 500 的公司）不在我們的資料裡，所以廣度用 S&P 500 裡產業為半導體與半導體設備的 " + BR.n +
        " 檔來量，和「和 S&P 500 半導體成分股比較」一節的重建指數是同一批。到 " + BR.asof + "，站上 200 日均線的 " + BR.now.p200.toFixed(0) + "%（" + vs(BR.now.p200, BR.mkt.p200) + "的 " + BR.mkt.p200.toFixed(0) +
        "%）、50 日 " + BR.now.p50.toFixed(0) + "%（全市場 " + BR.mkt.p50.toFixed(0) + "%）、20 日 " + BR.now.p20.toFixed(0) + "%（全市場 " + BR.mkt.p20.toFixed(0) + "%）。" +
        "週線上，站上 40 週均線的 " + BR.p40_now.toFixed(0) + "%，在 " + BR.w.dates[0].slice(0, 4) + " 年以來第 " + BR.p40_pctile.toFixed(0) + " 百分位（中位 " + BR.p40_median.toFixed(0) + "%）" +
        (BR.p40_last_as_low ? "；不算最近 " + BR.skip + " 週，上一次這麼低是 " + BR.p40_last_as_low + " 那週。" : "；不算最近 " + BR.skip + " 週，期間沒有這麼低的時候。");
      var row = function (lab, a, b, fmtv) { return [lab, { html: fmtv(a), cls: "n" }, { html: b === null ? "—" : fmtv(b), cls: "n" }]; };
      var p0 = function (v) { return v.toFixed(0) + "%"; }, i0 = function (v) { return String(v); };
      fillTable("t-br", ["項目", "半導體 " + BR.n + " 檔", "S&amp;P 500 全體"], [
        row("站上 20 日均線", BR.now.p20, BR.mkt.p20, p0), row("站上 50 日均線", BR.now.p50, BR.mkt.p50, p0), row("站上 200 日均線", BR.now.p200, BR.mkt.p200, p0),
        row("當日上漲／下跌家數", BR.adv + "／" + BR.dec, null, i0), row("近 20 日 52 週新高／新低（家次）", BR.nh20 + "／" + BR.nl20, null, i0),
        row("騰落線近 20 日變化", (BR.ad_chg20 > 0 ? "+" : "") + BR.ad_chg20, null, i0)]);
      $("br-cap").textContent = "資料到 " + BR.asof + "（成分股資料比 ^SOX 少最後一個交易日）。「家次」把同一檔在不同日的新高或新低分開計算。";
      $("br-def").textContent = "上：^SOX 週收盤（對數刻度）。下：" + BR.n + " 檔中站上 10 週與 40 週均線（約當 50 與 200 日）的比例。名單是今天的成分股往回推，早年偏強（存活者偏差）；一檔約占 " +
        (100 / BR.n).toFixed(0) + " 個百分點，比例跳動大。";
      $("br-fig").textContent = "站上 10 週均線目前 " + BR.p10_now.toFixed(0) + "%（第 " + BR.p10_pctile.toFixed(0) + " 百分位，中位 " + BR.p10_median.toFixed(0) + "%）。按鈕只改變畫面範圍，文字是全期數字。";
    } else {
      $("breadth").style.display = "none";
    }
    if (D.mcc) {
      $("mcc-sub").textContent = "擺盪指標看的是上漲與下跌家數的差距，和指數漲跌幅無關：指數續跌時若下跌家數不再擴大，擺盪指標會先止跌。這裡的家數同樣是 S&P 500 半導體 " +
        (BR ? BR.n : "") + " 檔；圖上的 ^SOX 只到成分股資料的最後一天。";
    } else {
      $("mcc").style.display = "none";
    }
    // section numbers follow the visible sections, never typed
    var k = 0;
    document.querySelectorAll(".wrap > section").forEach(function (sec) {
      if (sec.style.display === "none") return;
      var no = sec.querySelector(".sec-no"); if (no) no.textContent = String(++k).padStart(2, "0");
    });

    $("m-list").innerHTML = [
      ["資料", D.symbol + " 日線（" + D.start + " 至 " + D.asof + "，" + D.n_bars + " 個交易日），由每日抓取程式從 Yahoo Finance 取得，存在 data/weekly_reutin/index_ohlc.csv。報告不自行修正官方數字。"],
      ["回檔", "從歷史高點下跌達 " + Math.abs(D.episode_thr) + "% 算一次，直到收盤重新站上舊高點才結束；資料起點之前的高點看不到，所以最早一次的高點是資料期間內的高點。"],
      ["均線", "50 日與 200 日簡單移動平均，以收盤價計算。"],
      ["事件", "事件取自報告共用的事件表（data/events/market_events.csv），每一列都有來源；漲跌幅由本資料計算。"],
      ["限制", "樣本期間約 " + Math.round(D.n_bars / 252) + " 年，20% 以上的回檔只有個位數次，任何「通常」的說法都只是少數案例。這份檢視描述走勢，不預測後市，也不是投資建議。"]
    ].map(function (x, i) { return "<li data-i='" + String(i + 1).padStart(2, "0") + "'><span><b>" + x[0] + "</b>　" + x[1] + "</span></li>"; }).join("");
    $("foot").innerHTML = "費城半導體指數檢視 · 資料日 <b>" + D.asof + "</b> · 報告產出 <b>" + D.generated + "</b> · 由 <code>analysis/sox_review.py</code> 產生";
  }

  // one row per member of the rebuilt index, sortable by any column
  var MEM_SORT = { k: "weight", dir: -1 };
  var IND = { "semiconductors": "半導體", "semiconductor-equipment-materials": "半導體設備" };
  var GRP = { "AI Compute Chips": "AI 運算晶片", "Memory and Storage": "記憶體與儲存", "Semiconductor Equipment": "半導體設備",
    "AI Servers and Networking": "AI 伺服器與網通", "Optical Communication": "光通訊", "Connectors and Components": "連接器與元件",
    "Data Center Power and Cooling": "資料中心電力與散熱" };
  var STATE = { bull: "多頭排列", bear: "空頭排列", neither: "整理" };
  function renderMembers(C) {
    var M = C.members; if (!M) return;
    var R = M.rows, n = R.length, cnt = function (f) { return R.filter(f).length; };
    var nb = cnt(function (r) { return r.state === "bull"; }), ns = cnt(function (r) { return r.state === "bear"; });
    var n50 = cnt(function (r) { return r.a50; }), n200 = cnt(function (r) { return r.a200; });
    var byW = R.slice().sort(function (a, b) { return b.weight - a.weight; }), top3 = byW.slice(0, 3);
    var sp = R.filter(function (r) { return r.since_peak !== null; }).sort(function (a, b) { return a.since_peak - b.since_peak; });
    var ai = cnt(function (r) { return r.group && r.group !== "None"; });
    var med = function (a) { var x = a.slice().sort(function (p, q) { return p - q; }); return x[Math.floor((x.length - 1) / 2)]; };
    var mSp = med(sp.map(function (r) { return r.since_peak; }));
    var names = function (a) { return a.map(function (r) { return r.ticker + "（" + pct(r.since_peak) + "）"; }).join("、"); };
    $("mem-sub").textContent = "重建指數的 " + n + " 檔，資料到 " + M.asof + "。前三大權重 " + top3.map(function (r) { return r.ticker; }).join("、") + " 合計 " +
      top3.reduce(function (a, r) { return a + r.weight; }, 0).toFixed(0) + "%，指數走勢主要由它們決定。均線排列：多頭 " + nb + " 檔、空頭 " + ns + " 檔、整理 " + (n - nb - ns) +
      " 檔；站上 50 日均線 " + n50 + " 檔、200 日均線 " + n200 + " 檔。自 ^SOX 高點（" + M.peak_date + "）以來，" + n + " 檔的中位數是 " + pct(mSp) +
      "，跌最多的是 " + names(sp.slice(0, 3)) + (sp.length > 3 ? "，最抗跌的是 " + names(sp.slice(-2).reverse()) : "") + "。其中 " + ai + " 檔也在 AI 硬體股名單裡（「AI 硬體族群」欄）。";
    var cols = [["ticker", "代號"], ["name", "公司"], ["industry", "產業"], ["cap_bn", "市值<br><span class='sub'>十億美元</span>"], ["weight", "指數權重"],
      ["ret_1m", "近 1 月"], ["r3m", "近 3 月"], ["r1y", "近 1 年"], ["since_peak", "^SOX 高點以來"], ["from_high", "距 52 週高"],
      ["state", "均線排列"], ["a50", "50 日"], ["a200", "200 日"], ["group", "AI 硬體族群"]];
    var key = MEM_SORT.k, dir = MEM_SORT.dir;
    var rows = R.slice().sort(function (a, b) {
      var x = a[key], y = b[key];
      if (x === null || x === undefined) return 1; if (y === null || y === undefined) return -1;
      return (typeof x === "string" ? x.localeCompare(y) : x - y) * dir;
    });
    var neg = css("--neg"), posc = css("--pos");
    var signed = function (v) { return { html: pct(v), cls: "n", color: v === null ? null : v < 0 ? neg : v > 0 ? posc : null }; };
    var yn = function (v) { return { html: v === null ? "—" : v ? "之上" : "之下", cls: "n", color: v === false ? neg : null }; };
    fillTable("t-mem", cols.map(function (c) {
      return "<button type='button' class='th-sort' data-k='" + c[0] + "' style='all:unset;cursor:pointer'>" + c[1] + (c[0] === key ? (dir < 0 ? " ▼" : " ▲") : "") + "</button>";
    }), rows.map(function (r) {
      return ["<b>" + r.ticker + "</b>", { html: r.name, cls: "l" }, { html: IND[r.industry] || r.industry, cls: "l" },
        { html: r.cap_bn.toLocaleString("en-US", { maximumFractionDigits: 0 }), cls: "n" }, { html: r.weight.toFixed(1) + "%", cls: "n" },
        signed(r.ret_1m), signed(r.r3m), signed(r.r1y), signed(r.since_peak), signed(r.from_high),
        { html: STATE[r.state] || r.state, cls: "l", color: r.state === "bear" ? neg : r.state === "bull" ? posc : null }, yn(r.a50), yn(r.a200),
        { html: r.group && r.group !== "None" ? (GRP[r.group] || r.group) : "—", cls: "l" }];
    }));
    $("t-mem").querySelectorAll(".th-sort").forEach(function (b) {
      b.addEventListener("click", function () {
        var k = b.getAttribute("data-k");
        MEM_SORT = { k: k, dir: MEM_SORT.k === k ? -MEM_SORT.dir : (k === "ticker" || k === "name" ? 1 : -1) };
        renderMembers(C);
      });
    });
    $("mem-cap").textContent = "點欄名可排序。權重＝市值占這 " + n + " 檔合計的比例（重建指數用的固定股數）。報酬與均線位置都由本資料的收盤計算，到 " + M.asof +
      "；「^SOX 高點以來」從 " + M.peak_date + " 的收盤算起。均線排列：收盤 > 50 日 > 200 日為多頭，相反為空頭，其餘為整理。";
  }

  /* ---------------- charts ---------------- */
  var LONG_N = Infinity;
  function rangeButtons() {
    var host = $("long-rb"); host.innerHTML = "";
    [["1 年", 52], ["3 年", 156], ["5 年", 260], ["全部", Infinity]].forEach(function (p) {
      var b = document.createElement("button"); b.type = "button"; b.textContent = p[0];
      if (LONG_N === p[1]) b.className = "on";
      b.setAttribute("aria-pressed", LONG_N === p[1] ? "true" : "false");
      b.addEventListener("click", function () { LONG_N = p[1]; rangeButtons(); drawLong(); });
      host.appendChild(b);
    });
  }
  function yearTicks(g, dates, X, y, ink3) {
    var n = dates.length, span = dates[n - 1].slice(0, 4) - dates[0].slice(0, 4);
    if (span >= 3) {
      var every = Math.max(1, Math.ceil(span / 10)), last = null;
      dates.forEach(function (d, i) {
        var yr = d.slice(0, 4); if (yr === last) return; last = yr;
        if (i === 0 || +yr % every) return;
        g.appendChild(el("text", { x: X(i), y: y, "text-anchor": "middle", fill: ink3, "font-size": 10.5, "font-family": MONO }, yr));
      });
    } else {
      var st = Math.max(1, Math.round(n / 6));
      for (var q = 0; q < n; q += st) {
        if (n - 1 - q < st * 0.55 && q) continue;
        g.appendChild(el("text", { x: X(q), y: y, "text-anchor": q ? "middle" : "start", fill: ink3, "font-size": 10.5, "font-family": MONO }, dates[q].slice(2, 7).replace("-", "/")));
      }
      g.appendChild(el("text", { x: X(n - 1), y: y, "text-anchor": "end", fill: ink3, "font-size": 10.5, "font-family": MONO }, dates[n - 1].slice(2, 7).replace("-", "/")));
    }
  }
  function logTicks(lo, hi) {
    var t = [];
    for (var e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++)
      [1, 2, 3, 5, 7].forEach(function (f) { var v = f * Math.pow(10, e); if (v >= lo && v <= hi) t.push(v); });
    if (t.length > 7) t = t.filter(function (v, i) { return i % Math.ceil(t.length / 6) === 0; });
    return t;
  }
  function drawLong() {
    var L = D.long, N = L.dates.length, a = Math.max(0, N - Math.min(N, LONG_N));
    var dates = L.dates.slice(a), close = L.close.slice(a), dd = L.dd.slice(a), reb = L.rebuilt ? L.rebuilt.slice(a) : null, n = dates.length;
    var host = $("c-long"), w = Math.max(320, host.clientWidth), small = w < 520;
    var m = { l: small ? 46 : 54, r: small ? 64 : 80 }, top = { y: 10, h: small ? 200 : 250 }, bot = { y: (small ? 200 : 250) + 30, h: small ? 110 : 130 };
    var h = bot.y + bot.h + 26, iw = w - m.l - m.r, s = svg(w, h);
    var X = function (i) { return m.l + iw * i / Math.max(1, n - 1); };
    var ink3 = css("--ink-3"), rule = css("--rule"), c1 = css("--s2"), cR = css("--ink-2"), neg = css("--neg");
    var vals = close.concat(reb ? reb.filter(function (v) { return v; }) : []);
    var lo = Math.min.apply(null, vals) * 0.95, hi = Math.max.apply(null, vals) * 1.05;
    var LY = function (v) { return top.y + top.h * (1 - (Math.log(v) - Math.log(lo)) / (Math.log(hi) - Math.log(lo))); };
    logTicks(lo, hi).forEach(function (v) {
      s.appendChild(el("line", { x1: m.l, x2: m.l + iw, y1: LY(v), y2: LY(v), stroke: rule }));
      s.appendChild(el("text", { x: m.l - 6, y: LY(v) + 4, "text-anchor": "end", fill: ink3, "font-size": 10.5, "font-family": MONO }, v >= 1000 ? (v / 1000) + "k" : v));
    });
    var ddMin = Math.min(-50, Math.floor(Math.min.apply(null, dd) / 10) * 10);
    var DY = function (v) { return bot.y + bot.h * (v / ddMin); };
    for (var g = 0; g >= ddMin; g -= 10) {
      if (g % 20 && ddMin < -40) continue;
      s.appendChild(el("line", { x1: m.l, x2: m.l + iw, y1: DY(g), y2: DY(g), stroke: rule }));
      s.appendChild(el("text", { x: m.l - 6, y: DY(g) + 4, "text-anchor": "end", fill: ink3, "font-size": 10.5, "font-family": MONO }, g + "%"));
    }
    // episode bands on the drawdown panel and faintly on the price panel
    var idx = {}; dates.forEach(function (d, i) { idx[d] = i; });
    var near = function (d) { for (var i = 0; i < n; i++) if (dates[i] >= d) return i; return n - 1; };
    D.episodes.forEach(function (e) {
      var end = e.recovered || dates[n - 1];
      if (end < dates[0] || e.peak > dates[n - 1]) return;
      var i0 = e.peak < dates[0] ? 0 : near(e.peak), i1 = near(end);
      s.appendChild(el("rect", { x: X(i0), y: bot.y, width: Math.max(2, X(i1) - X(i0)), height: bot.h, fill: neg, opacity: 0.12 }));
      s.appendChild(el("rect", { x: X(i0), y: top.y, width: Math.max(2, X(i1) - X(i0)), height: top.h, fill: neg, opacity: 0.05 }));
    });
    var path = function (arr, Y, col, wd, dash) {
      var d = "", pen = false;
      arr.forEach(function (v, i) { if (v === null || v === undefined) { pen = false; return; } d += (pen ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1); pen = true; });
      s.appendChild(el("path", { d: d, fill: "none", stroke: col, "stroke-width": wd, "stroke-linejoin": "round", "stroke-dasharray": dash || null }));
    };
    var area = "M" + X(0) + " " + DY(0);
    dd.forEach(function (v, i) { area += "L" + X(i).toFixed(1) + " " + DY(v).toFixed(1); });
    area += "L" + X(n - 1) + " " + DY(0) + "Z";
    s.appendChild(el("path", { d: area, fill: neg, opacity: 0.35 }));
    if (reb) path(reb, LY, cR, 1.4, "5 3");
    path(close, LY, c1, 2);
    // end labels
    var lab = function (y, col, t, dash) {
      s.appendChild(el("line", { x1: m.l + iw + 4, x2: m.l + iw + 11, y1: y, y2: y, stroke: col, "stroke-width": 2, "stroke-dasharray": dash ? "3 2" : null }));
      s.appendChild(el("text", { x: m.l + iw + 14, y: y + 4, fill: css("--ink-2"), "font-size": 10.5, "font-weight": 600, "font-family": MONO }, t));
    };
    var ch = function (arr) { var f = arr.filter(function (v) { return v; }); return pct(100 * (f[f.length - 1] / f[0] - 1), 0); };
    var ly = LY(close[n - 1]), ry = null;
    if (reb) { var j = n - 1; while (j > 0 && !reb[j]) j--; ry = LY(reb[j]); if (Math.abs(ry - ly) < 13) ry = ly + (ry > ly ? 13 : -13); }
    lab(ly, c1, ch(close));
    if (reb && ry !== null) lab(ry, cR, ch(reb), true);
    lab(DY(dd[n - 1]), neg, pct(dd[n - 1], 0));
    yearTicks(s, dates, X, h - 8, ink3);
    var cross = el("line", { y1: top.y, y2: bot.y + bot.h, stroke: css("--ink"), opacity: 0 }); s.appendChild(cross);
    var hit = el("rect", { x: m.l, y: top.y, width: iw, height: bot.y + bot.h - top.y, fill: "transparent" });
    hit.addEventListener("mousemove", function (ev) {
      var bb = s.getBoundingClientRect(), i = Math.max(0, Math.min(n - 1, Math.round((ev.clientX - bb.left - m.l) / (iw / Math.max(1, n - 1)))));
      cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i)); cross.setAttribute("opacity", 0.3);
      showTip("<div class='tt-h'>" + dates[i] + "</div><div class='tt-r'><span>^SOX</span><b>" + num(close[i]) + "</b></div>" +
        "<div class='tt-r'><span>距高點</span><b>" + pct(dd[i]) + "</b></div>", ev);
    });
    hit.addEventListener("mouseleave", function () { hideTip(); cross.setAttribute("opacity", 0); });
    s.appendChild(hit);
    host.innerHTML = ""; host.appendChild(s);
    $("long-lg").innerHTML = "<span><i class='swatch' style='background:" + c1 + "'></i>^SOX 週收盤</span>" +
      (reb ? "<span><i class='swatch' style='background:repeating-linear-gradient(90deg," + cR + " 0 5px,transparent 5px 8px)'></i>重建 S&amp;P 500 半導體指數（虛線）</span>" : "") +
      "<span><i class='swatch' style='background:" + neg + ";opacity:.5'></i>距歷史高點</span>";
    $("long-cap").textContent = "圖右的百分比是目前畫面範圍內的漲跌；按鈕只改變畫面範圍，表格與文字是全期數字。";
  }
  function drawK() {
    var K = D.candles, n = K.dates.length, host = $("c-k"), w = Math.max(320, host.clientWidth), small = w < 520;
    var m0 = { r: small ? 56 : 70, l: small ? 46 : 54 }, iw0 = w - m0.l - m0.r;
    var nrows = (function () {                      // how many label rows the events need at this width
      var di = {}; K.dates.forEach(function (d, i) { di[d] = i; });
      var xs = D.events.filter(function (e) { return di[e.date] !== undefined; }).map(function (e) { return m0.l + iw0 / n * (di[e.date] + 0.5); }).sort(function (a, b) { return a - b; });
      var rr = []; xs.forEach(function (x) { var r = 0; while (r < rr.length && rr[r] > x - (small ? 15 : 28)) r++; rr[r] = x; });
      return Math.min(rr.length, small ? 5 : 99);
    })();
    var m = { t: 14 + 12 * nrows, r: m0.r, b: 26, l: m0.l }, h = (small ? 300 : 360) + 12 * nrows, iw = w - m.l - m.r, ih = h - m.t - m.b;
    var s = svg(w, h), ink3 = css("--ink-3"), rule = css("--rule"), up = css("--pos"), dn = css("--neg");
    var all = K.h.concat(K.l, K.ma50.filter(function (v) { return v; }), K.ma200.filter(function (v) { return v; }));
    var lo = Math.min.apply(null, all) * 0.98, hi = Math.max.apply(null, all) * 1.02;
    var Y = function (v) { return m.t + ih * (1 - (v - lo) / (hi - lo)); };
    var step = (iw / n), X = function (i) { return m.l + step * (i + 0.5); };
    var raw = (hi - lo) / 5, mag = Math.pow(10, Math.floor(Math.log10(raw))), st = [1, 2, 2.5, 5, 10].map(function (f) { return f * mag; }).filter(function (x) { return x >= raw; })[0];
    for (var v = Math.ceil(lo / st) * st; v <= hi; v += st) {
      s.appendChild(el("line", { x1: m.l, x2: m.l + iw, y1: Y(v), y2: Y(v), stroke: rule }));
      s.appendChild(el("text", { x: m.l - 6, y: Y(v) + 4, "text-anchor": "end", fill: ink3, "font-size": 10.5, "font-family": MONO }, v >= 1000 ? (v / 1000).toFixed(st < 1000 ? 1 : 0) + "k" : v));
    }
    var bw = Math.max(1, step * 0.62);
    for (var i = 0; i < n; i++) {
      var col = K.c[i] >= K.o[i] ? up : dn;
      s.appendChild(el("line", { x1: X(i), x2: X(i), y1: Y(K.h[i]), y2: Y(K.l[i]), stroke: col, "stroke-width": 1 }));
      var y0 = Y(Math.max(K.o[i], K.c[i])), y1 = Y(Math.min(K.o[i], K.c[i]));
      s.appendChild(el("rect", { x: X(i) - bw / 2, y: y0, width: bw, height: Math.max(1, y1 - y0), fill: col }));
    }
    var line = function (arr, col) {
      var d = ""; arr.forEach(function (v, i) { if (v) d += (d ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1); });
      s.appendChild(el("path", { d: d, fill: "none", stroke: col, "stroke-width": 1.6 }));
    };
    var c50 = css("--s2"), c200 = css("--s4");
    line(K.ma50, c50); line(K.ma200, c200);
    // event labels sit in rows above the plot (greedy: first row with room), a tick marks the candle
    var idx = {}; K.dates.forEach(function (d, i) { idx[d] = i; });
    var rows = [], LW = small ? 15 : 28, RH = 12, MAXR = small ? 5 : 99, ink2 = css("--ink-2"), hidden = 0;
    D.events.filter(function (e) { return idx[e.date] !== undefined; })
      .sort(function (a, b) { return idx[a.date] - idx[b.date]; })
      .forEach(function (e) {
        var x = X(idx[e.date]), r = 0;
        while (r < rows.length && rows[r] > x - LW) r++;
        var yh = Y(K.h[idx[e.date]]);
        if (r >= MAXR) {                            // no room left: keep a tick on the candle, label in the table
          hidden++;
          s.appendChild(el("line", { x1: x, x2: x, y1: yh - 8, y2: yh - 3, stroke: ink2, "stroke-width": 0.8, opacity: 0.7 }));
          return;
        }
        rows[r] = x;
        var ly = m.t - 6 - r * RH;
        s.appendChild(el("line", { x1: x, x2: x, y1: ly + 3, y2: yh - 3, stroke: ink2, "stroke-width": 0.6, "stroke-dasharray": "1 2", opacity: 0.6 }));
        s.appendChild(el("text", { x: x, y: ly, "text-anchor": "middle", fill: ink2, "font-size": 9.5, "font-family": MONO }, small ? e.id.replace(/^E/, "") : e.id));
      });
    var labs = [[K.c[n - 1], css("--ink"), num(K.c[n - 1])], [K.ma50[n - 1], c50, "50日"], [K.ma200[n - 1], c200, "200日"]]
      .map(function (x) { return { y: Y(x[0]), c: x[1], t: x[2] }; }).sort(function (a, b) { return a.y - b.y; });
    for (var q = 1; q < labs.length; q++) if (labs[q].y - labs[q - 1].y < 13) labs[q].y = labs[q - 1].y + 13;
    labs.forEach(function (lb) {
      s.appendChild(el("line", { x1: m.l + iw + 3, x2: m.l + iw + 9, y1: lb.y, y2: lb.y, stroke: lb.c, "stroke-width": 2 }));
      s.appendChild(el("text", { x: m.l + iw + 12, y: lb.y + 4, fill: css("--ink-2"), "font-size": 10, "font-weight": 600, "font-family": MONO }, lb.t));
    });
    var stp = Math.max(1, Math.round(n / (small ? 4 : 7)));
    for (var t = 0; t < n; t += stp) s.appendChild(el("text", { x: X(t), y: h - 8, "text-anchor": t ? "middle" : "start", fill: ink3, "font-size": 10.5, "font-family": MONO }, K.dates[t].slice(5).replace("-", "/")));
    var hit = el("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent" });
    hit.addEventListener("mousemove", function (ev) {
      var bb = s.getBoundingClientRect(), i = Math.max(0, Math.min(n - 1, Math.floor((ev.clientX - bb.left - m.l) / step)));
      var chg = i ? 100 * (K.c[i] / K.c[i - 1] - 1) : null;
      var evs = D.events.filter(function (e) { return e.date === K.dates[i]; }).map(function (e) { return "<div class='tt-r'><span>" + e.id + "</span><b style='font-weight:500'>" + e.title + "</b></div>"; }).join("");
      showTip("<div class='tt-h'>" + K.dates[i] + "</div><div class='tt-r'><span>收盤</span><b>" + num(K.c[i]) + "</b></div>" +
        "<div class='tt-r'><span>當日</span><b>" + pct(chg, 2) + "</b></div>" + evs, ev);
    });
    hit.addEventListener("mouseleave", hideTip);
    s.appendChild(hit);
    host.innerHTML = ""; host.appendChild(s);
    $("k-lg").innerHTML = "<span><i class='swatch' style='background:" + up + "'></i>上漲（收盤高於開盤）</span><span><i class='swatch' style='background:" + dn + "'></i>下跌</span>" +
      "<span><i class='swatch' style='background:" + c50 + "'></i>50 日均線</span><span><i class='swatch' style='background:" + c200 + "'></i>200 日均線</span>";
    var mx = 0, mxi = 0, mn = 0, mni = 0;
    for (var z = 1; z < n; z++) { var cz = 100 * (K.c[z] / K.c[z - 1] - 1); if (cz > mx) { mx = cz; mxi = z; } if (cz < mn) { mn = cz; mni = z; } }
    $("k-cap").textContent = "這段期間最大單日跌幅在 " + K.dates[mni] + "（" + pct(mn, 2) + "），最大單日漲幅在 " + K.dates[mxi] + "（" + pct(mx, 2) + "）。" +
      (small ? "窄螢幕上編號省略字母 E" + (hidden ? "，另有 " + hidden + " 則事件只標短線、不標編號" : "") + "，完整內容見下方事件表。" : "");
  }
  function drawYears() {
    var B = D.by_year, host = $("c-yr"), w = Math.max(320, host.clientWidth), h = 180, m = { t: 18, r: 10, b: 24, l: 30 };
    var iw = w - m.l - m.r, ih = h - m.t - m.b, s = svg(w, h), ink3 = css("--ink-3");
    var mx = Math.max.apply(null, B.map(function (b) { return b.n; })) || 1, bw = iw / B.length;
    var Y = function (v) { return m.t + ih * (1 - v / mx); };
    B.forEach(function (b, i) {
      var last = i === B.length - 1, x = m.l + bw * i + bw * 0.18, ww = bw * 0.64;
      s.appendChild(el("rect", { x: x, y: Y(b.n), width: ww, height: Math.max(0, Y(0) - Y(b.n)), fill: last ? css("--neg") : css("--rule-strong"), rx: 1.5 }));
      if (b.n) s.appendChild(el("text", { x: x + ww / 2, y: Y(b.n) - 4, "text-anchor": "middle", fill: css("--ink-2"), "font-size": 10.5, "font-family": MONO }, b.n));
      if (w > 480 || i % 2 === 0 || last) s.appendChild(el("text", { x: x + ww / 2, y: h - 7, "text-anchor": "middle", fill: ink3, "font-size": 10, "font-family": MONO }, String(b.year).slice(2)));
    });
    s.appendChild(el("line", { x1: m.l, x2: m.l + iw, y1: Y(0), y2: Y(0), stroke: css("--axis") }));
    host.innerHTML = ""; host.appendChild(s);
  }
  var BR_N = Infinity;
  function drawBreadth() {
    var BR = D.breadth; if (!BR) return;
    var host = $("br-rb"); host.innerHTML = "";
    [["1 年", 52], ["3 年", 156], ["5 年", 260], ["全部", Infinity]].forEach(function (p) {
      var b = document.createElement("button"); b.type = "button"; b.textContent = p[0];
      if (BR_N === p[1]) b.className = "on";
      b.setAttribute("aria-pressed", BR_N === p[1] ? "true" : "false");
      b.addEventListener("click", function () { BR_N = p[1]; drawBreadth(); });
      host.appendChild(b);
    });
    var W = BR.w, N = W.dates.length, a = Math.max(0, N - Math.min(N, BR_N));
    var dates = W.dates.slice(a), sox = W.sox.slice(a), p10 = W.p10.slice(a), p40 = W.p40.slice(a), n = dates.length;
    var hostC = $("c-br"), w = Math.max(320, hostC.clientWidth), small = w < 520;
    var m = { l: small ? 46 : 54, r: small ? 50 : 60 }, T = { y: 10, h: small ? 160 : 200 }, B = { y: 0, h: small ? 130 : 160 };
    B.y = T.y + T.h + 22;
    var h = B.y + B.h + 26, iw = w - m.l - m.r, sv = svg(w, h), ink3 = css("--ink-3"), rule = css("--rule");
    var X = function (i) { return m.l + iw * i / Math.max(1, n - 1); };
    var v = sox.filter(function (x) { return x; }), lo = Math.min.apply(null, v) * 0.95, hi = Math.max.apply(null, v) * 1.05;
    var LY = function (x) { return T.y + T.h * (1 - (Math.log(x) - Math.log(lo)) / (Math.log(hi) - Math.log(lo))); };
    logTicks(lo, hi).forEach(function (t) {
      sv.appendChild(el("line", { x1: m.l, x2: m.l + iw, y1: LY(t), y2: LY(t), stroke: rule }));
      sv.appendChild(el("text", { x: m.l - 6, y: LY(t) + 4, "text-anchor": "end", fill: ink3, "font-size": 10.5, "font-family": MONO }, t >= 1000 ? (t / 1000) + "k" : t));
    });
    var PY = function (x) { return B.y + B.h * (1 - x / 100); };
    [0, 25, 50, 75, 100].forEach(function (t) {
      sv.appendChild(el("line", { x1: m.l, x2: m.l + iw, y1: PY(t), y2: PY(t), stroke: t === 50 ? css("--axis") : rule }));
      sv.appendChild(el("text", { x: m.l - 6, y: PY(t) + 4, "text-anchor": "end", fill: ink3, "font-size": 10.5, "font-family": MONO }, t + "%"));
    });
    var path = function (arr, Y, col, wd, op) {
      var d = "", pen = false;
      arr.forEach(function (x, i) { if (x === null) { pen = false; return; } d += (pen ? "L" : "M") + X(i).toFixed(1) + " " + Y(x).toFixed(1); pen = true; });
      sv.appendChild(el("path", { d: d, fill: "none", stroke: col, "stroke-width": wd, opacity: op || 1, "stroke-linejoin": "round" }));
    };
    var cS = css("--s2"), c40 = css("--s1"), c10 = css("--s3");
    path(sox, LY, cS, 1.8); path(p10, PY, c10, 1.2, 0.8); path(p40, PY, c40, 1.8);
    var endL = function (y, col, t) {
      sv.appendChild(el("line", { x1: m.l + iw + 4, x2: m.l + iw + 10, y1: y, y2: y, stroke: col, "stroke-width": 2 }));
      sv.appendChild(el("text", { x: m.l + iw + 13, y: y + 4, fill: css("--ink-2"), "font-size": 10.5, "font-weight": 600, "font-family": MONO }, t));
    };
    var j = n - 1; while (j > 0 && sox[j] === null) j--;
    endL(LY(sox[j]), cS, (sox[j] / 1000).toFixed(1) + "k");
    var y40 = PY(p40[n - 1]), y10 = PY(p10[n - 1]); if (Math.abs(y40 - y10) < 12) y10 = y40 + (y10 >= y40 ? 12 : -12);
    endL(y40, c40, p40[n - 1].toFixed(0) + "%"); endL(y10, c10, p10[n - 1].toFixed(0) + "%");
    yearTicks(sv, dates, X, h - 8, ink3);
    var cross = el("line", { y1: T.y, y2: B.y + B.h, stroke: css("--ink"), opacity: 0 }); sv.appendChild(cross);
    var hit = el("rect", { x: m.l, y: T.y, width: iw, height: B.y + B.h - T.y, fill: "transparent" });
    hit.addEventListener("mousemove", function (ev) {
      var bb = sv.getBoundingClientRect(), i = Math.max(0, Math.min(n - 1, Math.round((ev.clientX - bb.left - m.l) / (iw / Math.max(1, n - 1)))));
      cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i)); cross.setAttribute("opacity", 0.3);
      showTip("<div class='tt-h'>" + dates[i] + "</div>" + (sox[i] ? "<div class='tt-r'><span>^SOX</span><b>" + num(sox[i]) + "</b></div>" : "") +
        "<div class='tt-r'><span>站上 40 週均線</span><b>" + (p40[i] === null ? "—" : p40[i].toFixed(0) + "%") + "</b></div>" +
        "<div class='tt-r'><span>站上 10 週均線</span><b>" + (p10[i] === null ? "—" : p10[i].toFixed(0) + "%") + "</b></div>", ev);
    });
    hit.addEventListener("mouseleave", function () { hideTip(); cross.setAttribute("opacity", 0); });
    sv.appendChild(hit);
    hostC.innerHTML = ""; hostC.appendChild(sv);
    $("br-lg").innerHTML = "<span><i class='swatch' style='background:" + cS + "'></i>^SOX 週收盤</span><span><i class='swatch' style='background:" + c40 +
      "'></i>站上 40 週均線</span><span><i class='swatch' style='background:" + c10 + "'></i>站上 10 週均線</span>";
  }
  function renderCharts() {
    rangeButtons(); drawLong(); drawK(); drawBreadth(); drawYears();
    if (D.mcc && window.MCC) MCC.render(D.mcc, { key: "sox", idxName: "^SOX",
      groupName: "S&P 500 半導體成分股 " + (D.breadth ? D.breadth.n : "") + " 檔（不是 ^SOX 自己的成分股）",
      ids: { chart: "c-mcc", rb: "mcc-rb", lg: "mcc-lg", def: "mcc-def", cap: "mcc-cap", take: "mcc-take" } });
  }

  renderStatic(); renderCharts();
  var tmr; addEventListener("resize", function () { clearTimeout(tmr); tmr = setTimeout(renderCharts, 150); });
  try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () { renderStatic(); renderCharts(); }); } catch (e) {}
  new MutationObserver(function () { renderStatic(); renderCharts(); }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
})();
</script>
"""


if __name__ == "__main__":
    main()
