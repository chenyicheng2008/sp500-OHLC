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
python fetch_sp500_memory_software.py
```

Requires local input files (ticker lists) at the paths hardcoded in `BASE`/`TABLEAU`:
- `SP500.csv` — S&P 500 ticker list (column `A`)
- `AIsoftware_en.csv` — AI-software concept ticker list (column `stock`)

Outputs (written in place, overwriting previous runs):
- `sp500_stocks.csv`, `aisoft_df.csv`, `Memory_data.csv`
- `SP550_memory_combined.csv` (sp500 + memory concat)
- `sp500_ohlc.csv`, `Memory_ohlc.csv` (12-year OHLC history)
