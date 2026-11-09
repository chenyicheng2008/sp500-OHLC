# CLAUDE.md

Project memory for this repo. Read this before starting work here.

## What this repo is

A data pipeline + analysis layer for S&P 500 (plus Memory-concept and AI-software
concept) stocks. `fetch_sp500_memory_software.py` pulls fundamentals and OHLC from
`yfinance`; `.github/workflows/daily-fetch.yml` runs it daily (21:30 UTC / 05:30
Taipei) and commits the refreshed CSVs back.

## Layout

```
fetch_sp500_memory_software.py   fetch step (yfinance -> data/weekly_reutin/*.csv)
data/weekly_reutin/              fetched CSVs (sp500_ohlc.csv, sp500_stocks.csv, ...)
data/tableau/                    ticker lists (AIhardware_en.csv is hand-made, see below)
analysis/breadth_sector.py       breadth + sector/industry analysis -> data/analysis/*.csv
analysis/kd_signals.py           weekly/monthly KD(9,3,3) crosses + their factors -> kd_crosses.csv, kd_bundle.json
analysis/trend_regime.py         bull/bear share over time (default: AI hardware list) -> trend_regime_*.csv/json
analysis/regime_backtest.py      does that net warn of falls in rebuilt tech / semi indices? -> regime_backtest*.csv/json
data/events/market_events.csv    hand-curated, sourced market events (the only non-computed input)
analysis/build_report_data.py    condenses those CSVs -> data/analysis/report_data.json
analysis/build_report.py         bakes the JSON into the template -> analysis/reports/*.html (two files, see below)
analysis/report_template.html    report page; `__REPORT_DATA__` is the data placeholder
analysis/reports/                dated standalone reports (one file per data date)
```

## Running the analysis

Always in this order — each step consumes the previous one's output:

```bash
python analysis/breadth_sector.py        # data/analysis/*.csv + analysis_bundle.json + index_ohlc_daily.csv
python analysis/kd_signals.py            # data/analysis/kd_crosses.csv + kd_bundle.json (reads market_events.csv)
python analysis/trend_regime.py          # data/analysis/trend_regime_{daily,weekly,groups}.csv + trend_regime_bundle.json
python analysis/regime_backtest.py       # data/analysis/regime_backtest_weekly.csv + regime_backtest.json
python analysis/build_report_data.py     # data/analysis/report_data.json
python analysis/build_report.py          # analysis/reports/sp500_internals_<asof>.html + ai_spread_<asof>.html
```

Needs `pandas` and `numpy` (not in `requirements.txt`, which covers only the fetch step).
Install with `python3 -m pip install pandas numpy`: on these containers bare `pip` can
belong to a different interpreter than `python3` (seen 2026-10-19: pip on 3.13, python3
on 3.11), so it reports "already satisfied" while the import still fails.

## Report conventions

- **Offline and self-contained.** The generated report inlines its data, CSS and JS
  into one HTML file. No server, no network, no sibling data files — it must open
  from the local filesystem. Fonts are the only external reference and every face
  has a real fallback stack, so the page is fully legible without them.
- **Date-stamped, always, in two places.** The filename carries the data date
  (`sp500_internals_2026-09-11.html`), and the page itself prints both `資料日`
  (last trading day in the data) and `報告產出` (build date) in the masthead and in
  the method section. Never ship a report where you cannot tell those two apart.
- **Never overwrite an older dated report.** Each run writes a new file; the
  directory is the archive.
- **No figure is ever typed into the template.** Every number, ticker, sector name
  and date in the prose and chart captions is derived from `report_data.json` at
  render time. Prose baked into `report_template.html` goes stale silently and then
  ships, dated and wrong, on the next daily rebuild. If a caption needs a figure the
  payload lacks, add it to `build_report_data.py` — do not hardcode it. The same goes for
  connective words: a clause like 「20 日更只有」 or 「仍站在」 asserts an ordering or a
  state, so it must be chosen from the data too, not written once. **Direction counts as
  a state.** The original headline 「指數在高點附近，內部卻在退潮」 was hardcoded and turned
  false on 2026-10-16, when the index fell 2% on the week while 72% of stocks rose.
  `breadthDirection()` (four-week change in %>50DMA plus the McClellan sign, and whether
  the index is within 5% of its high) is the single source every headline, subtitle and
  caption reads from — add new prose through it, never with a fixed adjective. Level bands
  need it too: 「長線結構正在鬆動」 for any %>200DMA in 45-60 read wrong on 2026-10-23 when
  the reading was 58% and climbing from 41%; the same band now says 「正在修復」 when
  improving. **Section subtitles count too**: as of 2026-11-03 the static lines 「平均報酬
  遠高於中位數」, 「指數只差高點不到 2%」 (a figure typed in since 09-11), 「它的高點比指數高點
  早到」 and 「廣度和指數…走了不同方向」 were all filled from data (`renderSubtitles()`), as
  were the counts 「11 個類股」「70 個產業」「各 15 檔」. The verdict body's 「但…只有」「僅」
  「就吃掉了」 flipped wrong that day — the 12-month median stock (+14.7%) beat the index
  (+10.8%) and the top ten supplied only 17% of the gain — and now follow the readings.
  Branches must agree with each other too: on 2026-11-06 the headline said 「內部原地踏步」
  (neither improving nor deteriorating) while the body's off-the-high branch still said
  「內外同步轉弱」; and 「20 日更只有 61%」 called an above-average reading weak just because
  it was below the 50-day one. Both now key off `deteriorating` / an absolute level.
- Prose, labels and tables are Traditional Chinese. Metric names keep their standard
  English term in parentheses on first use (例如「騰落線（A/D Line）」).
- Charts are hand-built inline SVG re-rendered on resize and on theme change; there
  is no chart library and the CSP on published artifacts would block one anyway.

## Event timeline (`data/events/market_events.csv`)

The two-week K-line section annotates economic / industry / stock events. These cannot
be computed, so they live in a hand-maintained CSV — and it is the one place where the
"no figure typed in" rule bends, so it has stricter rules of its own:

- **Every row needs a `source_url`** that says what the row says. Model knowledge does
  not cover the current period; never add an event from memory or inference.
- `detail` restates the source. Price moves are **not** copied from articles: the report
  shows each listed ticker's move as computed from our own closes (`event_moves` in
  `kd_bundle.json`). When they disagree, ours is what the page prints — e.g. GS was
  reported "rising" on 2026-10-13 in early trading but closed -0.2%.
- List in `tickers` only the names the source itself ties to the event. Same-day moves in
  other names are shown as 「同日」 co-occurrence, never as a cause.
- A headline that contradicts our data is about a different date (one result claimed LRCX
  +20% on its October 2026 report; our data shows -11.8% that day) — drop it.
- Add the new two weeks of events on each refresh; rows dated after the data date render
  as 「即將」 automatically — never type 「（即將）」 into a title, it goes stale. When a
  previewed event happens (e.g. E12, the 10-28 FOMC), rewrite its row with the outcome.
- Date an earnings event to the **session the market reacted**, not the after-hours release
  (Alphabet reported 10-28 after the close → row dated 10-29), so the measured move lines up.
- No source, no row: the 11-02 optical drop (LITE -18.6%) had no coverage, so it appears
  only as a data move. Same for a preview whose outcome can't be found — the Lumentum
  11-05 earnings row was deleted rather than left as a stale preview.
- Commentary is labelled as commentary: E20's "fear of Democratic AI regulation" is an
  FXStreet market-wrap opinion and the row says 「屬評論觀點」.
- Sources reachable from this container: WebSearch works. Yahoo (`yfinance` direct) is
  blocked by the proxy (403), Alpha Vantage needs a premium plan for recent US prices, and
  some recap sites fail WebFetch DNS — so the candles are built from our own data.

## KD crosses (`kd_signals.py`)

KD(9,3,3), Taiwan convention: RSV over 9 bars, K = 2/3·K' + 1/3·RSV, D = 2/3·D' + 1/3·K,
seeded at 50. Weekly and monthly bars are resampled from the daily slice with the older
`1wk` bars spliced in front, so the monthly KD has years of warm-up.

- 「同步」 = the monthly KD crosses on the current month's bar **and** the weekly KD crosses
  the same way on a week ending in that month. The stricter "both on the latest bar"
  test found nothing on 2026-10-23 (a month holds four weekly bars, so it almost never
  lines up), which is why the same-month reading is used.
- Zone is checked on the bar **before** the cross, in both timeframes: ≥80 / ≤20 is the
  main list, ≥70 / ≤30 the watch list.
- **Confirmed vs provisional months.** While the current month is unfinished, the script
  scans the previous (finished) month as the confirmed list and the current month as a
  provisional one; every row carries `month` and `month_complete`, and `primary_month` in
  the bundle is what the main tables, factors and read-out use. The current weekly bar can
  be partial too (`week_complete`): `W-FRI` labels it with the coming Friday, e.g. a week
  labelled 2026-11-06 when the data ended 2026-11-03. October 2026 confirmed after
  month-end: ANET/DELL/KEYS and AZO/ZTS/FIS/OTIS/POOL held from the mid-month list; STZ and
  NDSN dropped out; LULU, NVDA, FFIV, AON, KKR joined.
- Event links: a crossed name links only to events naming it **dated in its cross month or
  later**, and a large one-day move is shown as 「與同類股的 Exx 同日」 only when the event's
  own tickers share the name's sector (`event_sectors` in the bundle). Without the sector
  filter, KEYS's 10-22 drop was listed beside Moderna and Pool. A move on a different day
  from the name's own event is shown separately, never fused into that event.
- Group read-outs are generated: "concentrated in one sector" needs ≥50% of the group
  *and* ≥2× that sector's universe share (3 of 10 industrials at 2× is not concentration).

## AI-hardware bull / bear regime (`trend_regime.py`)

Every name is classified each session: **bull** = close > MA50 > MA200, **bear** =
close < MA50 < MA200, **neither** otherwise. The universe's three shares, and net = bull −
bear, form the time series; the whole S&P 500 is computed the same way as the baseline.

On the page `net` is called **多空排列差（Bull–Bear Spread）** = 多頭排列占比 − 空頭排列占比,
in percentage points, −100…+100. It was 「淨值」 until 2026-11-09; the user asked for a name
that says what it is (淨值 reads as NAV / book value). Code and CSV columns keep `net`;
every page label says 多空排列差 — don't reintroduce 淨值.

- **Universe** (since 2026-11-09, second change that day): AI **hardware** only, per the
  user ("AI概念股先排除軟體"). `data/tableau/AIhardware_en.csv` is a list Claude proposed and
  the user accepted — the 22 "core" names: compute chips NVDA/AVGO/AMD; memory & storage
  MU/SNDK/WDC/STX; servers & networking ANET/DELL/SMCI/HPE; optical LITE/CIEN/COHR/GLW;
  connectors APH/TEL; semi equipment AMAT/LRCX/KLAC/TER; DC power & cooling VRT. Its
  business descriptions are generic, written from model knowledge, not sourced. Offered
  but **not** added (the user's call): CSCO, MPWR, JBL, NTAP, ETN, GEV, CEG, VST, and
  Samsung / SK hynix / Kioxia (priced in `Memory_ohlc.csv`, different exchange holidays).
  All 22 are S&P 500 members with full daily history; no split/spin-off cliffs as of
  2026-11-06 (largest one-day drop SMCI -33%).
- `--universe aisoft` gives the software list (`AIsoftware_en.csv`, INDEX rows dropped):
  only 15 of 44 names are priced — the fetch step saves OHLC for S&P 500 members only —
  and the page then lists the 29 unpriced names by group in a note. Do not drop that note.
  `--universe sector:technology` gives the Yahoo-sector view, grouped by industry. All
  page wording (h2, captions, read-out) follows `bundle.universe` (`label`, `source`,
  `group_kind`); zh group names live in `GRP_TC` in the template.
- Daily series starts only once MA200 exists (~2025-08 with the current file). The long
  run uses 10/40-week averages on the spliced weekly bars from 2015 — with **today's**
  list, so it carries survivorship bias (early years read too bullish; for a hand-picked
  theme list it is worse than for an index); the page says so, and the percentile it
  reports is a lower bound on the true one. Weeks with fewer than 60% of members warmed
  up are dropped (`min_n`; the old fixed `>= 10` was sized for 83 tech names).
- The transition matrix (state 21 sessions ago → now) explains *why* the ratio moved;
  the read-out's "單日衝擊" line names the session with the largest one-day fall in net
  and the events catalogued that day.
- Read-out verbs come from signs: on 2026-11-06 all three ≥3-name groups fell, and the
  first draft still said 「上升最多的是 CSP（+67 → +33）」. 「只剩 N 檔維持」 only when
  fewer than half held; a single new bull is named, not 「1 檔以…為主」.
- Extremes are said in words: a percentile of 0 reads 「為近一年最低」, not 「第 0 百分位」
  (`pctTxt()`), and zero counts read 「沒有一檔維持」/「同期沒有新進多頭」.
- The weekly series feeds section 「預警檢驗」 (see below) — change `trend_regime_weekly.csv`
  and that section changes with it.
- As of 2026-11-06, AI hardware: bull 0%, neither 68%, bear 32%, net -31.8 (lowest of the
  daily year) vs market +18.9; a month earlier +59.1 vs -5.1. All 14 bulls left (13 to
  neither, KLAC to bear); the largest one-day fall was 10-14 (E03 CPI, E04 Barclays AI
  hardware downgrade). The software list on the same date: net -6.7.

## Regime as a warning? (`regime_backtest.py`, section 「預警檢驗」)

Asked 2026-11-09: "can this indicator predict a large tech fall?" Answer, from the weekly
net (2015-08 → 2026-11, 587 weeks): **no — it confirms, it doesn't warn.**

- Indices are rebuilt from our closes (no ^IXIC/^SOX in the data): tech = Yahoo
  `technology` (83), semi = `semiconductors` + `semiconductor-equipment-materials` (18);
  cap-weighted, constant shares, **chain-linked weekly** so names entering the data don't
  jump the level. Semi overlaps the AI-hardware list by 8 names / 88% of cap, tech by
  21 / 40% — partly self-comparison; the page says so.
- Rank correlation of net with the *past* 13w return 0.62 (tech) / 0.70 (semi); with the
  *forward* 13w max drawdown +0.07 / +0.09, forward return -0.05 / -0.03.
- Net ≤ +20 → P(≥10% fall within 13w) 33% / 38% vs 7% / 18% above +20, but median forward
  return is about the same: low net = higher volatility, not lower returns.
- Of 15 episodes (≥15% falls, both indices) the net crossed below 0 after the peak 8×,
  before it 5× (index then rose another 7-28% first), never 2× (tech 2025-10, semi 2024-03).
- Signals are declustered (13w); signals inside the last 13w are "尚無結果", never counted.
  Only 45 non-overlapping 13w windows exist — say so whenever quoting these rates.
- **Slide from a high → how long to a correction?** (asked 2026-11-09, `slide_study()`).
  A slide = net reaches `zone`, then falls `drop` below the highest reading since; one
  trigger per visit (base 60/30 → 33 triggers, strict 80/40 → 11). Correction = index
  drawdown from its running high reaching -10/-15/-20%. Compared against **any week**,
  and both sides count only start weeks not already past the line and with 52 weeks of
  follow-up. That eligibility rule matters: the first chat answer counted already-down
  triggers as "0 weeks" and showed tech -10% within 26w as 9/29 (31%); on the fair basis
  it is 5/25 (20%) vs 40% for any week; semi 12/25 (48%) vs 63%. Median wait for -10%:
  tech 47 w vs 36, semi 30 vs 17 — slides are followed by corrections *later*, not sooner.
  Strict slides: tech -15% within 26w 0/9, and every one saw a new high within 52 weeks.
  The spread's own high led the index peak by 0-52 weeks (median 45) across 13 episodes —
  only matchable in hindsight; the read-out says so. "只有" and 「多半是行情中的休息」 are
  conditional on those comparisons, not fixed text.
- **Average cycle** (asked 2026-11-09, `cycle_study()`): turning points by zig-zag — a
  high/low is confirmed once the series reverses by ≥R. The answer depends on R, so the
  page lists R = 40/60/80 points (mean peak-to-peak 18 / 34 / 57 weeks as of 2026-11-06);
  60 drives the chart markers and the legs table. Indices use the same zig-zag on log
  level with a 15% reversal: tech 86 w, semi 63 w (rises ~73/47 w, falls ~14/13 w).
  Autocorrelation is the model-free cross-check: zero at 34 w, most negative at 90 w,
  best re-match only 0.19 at 132 w — weak periodicity; the read-out says so. The last
  leg (from the final confirmed pivot to the data date) is shown as 進行中 and kept out
  of the averages; on 2026-11-06 it ran 57 weeks from +100 (2025-10-03) because the
  2026 swings never reversed 60 points.
- Every read-out clause picks its connective from the numbers (「明顯高於/略高於/對照」,
  「相差不大」 only when the return gap < 3 points, 「各占一半」 only when hits = half).
  The first draft put 「明顯較高」 after the *lower* group's figures — read the sentence
  order, not just the condition.

## Two files from one template

`build_report.py` writes `sp500_internals_<asof>.html` (view `full`) and, when the payload has
`trend`, `ai_spread_<asof>.html` (view `spread`, asked 2026-11-09: 「多空排列差圖形單獨生成一個
HTML」). The view is the `__REPORT_VIEW__` placeholder; `applyView()` hides every section but
`ai`, `bt` and `method`, swaps the masthead (title from the spread reading, `#h-dek-spread`,
名單 count) and the footer. Same data and code, so the two pages cannot disagree — never fork
the template for the spread page. `applyView()` must run after every `renderStatic()`
(initial, resize, theme): renderStatic rewrites the masthead. Hide masthead blocks with
`style.display`, not `hidden` — `.verdict`/`.stats` set their own display and win over the
attribute; and never overwrite an element that renderStatic fills (`#h-dek` holds
`#st-dek-n` — replacing its text crashed the resize handler).

## Constituents (section 「成分股」)

`regime_backtest.py` → `constituents`: the regime universe (22 AI-hardware names) and both
rebuilt indices (semi 18, tech 83), each row with market cap, weight, current alignment
(latest daily close vs MA50/MA200), 1-month return and distance from the 1-year high. The
universe's weight column is informational only — the spread counts every name once; the
caption says so. Tech is collapsed in a `<details>`. Shown in both files.

## Adjustable time range

Every spread time series (07 daily stack + net, 07 weekly long run, 08 timeline) has a
`rangeBar()` above it: presets plus an overview strip whose window drags to move, drags
at its edges to resize, recentres on click; ←/→ move, +/− resize. The two 07 daily charts
share one window. Windows live in `RANGE` (in memory, per group). Ranges change only what
the charts draw — captions, tables and read-outs stay full-period, and the bar says so.
All-period marks (weekly extremes, episodes, pivots, zero-crosses) are drawn only when
inside the window; episodes are clipped to it. Axis ticks use `fmtTick()`: YY/MM, or MM/DD
when the window is under ~7 months (otherwise a 3-month window repeated "26/08 26/08").

## Chapter index

The 章節索引 block and the sticky bar are both generated by `buildToc()` from
`.wrap > section[data-toc]`: number = position among visible sections (written into each
`.sec-no` too), title = the section's own h2, `data-toc` = short bar label, `data-q` = one
line on what the section answers. Add a section by giving it those two attributes — never
type a number into the nav or a `.sec-no` (they drifted before). `data-q` describes the
question, not a reading, so it carries no figures or states. The bar highlights the
section being read (scroll spy) and scrolls itself horizontally on phones.

## Index K-line

`index_ohlc_daily.csv` is the reconstructed cap-weighted index. Open and close are exact
for the reconstruction; high and low are sums of each name's own high/low, which names do
not hit simultaneously — so the wicks are an outer bound (2-3.5% daily range vs a far
narrower real one). The chart draws wicks muted and the page says this; do not present
them as the true index range. Validated against reported S&P 500 closes: 10-16 -1.21% vs
-1.09%, 10-22 -1.33% vs -1.21%, 10-23 -0.57% vs -0.52%.

## Data facts worth remembering

- `sp500_ohlc.csv` is **mixed interval**: the most recent ~2 years are `1d` bars, the
  10 years before that are `1wk`, flagged by the `Interval` column. This split exists
  to keep the file under GitHub's 100MB limit. Breadth must be computed on the `1d`
  slice only; the weekly bars are for long-run context.
- CSVs are `UTF-8-SIG`. The original Colab notebook wrote `Memory_data.csv` as `big5`,
  which silently broke the combine step — do not reintroduce a per-file encoding.
- There is **no volume column**, so volume-confirmed indicators (OBV, volume thrust)
  are not possible. Say so rather than approximating.
- Known bad rows, handled in `breadth_sector.py` and worth re-checking after a refresh
  (the script prints what it excluded every run — read that line):
  `SATS` has no OHLC at all; `EA`, `EQR`, `AVB` return only a handful of daily bars;
  `PSKY` (Paramount Skydance) and `WBD` (post-split) are too new to have 60 bars as of 2026-10;
  PSKY also stopped receiving bars after 2026-10-16 while every other name kept updating,
  so it may never reach 60 — check whether the ticker changed before assuming it will;
  `FISV` comes back with a null sector/industry (patched via `SECTOR_OVERRIDES`);
  `KVUE` dropped to a single bar (2026-10-30) by 2026-11-05 — Kimberly-Clark's acquisition
  was expected to close in H2 2026, but no closing report was found, so do not state it;
  `SATS` now resolves to "Strive, Inc. – Series A" preferred, a different security entirely;
  a session can be missing outright, not just blank (2026-11-04 was absent at the 02:19 UTC
  fetch because the fetch-side fix dropped its unsettled rows) — the next refresh adds it;
  `AZO` returned a zero market cap on 2026-09-22 with its price history intact (back to
  normal on 2026-09-30 — these glitches come and go, so check the printed lines, not this list).
  The two failures are handled differently on purpose: **no usable price history** (<60
  daily bars) drops the name entirely, while a **missing market cap** only removes it
  from cap-weighted figures — it stays in breadth, equal-weight and median stats, where
  no weight is needed. Do not collapse these back into one filter; doing so silently
  deleted AutoZone from the whole analysis.
- **A phantom final session** appears whenever the daily fetch runs before the US
  consolidated close exists: `sp500_ohlc.csv` gets a row for every ticker at that
  date with all four OHLC fields blank (seen 2026-10-01, where only HUBB priced).
  Row counts look perfectly normal, so this does not show up in a `groupby(Date).size()`
  check — only in the non-null count. `drop_empty_sessions()` rejects any session
  priced for under `MIN_SESSION_COVERAGE` (50%) of constituents and the script prints
  what it dropped. Left in, it silently poisons every "latest" reading, the whole
  leaders/laggards table, and the distance-from-high figure.
  Note `pivot_table` drops an all-NaN date by default, so a session where *zero*
  tickers priced (2026-10-07) vanished before the check could see or report it.
  `pivot()` uses `dropna=False` so every session goes through the same gate.
  Since 2026-10-09 the fetch step also drops rows with every price blank
  (`flatten_and_save_ohlc`). Keep the analysis-side gate anyway: the fetch fix removes
  blank *rows*, but a session where one ticker priced and the rest were blank (the
  2026-10-01 HUBB case) still survives as a one-ticker session, and only the coverage
  check catches that. CSVs written before the fix (anything committed before
  2026-10-09 01:25 UTC) still carry placeholder rows. The first post-fix refresh
  (2026-10-09 01:34 UTC) had zero blank rows and the 2026-10-08 bar fully priced.
  The partial case does recur: on 2026-10-26 only 57 of 494 tickers priced, and they were
  all late in the alphabet (TSCO, TSLA … UBER) — the fetch walks tickers in order and the
  bar settled mid-run, so early names got blank rows (dropped at fetch) and late names got
  real ones. The coverage gate dropped the session; the next refresh fills it in.
- **Unadjusted corporate actions.** yfinance does not back-adjust spin-offs/splits, so
  the series shows a cliff (CTVA, 2026-10-01: -83.8% in one session — Corteva's
  separation; market cap / last close = 693M shares, which only fits the post-event
  price). Every return, moving average and 52-week range spanning that cliff is junk,
  and it faked a -59.6% quarter for the whole agricultural-inputs industry. Yahoo
  back-adjusted CTVA a week later (by 2026-10-09), the cliff disappeared and the name
  re-entered on its own — so the break is detected fresh each run, never hard-listed. A single-day
  drop past `CORP_ACTION_DROP` (-60%) marks a break; only bars after it count toward
  `MIN_DAILY_BARS`. Large *rises* are only printed, never dropped — MRNA's +177% on
  2026-08-19 is real (opened +84%, wide range, implied share count consistent). The
  code cannot tell a real surge from a reverse split, so the report must say "flagged,
  check it" — never claim it was verified.
- Index weights are reconstructed as `latest market cap / latest close`, held constant
  through history. This ignores buybacks, issuance and index changes — good enough for
  relative comparison, not a precise index replication. State this limitation in any
  output that uses it.

## Fetch schedule

`daily-fetch.yml` now fires five attempts on odd minutes across 20:07-22:07 UTC, runs
serialized, and re-points onto the remote tip before committing so overlapping runs
don't reject each other. Runs are idempotent (no new data, no commit), so several
"Daily CSV refresh" commits a day is normal, not a bug.

## Git history on main

`main` was rewritten around 2026-10-10 into a fresh orphan history (root commit
"Daily CSV refresh (2026-10-10)"), almost certainly to drop the bloat of committing
a ~45MB CSV every day. This branch predates that and shares **no merge base** with it,
so `git merge origin/main` refuses and GitHub cannot open a PR between them. Until the
branch is rebuilt on the new main, refresh data with
`git checkout origin/main -- data/weekly_reutin data/tableau` (the code outside `data/`
was verified identical) instead of merging — and do not `--allow-unrelated-histories`,
which would re-attach the old history the cleanup removed.

## Git

Work on the branch the task names; never push to `main` without being asked. Do not
open a PR unless explicitly requested.
