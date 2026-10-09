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
data/tableau/                    ticker lists
analysis/breadth_sector.py       breadth + sector/industry analysis -> data/analysis/*.csv
analysis/build_report_data.py    condenses those CSVs -> data/analysis/report_data.json
analysis/build_report.py         bakes the JSON into the template -> analysis/reports/*.html
analysis/report_template.html    report page; `__REPORT_DATA__` is the data placeholder
analysis/reports/                dated standalone reports (one file per data date)
```

## Running the analysis

Always in this order — each step consumes the previous one's output:

```bash
python analysis/breadth_sector.py        # data/analysis/*.csv + analysis_bundle.json
python analysis/build_report_data.py     # data/analysis/report_data.json
python analysis/build_report.py          # analysis/reports/sp500_internals_<asof>.html
```

Needs `pandas` and `numpy` (not in `requirements.txt`, which covers only the fetch step).

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
  state, so it must be chosen from the data too, not written once.
- Prose, labels and tables are Traditional Chinese. Metric names keep their standard
  English term in parentheses on first use (例如「騰落線（A/D Line）」).
- Charts are hand-built inline SVG re-rendered on resize and on theme change; there
  is no chart library and the CSP on published artifacts would block one anyway.

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
  `FISV` comes back with a null sector/industry (patched via `SECTOR_OVERRIDES`);
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
  2026-10-09 01:25 UTC) still carry placeholder rows.
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

## Git

Work on the branch the task names; never push to `main` without being asked. Do not
open a PR unless explicitly requested.
