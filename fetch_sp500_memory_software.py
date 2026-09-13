"""
Re-fetch sp500 / memory-concept / AI-software-concept fundamentals + OHLC and
save consistent CSVs to the local mirror of the Google Drive weekly_reutin folder.

Local port of the Colab notebook "get sp500 data" (Drive id 1sBE7IBpKhUg0EmVWOJwWjgvVjhHkim73).

Fix applied vs. the original notebook: Memory_data.csv was being saved with
encoding="big5" while every other CSV in the pipeline uses UTF-8-SIG. Big5 can't
encode arbitrary Unicode company names and caused the sp500+memory combine step
to silently never run. Everything below is standardized on UTF-8-SIG.

Run this again next time to refresh the CSVs (same base paths, so it overwrites in place).

Paths default to the original local Windows mirror, but can be overridden (e.g. by
the GitHub Actions workflow, which runs on Linux and has no access to that drive)
via the FETCH_BASE / FETCH_TABLEAU environment variables.
"""
import os
import time

import pandas as pd
import yfinance as yf

BASE = os.environ.get("FETCH_BASE", r"C:\My_old_NoteBook\SOX_EPS\SOX_EPS\python_jupyter\weekly_reutin")
TABLEAU = os.environ.get("FETCH_TABLEAU", r"C:\My_old_NoteBook\SOX_EPS\SOX_EPS\tableau")

# Yahoo Finance occasionally 404s/429s on an isolated request even when the
# symbol is fine (rate limiting / transient blip). Retry a couple of times
# with backoff before giving up on a single ticker, so one flaky request
# doesn't kill an entire 500+ ticker run.
MAX_RETRIES = 3
RETRY_DELAY_SEC = 3


def _get_info_with_retry(stock):
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return stock.info
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SEC * attempt)
    print(f"  [warn] giving up on {stock.ticker} after {MAX_RETRIES} attempts: {last_err}")
    return {}


def get_stock_info(ticker):
    stock = yf.Ticker(ticker)
    info = _get_info_with_retry(stock) or {}
    try:
        earnings_estimates = stock.earnings_estimate
    except Exception:
        earnings_estimates = pd.DataFrame()

    current_y_growth = next_y_growth = current_q_growth = next_q_growth = 0
    if earnings_estimates is not None and not earnings_estimates.empty and "growth" in earnings_estimates.columns:
        growth_data = earnings_estimates["growth"]
        current_y_growth = growth_data.get("0y", 0)
        next_y_growth = growth_data.get("+1y", 0)
        current_q_growth = growth_data.get("0q", 0)
        next_q_growth = growth_data.get("+1q", 0)

    return {
        "Ticker": ticker,
        "Short Name": info.get("shortName", "N/A"),
        "Market Cap": info.get("marketCap", 0),
        "Sector": info.get("sectorKey"),
        "Industry": info.get("industryKey"),
        "PE Ratio": info.get("trailingPE", 0),
        "Dividend Yield": info.get("trailingAnnualDividendYield", 0),
        "Forward P/E Ratio": info.get("forwardPE", 0),
        "50日均差%": info.get("fiftyDayAverageChangePercent", 0),
        "200日均差%": info.get("twoHundredDayAverageChangePercent", 0),
        "CurrentY成長": current_y_growth,
        "NextY成長": next_y_growth,
        "CurrentQ成長": current_q_growth,
        "NextQ成長": next_q_growth,
    }


def get_adjusted_ohlc_from_csv(csv_filepath, column_name="Ticker", period="1y", encoding=None):
    stock_list_df = None
    encodings = [encoding] if encoding else ["utf-8-sig", "utf-8", "big5"]
    for enc in encodings:
        try:
            stock_list_df = pd.read_csv(csv_filepath, encoding=enc)
            print(f"成功使用 {enc} 編碼讀取檔案。")
            break
        except (UnicodeDecodeError, TypeError):
            continue
    if stock_list_df is None:
        print(f"錯誤: 無法讀取檔案 '{csv_filepath}'，請檢查編碼。")
        return {}
    if column_name not in stock_list_df.columns:
        print(f"CSV 欄位名稱錯誤。現有欄位: {list(stock_list_df.columns)}")
        return {}

    stock_symbols = stock_list_df[column_name].dropna().unique().tolist()
    ohlc_data = {}
    for symbol in stock_symbols:
        if not symbol or str(symbol).strip() == "":
            continue
        print(f"正在抓取 {symbol} 的資料...")
        try:
            data = yf.download(symbol, period=period, progress=False)
            if not data.empty:
                if isinstance(data.columns, pd.MultiIndex):
                    if symbol in data.columns.get_level_values(1):
                        data = data.xs(symbol, axis=1, level=1)
                    elif symbol in data.columns.get_level_values(0):
                        data = data.xs(symbol, axis=1, level=0)
                ohlc_data[symbol] = data
            else:
                ohlc_data[symbol] = None
        except Exception as e:
            print(f"抓取 {symbol} 錯誤: {e}")
            ohlc_data[symbol] = None
    return ohlc_data


def flatten_and_save_ohlc(ohlc_dict, output_filename):
    all_frames = []
    for ticker, df_ticker in ohlc_dict.items():
        if df_ticker is not None and not df_ticker.empty:
            cols = [c for c in ["Close", "High", "Low", "Open"] if c in df_ticker.columns]
            temp_df = df_ticker[cols].copy().reset_index()
            temp_df.insert(0, "Ticker", ticker)
            all_frames.append(temp_df)
    if not all_frames:
        print("無有效資料可供轉換。")
        return None
    combined_df = pd.concat(all_frames, ignore_index=True)
    final_order = ["Ticker", "Date", "Close", "High", "Low", "Open"]
    combined_df = combined_df[[c for c in final_order if c in combined_df.columns]]
    combined_df.to_csv(output_filename, index=False, encoding="utf-8-sig")
    print(f"已儲存至: {output_filename}")
    return combined_df


def fetch_sp500():
    sp500_df = pd.read_csv(os.path.join(BASE, "SP500.csv"))
    sp500_data = [get_stock_info(t) for t in sp500_df["A"]]
    df = pd.DataFrame(sp500_data)
    df.to_csv(os.path.join(BASE, "sp500_stocks.csv"), index=False, encoding="UTF-8-SIG")
    return df


def fetch_aisoft():
    aisoft = pd.read_csv(os.path.join(TABLEAU, "AIsoftware_en.csv"), encoding="UTF-8-SIG")
    aisoft_data = [get_stock_info(t) for t in aisoft["stock"]]
    aisoft_data = pd.DataFrame(aisoft_data)
    aisoft_df = aisoft_data[aisoft_data["Market Cap"] > 0].sort_values(by="Market Cap", ascending=False)
    aisoft_df.rename(columns={"Ticker": "stock"}, inplace=True)
    aisoft_df = aisoft_df.merge(aisoft, on="stock", how="left")
    aisoft_df.to_csv(os.path.join(BASE, "aisoft_df.csv"), index=False, encoding="UTF-8-SIG")
    return aisoft_df


def fetch_memory():
    memory_concept_list = ["MU", "005930.KS", "000660.KS", "603986.SS"]
    nandflash_concept_list = ["SNDK", "285A.T"]
    taiwan_dram_concept_list = ["2408.TW", "2344.TW"]
    g_m_concept_list = memory_concept_list + nandflash_concept_list + taiwan_dram_concept_list

    memory_data = [get_stock_info(t) for t in g_m_concept_list]
    memory_data = pd.DataFrame(memory_data)
    memory_data.rename(columns={"Ticker": "stock"}, inplace=True)
    memory_data["ethnic_group"] = (
        ["Memory_concept"] * len(memory_concept_list)
        + ["NandFlash_concept"] * len(nandflash_concept_list)
        + ["Taiwan_Dram_concept"] * len(taiwan_dram_concept_list)
    )
    memory_data = memory_data[memory_data["Market Cap"] > 0].sort_values(by="Market Cap", ascending=False)
    # FIX: was encoding="big5" in the original notebook, inconsistent with the rest
    # of the pipeline (UTF-8-SIG) and unable to encode arbitrary Unicode company names.
    memory_data.to_csv(os.path.join(BASE, "Memory_data.csv"), index=False, encoding="UTF-8-SIG")
    return memory_data


def combine_sp500_memory():
    sp500 = pd.read_csv(os.path.join(BASE, "sp500_stocks.csv"), encoding="UTF-8-SIG")
    memory = pd.read_csv(os.path.join(BASE, "Memory_data.csv"), encoding="UTF-8-SIG")
    combined = pd.concat([sp500, memory], ignore_index=True)
    combined.to_csv(os.path.join(BASE, "SP550_memory_combined.csv"), index=False, encoding="UTF-8-SIG")
    return combined


if __name__ == "__main__":
    print("== sp500 fundamentals ==")
    fetch_sp500()
    print("== aisoft (software concept) fundamentals ==")
    fetch_aisoft()
    print("== memory concept fundamentals ==")
    fetch_memory()
    print("== combine sp500 + memory ==")
    combine_sp500_memory()

    print("== Memory OHLC ==")
    ohlc = get_adjusted_ohlc_from_csv(os.path.join(BASE, "Memory_data.csv"), column_name="stock", period="12Y")
    flatten_and_save_ohlc(ohlc, os.path.join(BASE, "Memory_ohlc.csv"))

    print("== sp500 OHLC ==")
    sp500_ohlc = get_adjusted_ohlc_from_csv(os.path.join(BASE, "sp500_stocks.csv"), column_name="Ticker", period="12y")
    flatten_and_save_ohlc(sp500_ohlc, os.path.join(BASE, "sp500_ohlc.csv"))

    print("All done.")
