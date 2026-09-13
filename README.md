# sp500-memory-software-fetcher

Re-fetches S&P 500, Memory-concept, and AI-software-concept stock fundamentals + OHLC
data via `yfinance`, and saves consistent CSVs for downstream analysis.

Originally a port of a Google Colab notebook ("get sp500 data"). The notebook saved
`Memory_data.csv` with `encoding="big5"` while every other CSV used `UTF-8-SIG`,
which silently broke the sp500+memory combine step. This script standardizes
everything on UTF-8-SIG and adds retry/backoff around `yfinance` calls so a single
transient Yahoo Finance 404/429 doesn't kill a 500+ ticker run.

## Usage

```bash
pip install -r requirements.txt
python fetch_sp500_memory_software.py
```

By default it reads/writes the original local Windows mirror
(`C:\My_old_NoteBook\SOX_EPS\SOX_EPS\python_jupyter\weekly_reutin` /
`...\tableau`). Override with the `FETCH_BASE` / `FETCH_TABLEAU` env vars to
point elsewhere (e.g. this repo's `data/weekly_reutin` and `data/tableau`,
which is what the GitHub Actions workflow does).

Input files (ticker lists), checked into `data/`:
- `data/weekly_reutin/SP500.csv` — S&P 500 ticker list (column `A`)
- `data/tableau/AIsoftware_en.csv` — AI-software concept ticker list (column `stock`)

Outputs (written in place into `FETCH_BASE`, overwriting previous runs):
- `sp500_stocks.csv`, `aisoft_df.csv`, `Memory_data.csv`
- `SP550_memory_combined.csv` (sp500 + memory concat)
- `sp500_ohlc.csv`, `Memory_ohlc.csv` — 12 years of OHLC: the most recent 2 years
  as daily bars, the 10 years before that as weekly bars (keeps `sp500_ohlc.csv`
  under GitHub's 100MB file limit). The `Interval` column is `1d` or `1wk`.

## GitHub Actions

`.github/workflows/daily-fetch.yml` runs the script daily (21:30 UTC / 05:30
Taipei), pointing `FETCH_BASE`/`FETCH_TABLEAU` at `data/weekly_reutin` and
`data/tableau`, then commits any changed output CSVs back to the repo. It can
also be triggered manually from the Actions tab (`workflow_dispatch`).

## Breadth & sector analysis

`analysis/breadth_sector.py` reads `sp500_ohlc.csv` + `sp500_stocks.csv` and writes
market-internals tables into `data/analysis/`:

```bash
python analysis/breadth_sector.py        # -> data/analysis/*.csv + analysis_bundle.json
python analysis/build_report_data.py     # -> data/analysis/report_data.json (feeds the HTML report)
```

Breadth runs on the daily portion of the OHLC file (the most recent ~2 years); the
weekly bars before that are used only for the long-run equal-weight vs cap-weight
series. Names with no market cap or fewer than 60 daily bars are dropped — they carry
no index weight and only add noise.

| Output | What's in it |
| --- | --- |
| `breadth_daily.csv` | Daily % above 20/50/150/200 DMA, A/D line, McClellan oscillator + summation, Zweig breadth thrust, 52-week new highs/lows, cap- and equal-weighted index levels |
| `breadth_signals.csv` | Ten named regime signals (trend, divergence, participation, concentration) with a bullish/neutral/bearish-style status each |
| `breadth_participation.csv` | Per horizon: % of names positive, % beating the index, mean vs median return, P10/P90 dispersion |
| `breadth_drawdown_buckets.csv` | Distribution of constituents by distance from their 52-week high |
| `breadth_ew_cw_long.csv` | 12-year equal-weight / cap-weight ratio (weekly bars spliced onto daily) |
| `sector_summary.csv` | Per sector: cap-weighted / equal-weighted / median returns over 1W–12M, breadth, valuation, consensus growth, index weight |
| `sector_rotation.csv` | Sector rank over 12M / 3M / 1M and the rank change between them |
| `sector_daily_index.csv` | Cap-weighted daily index level per sector |
| `industry_summary.csv` | The same return/breadth/valuation columns per industry (min. 3 constituents) |
| `leaders_3m.csv`, `laggards_3m.csv` | The 15 strongest and weakest names over 3 months |

Index weights use shares implied by the latest market cap divided by the latest close,
held constant through history. That ignores buybacks, issuance and index changes, so the
reconstructed index is for relative comparison, not a precise replication.

`analysis/report.html` is a self-contained Traditional-Chinese report built from
`report_data.json` (charts, signal board, sector and industry tables).
