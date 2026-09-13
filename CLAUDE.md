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
- Known bad rows, handled in `breadth_sector.py` and worth re-checking after a refresh:
  `SATS` has zero market cap and no OHLC; `EA`, `EQR`, `AVB` return only a handful of
  daily bars; `FISV` comes back with a null sector/industry (patched via
  `SECTOR_OVERRIDES`). Names with no cap or <60 daily bars are dropped.
- Index weights are reconstructed as `latest market cap / latest close`, held constant
  through history. This ignores buybacks, issuance and index changes — good enough for
  relative comparison, not a precise index replication. State this limitation in any
  output that uses it.

## Git

Work on the branch the task names; never push to `main` without being asked. Do not
open a PR unless explicitly requested.
