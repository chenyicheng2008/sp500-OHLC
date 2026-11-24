---
name: sp500-refresh
description: Refresh the S&P 500 breadth / AI-hardware spread / ^SOX review reports to the latest data date in this repo — bring in the daily yfinance data from main, add sourced events, run the analysis pipeline, check the pages and publish. Use when the user says 更新, 更新資料日, refresh the reports, or asks where stock or index prices may come from.
---

# Refreshing the reports

Read `CLAUDE.md` first; this skill is the checklist, CLAUDE.md holds the reasons.

## Data sources — the rule

**Stock and index prices come only from yfinance or Alpha Vantage** (user, 2026-11-24).

- yfinance: the daily GitHub Action runs `fetch_sp500_memory_software.py` on `main` and
  commits `data/weekly_reutin/*.csv` (constituents, `index_ohlc.csv` with ^GSPC / ^SPXEW / ^SOX /
  ^SP500-45, and `sox_extra_ohlc.csv` for ^SOX members outside the S&P 500). The container
  cannot reach Yahoo itself (proxy 403), so take the files from main.
- Alpha Vantage (MCP tools only): index data (`INDEX_DATA`) and recent US prices need a
  premium plan this account does not have (checked 2026-11-24). Its catalog has SPX and SPEQX
  (equal weight, 1/10 level) but no ^SOX and no ^SP500-45; SIXT is a different index — never
  substitute it. `ETF_PROFILE` and `SYMBOL_SEARCH` work.
- Never take a price, close, index level or percentage move from an article, a recap site or
  model knowledge. Articles source *what happened* in event rows; moves are computed from
  our closes.

## Steps

1. **Data.** `git fetch origin main && git checkout origin/main -- data/weekly_reutin data/tableau`
   (the branch shares no history with main — never merge it). Check the last daily session
   and how many names priced it; if main runs past the date the user named, ask which date.
2. **Events** (`data/events/market_events.csv`). For each session since the last refresh, look
   at the largest moves in our data, search for sources (WebSearch works; WebFetch often
   fails DNS on fool.com / finance.yahoo.com), and add a row only when a source says what the
   row says. Label anonymous-source and commentary claims. Rewrite previewed events with
   their outcome. No source → no row (the move still shows as data).
3. **Pipeline**, in order:
   ```bash
   python3 analysis/breadth_sector.py      # read the "excluding …" line
   python3 analysis/kd_signals.py
   python3 analysis/trend_regime.py
   python3 analysis/regime_backtest.py
   python3 analysis/build_report_data.py
   python3 analysis/build_report.py        # sp500_internals_<asof>.html + ai_spread_<asof>.html
   python3 analysis/sox_review.py          # sox_review_<asof>.html
   ```
4. **Check** each page in headless Chromium (Node `playwright`, preinstalled) at 1200 px and
   390 px: no page errors, no horizontal scroll, and read the generated headlines and
   connectives against the numbers — a big one-day move (crash or rebound) is where fixed
   wording breaks.
5. **Record and ship.** Update CLAUDE.md with the readings and anything learned, commit on the
   session branch, push, publish the three pages as artifacts, and reply in Traditional
   Chinese with the data date, the key readings and anything left undone.
