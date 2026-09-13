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
