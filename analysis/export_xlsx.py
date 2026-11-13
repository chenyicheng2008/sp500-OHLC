"""Export the bull-bear spread and the rebuilt index series to an Excel workbook.

Sheets: 說明 (definitions, dates, limits), 摘要 (key readings as formulas over the data
sheets), 週線 / 日線 (time series; derived columns are formulas), 背離, 週期段落,
成分股_AI硬體 / 成分股_半導體 / 成分股_科技, and two line charts.

Run after ``regime_backtest.py`` (reads data/analysis/*). Usage:
    python analysis/export_xlsx.py            # -> analysis/reports/ai_spread_<asof>.xlsx
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from breadth_sector import ENC, load, pivot, drop_empty_sessions
from regime_backtest import INDICES, chain_index

REPO = Path(__file__).resolve().parent.parent
A = REPO / "data" / "analysis"
FONT = "Arial"
F = Font(name=FONT, size=10)
FB = Font(name=FONT, size=10, bold=True)
FH = Font(name=FONT, size=10, bold=True, color="FFFFFF")
FT = Font(name=FONT, size=14, bold=True)
FN = Font(name=FONT, size=9, color="666666")
HEAD = PatternFill("solid", fgColor="1F3A5F")
THIN = Border(bottom=Side(style="thin", color="D0D5DD"))
STATE_TC = {"bull": "多頭", "neither": "整理", "bear": "空頭"}
GRP_TC = {"AI Compute Chips": "AI 運算晶片", "Memory and Storage": "記憶體與儲存",
          "AI Servers and Networking": "AI 伺服器與網通", "Optical Communication": "光通訊",
          "Connectors and Components": "連接器與零組件", "Semiconductor Equipment": "半導體設備",
          "Data Center Power and Cooling": "資料中心電力與散熱"}


def industry_names() -> dict:
    """Reuse the report's zh industry names (IND_TC in the template) so both outputs agree."""
    tpl = (REPO / "analysis" / "report_template.html").read_text(encoding="utf-8")
    m = re.search(r"var IND_TC = \{(.*?)\};", tpl, re.S)
    return dict(re.findall(r'"([^"]+)":\s*"([^"]+)"', m.group(1))) if m else {}


def header(ws, row, cols, widths=None):
    for j, c in enumerate(cols, 1):
        cell = ws.cell(row=row, column=j, value=c)
        cell.font, cell.fill = FH, HEAD
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 30
    if widths:
        for j, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = ws.cell(row=row + 1, column=2)


def put(ws, r, c, v, fmt=None, font=F):
    cell = ws.cell(row=r, column=c, value=None if (isinstance(v, float) and np.isnan(v)) else v)
    cell.font = font
    if fmt:
        cell.number_format = fmt
    return cell


def daily_indices(start: str) -> pd.DataFrame:
    """Same rebuilt indices as the weekly ones, chain-linked day to day, = 100 at `start`."""
    ohlc, fund, _ = load(REPO / "data" / "weekly_reutin")
    daily, _ = drop_empty_sessions(pivot(ohlc, "1d", "Close"))
    meta = fund.set_index("Ticker")
    last = daily.ffill().iloc[-1].reindex(meta.index)
    shares = (meta["Market Cap"] / last).replace([np.inf, -np.inf, 0], np.nan).dropna()
    out = {}
    for k, (_, sel) in INDICES.items():
        cols = [t for t in meta.index[sel(meta)] if t in daily.columns and t in shares.index]
        lvl = chain_index(daily, shares, cols).loc[start:]
        out[k] = 100 * lvl / lvl.iloc[0]
    return pd.DataFrame(out)


def main() -> None:
    rb = json.load(open(A / "regime_backtest.json", encoding="utf-8"))
    tr = json.load(open(A / "trend_regime_bundle.json", encoding="utf-8"))
    rd = json.load(open(A / "report_data.json", encoding="utf-8"))
    tw = pd.read_csv(A / "trend_regime_weekly.csv", index_col=0, parse_dates=True)
    bw = pd.read_csv(A / "regime_backtest_weekly.csv", index_col=0, parse_dates=True)
    td = pd.read_csv(A / "trend_regime_daily.csv", index_col=0, parse_dates=True)
    asof, U = rb["asof"], rb["universe_label"]
    labels = {k: rb["indices"][k]["label"] for k in INDICES}
    di = daily_indices(td.index[0].strftime("%Y-%m-%d"))
    ind_tc = industry_names()

    wb = Workbook()
    # ------------------------------------------------------------------ 週線
    ws = wb.active
    ws.title = "週線"
    cols = ["週（週五）", f"{U} 多頭排列 %", "整理 %", "空頭排列 %", f"{U} 多空排列差", "S&P 500 全體 多空排列差",
            f"{labels['tech']}指數", f"{labels['semi']}指數",
            "科技 距高點", "半導體 距高點", "多空排列差 4 週變化", "科技 13 週報酬", "半導體 13 週報酬",
            f"{rb['ew']['label']}指數", "等權重 距高點"]
    widths = [12, 11, 9, 10, 12, 13, 12, 13, 10, 11, 12, 11, 12, 14, 11]
    OFF = (rb.get("official") or {}).get("tech") or {}
    has_off = bool(OFF.get("available")) and "tech_off" in bw
    if has_off:               # official S&P 500 IT, rebased onto the rebuilt tech line
        cols += [f"官方 {OFF['symbol']}", "官方 距高點"]
        widths += [13, 11]
    header(ws, 1, cols, widths)
    w = bw.join(tw[["sec_bull", "sec_neither", "sec_bear", "mkt_net"]], how="left")
    for i, (d, r) in enumerate(w.iterrows(), start=2):
        put(ws, i, 1, d.date(), "yyyy-mm-dd")
        for c, key in zip(range(2, 9), ["sec_bull", "sec_neither", "sec_bear", "net", "mkt_net", "tech", "semi"]):
            put(ws, i, c, round(float(r[key]), 2), "0.0" if c <= 6 else "#,##0.0")
        # derived columns are formulas over the data columns
        put(ws, i, 9, f"=G{i}/MAX(G$2:G{i})-1", "0.0%")
        put(ws, i, 10, f"=H{i}/MAX(H$2:H{i})-1", "0.0%")
        put(ws, i, 11, f"=E{i}-E{i-4}" if i >= 6 else None, "+0.0;-0.0;0")
        put(ws, i, 12, f"=G{i}/G{i-13}-1" if i >= 15 else None, "0.0%")
        put(ws, i, 13, f"=H{i}/H{i-13}-1" if i >= 15 else None, "0.0%")
        put(ws, i, 14, round(float(r["aihw"]), 2), "#,##0.0")
        put(ws, i, 15, f"=N{i}/MAX(N$2:N{i})-1", "0.0%")
        if has_off and pd.notna(r["tech_off"]):
            put(ws, i, 16, round(float(r["tech_off"]), 2), "#,##0.0")
            put(ws, i, 17, f"=P{i}/MAX(P$2:P{i})-1", "0.0%")
    nW = len(w) + 1
    ws.cell(row=1, column=5).comment = Comment("多頭排列占比 − 空頭排列占比（百分點），-100～+100。週線用 10 週與 40 週均線。", "export")
    ws.cell(row=1, column=14).comment = Comment(f"多空排列差同一批 {rb['ew']['n']} 檔，每週取各檔報酬的簡單平均後連乘，"
                                                 "2015-08-14 = 100；用今天的名單回推，早年偏高（存活者偏差）。", "export")
    ws.cell(row=1, column=7).comment = Comment("成分股重建的市值加權指數，逐週連鎖，2015-08-14 = 100。股數以最新市值÷最新收盤固定，非官方指數。", "export")

    # ------------------------------------------------------------------ 日線
    wd = wb.create_sheet("日線")
    cols = ["交易日", f"{U} 多頭排列 %", "整理 %", "空頭排列 %", f"{U} 多空排列差", "S&P 500 全體 多空排列差",
            f"{labels['tech']}指數", f"{labels['semi']}指數", "科技 距高點", "半導體 距高點", "多空排列差 20 日變化"]
    header(wd, 1, cols, [12, 11, 9, 10, 12, 13, 12, 13, 10, 11, 13])
    dd = td.join(di, how="left")
    for i, (d, r) in enumerate(dd.iterrows(), start=2):
        put(wd, i, 1, d.date(), "yyyy-mm-dd")
        for c, key in zip(range(2, 9), ["sec_bull", "sec_neither", "sec_bear", "sec_net", "mkt_net", "tech", "semi"]):
            put(wd, i, c, round(float(r[key]), 2), "0.0" if c <= 6 else "#,##0.00")
        put(wd, i, 9, f"=G{i}/MAX(G$2:G{i})-1", "0.0%")
        put(wd, i, 10, f"=H{i}/MAX(H$2:H{i})-1", "0.0%")
        put(wd, i, 11, f"=E{i}-E{i-20}" if i >= 22 else None, "+0.0;-0.0;0")
    nD = len(dd) + 1
    wd.cell(row=1, column=5).comment = Comment("日線用 50 日與 200 日均線；200 日均線需足夠歷史，所以日線從此表第一天開始。", "export")
    wd.cell(row=1, column=7).comment = Comment("同週線的重建方式，逐日連鎖，本表第一天 = 100（與週線指數基期不同）。", "export")

    # ------------------------------------------------------------------ 摘要 (formulas)
    sm = wb.create_sheet("摘要", 0)
    sm.column_dimensions["A"].width = 34
    sm.column_dimensions["B"].width = 16
    sm.column_dimensions["C"].width = 60
    put(sm, 1, 1, f"{U}多空排列差與科技／半導體指數", font=FT)
    rows = [
        ("資料日（最後交易日）", f"=MAX(日線!A2:A{nD})", "yyyy-mm-dd", "日線最後一列"),
        ("最新 多空排列差（日線）", f"=INDEX(日線!E2:E{nD},MATCH(B3,日線!A2:A{nD},0))", "+0.0;-0.0;0", "多頭排列占比 − 空頭排列占比"),
        ("最新 S&P 500 全體 多空排列差（日線）", f"=INDEX(日線!F2:F{nD},MATCH(B3,日線!A2:A{nD},0))", "+0.0;-0.0;0", "全部成分股，同一算法"),
        ("日線期間 多空排列差 最高", f"=MAX(日線!E2:E{nD})", "+0.0;-0.0;0", ""),
        ("日線期間 多空排列差 最低", f"=MIN(日線!E2:E{nD})", "+0.0;-0.0;0", ""),
        ("最新 多空排列差（週線）", f"=週線!E{nW}", "+0.0;-0.0;0", "週線最後一列"),
        ("週線 2015 年以來 最高", f"=MAX(週線!E2:E{nW})", "+0.0;-0.0;0", ""),
        ("週線 2015 年以來 最低", f"=MIN(週線!E2:E{nW})", "+0.0;-0.0;0", ""),
        ("週線 目前讀數的百分位（低於它的週數占比）", f"=COUNTIF(週線!E2:E{nW},\"<\"&B8)/COUNT(週線!E2:E{nW})", "0%", "0% = 期間最低"),
        ("科技 距高點（週線）", f"=週線!I{nW}", "0.0%", "重建指數距 2015 年以來最高點"),
        ("半導體 距高點（週線）", f"=週線!J{nW}", "0.0%", ""),
        ("多空排列差 與 過去 13 週科技報酬 的相關（Pearson）",
         f"=CORREL(週線!E15:E{nW},週線!L15:L{nW})", "0.00", "同一週的排列差與該週往回 13 週的報酬"),
        ("多空排列差 與 未來 13 週科技報酬 的相關（Pearson）",
         f"=CORREL(週線!E2:E{nW - 13},週線!L15:L{nW})", "0.00", "排列差與 13 週後才知道的報酬；接近 0 = 沒有預測力"),
    ]
    put(sm, 2, 1, "項目", font=FB); put(sm, 2, 2, "數值", font=FB); put(sm, 2, 3, "說明", font=FB)
    for r, (k, f, fmt, note) in enumerate(rows, start=3):
        put(sm, r, 1, k); put(sm, r, 2, f, fmt); put(sm, r, 3, note, font=FN)
    r0 = 3 + len(rows) + 1
    put(sm, r0, 1, "報告與回測的主要結論（由 regime_backtest.py 計算，數值為輸出當時的結果）", font=FB)
    bi = rb["by_index"]
    notes = [
        f"排名相關（Spearman）：與過去 13 週報酬 科技 {bi['tech']['corr_past']}、半導體 {bi['semi']['corr_past']}；"
        f"與未來 13 週最大跌幅 {bi['tech']['corr_fwd_mdd']:+}、{bi['semi']['corr_fwd_mdd']:+}。",
        f"背離 B 型（指數強、多空弱）：科技 {bi and rb['divergence']['by_index']['tech']['summary']['B']['n']} 次、"
        f"半導體 {rb['divergence']['by_index']['semi']['summary']['B']['n']} 次；明細見「背離」。",
        f"週期（轉折門檻 {rb['cycles']['main_swing']} 點）：平均 "
        f"{next(r['pp_mean'] for r in rb['cycles']['table'] if r['series'] == 'net' and r['swing'] == rb['cycles']['main_swing'])} 週；明細見「週期段落」。",
    ]
    for j, t in enumerate(notes, start=r0 + 1):
        put(sm, j, 1, t); sm.merge_cells(start_row=j, start_column=1, end_row=j, end_column=3)

    # ------------------------------------------------------------------ 背離
    dv = wb.create_sheet("背離")
    header(dv, 1, ["型態", "指數", "高點 1", "排列差 1", "高點 2", "排列差 2", "確認週", "指數高點變化",
                   "13 週後報酬", "26 週後報酬", "26 週內最大跌幅", "52 週內最大跌幅", "回落 5% 週數", "回落 10% 週數", "已滿 26 週"],
           [18, 10, 12, 9, 12, 9, 12, 11, 11, 11, 12, 12, 11, 11, 9])
    r = 2
    for k in INDICES:
        for x in rb["divergence"]["by_index"][k]["rows"]:
            vals = [("A 多空強、指數弱" if x["type"] == "A" else "B 指數強、多空弱"), labels[k],
                    date.fromisoformat(x["h1"]), x["h1_val"], date.fromisoformat(x["h2"]), x["h2_val"],
                    "待確認" if x["confirm_pending"] else date.fromisoformat(x["confirm"]),
                    x["idx_chg"] / 100, None if x["ret13"] is None else x["ret13"] / 100,
                    None if x["ret26"] is None else x["ret26"] / 100, x["mdd26"] / 100,
                    None if x["dip52"] is None else x["dip52"] / 100,
                    x["w5"] if x["w5"] is not None else "未出現", x["w10"] if x["w10"] is not None else "未出現",
                    "是" if x["complete"] else "否"]
            fmts = [None, None, "yyyy-mm-dd", "+0;-0;0", "yyyy-mm-dd", "+0;-0;0", "yyyy-mm-dd", "0.0%", "0.0%", "0.0%", "0.0%", "0.0%", "0", "0", None]
            for c, (v, fm) in enumerate(zip(vals, fmts), 1):
                put(dv, r, c, v, fm)
            r += 1
    put(dv, r + 1, 1, f"高點＝前後 {rb['divergence']['k']} 週內最高、至少 +{rb['divergence']['level']}；指數高點取前後 "
                      f"{rb['divergence']['w']} 週內最高。A：排列差高點不低於前一個 − {rb['divergence']['tol']} 點、指數未過前高；"
                      f"B：指數創更高的高點、排列差高點低於前一個超過 {rb['divergence']['tol']} 點。", font=FN)

    # ------------------------------------------------------------------ 週期段落
    cy = wb.create_sheet("週期段落")
    header(cy, 1, ["段落", "起點", "終點", "週數", "排列差 起", "排列差 迄", "科技報酬", "半導體報酬"], [8, 12, 12, 8, 10, 10, 11, 12])
    for i, l in enumerate(rb["cycles"]["legs"], start=2):
        vals = ["上升" if l["dir"] == "up" else "下降", date.fromisoformat(l["start"]),
                date.fromisoformat(l["end"]) if l["end"] else "進行中", l["weeks"], l["from"], l["to"],
                l["tech"] / 100, l["semi"] / 100]
        for c, (v, fm) in enumerate(zip(vals, [None, "yyyy-mm-dd", "yyyy-mm-dd", "0", "+0;-0;0", "+0;-0;0", "0.0%", "0.0%"]), 1):
            put(cy, i, c, v, fm)
    nL = len(rb["cycles"]["legs"]) + 1
    put(cy, nL + 2, 1, "上升段平均", font=FB)
    put(cy, nL + 3, 1, "下降段平均", font=FB)
    for row, lab in ((nL + 2, "上升"), (nL + 3, "下降")):
        # the open (進行中) leg has text in column C, so only confirmed legs are averaged
        put(cy, row, 4, f'=AVERAGEIFS(D2:D{nL},A2:A{nL},"{lab}",C2:C{nL},"<>進行中")', "0")
        put(cy, row, 7, f'=AVERAGEIFS(G2:G{nL},A2:A{nL},"{lab}",C2:C{nL},"<>進行中")', "0.0%")
        put(cy, row, 8, f'=AVERAGEIFS(H2:H{nL},A2:A{nL},"{lab}",C2:C{nL},"<>進行中")', "0.0%")
    put(cy, nL + 5, 1, f"轉折以 zig-zag 認定：反向走 {rb['cycles']['main_swing']} 點才確認高低點。最後一段到資料日尚未確認，不計入平均。", font=FN)

    # ------------------------------------------------------------------ 成分股
    for key, title in (("universe", "成分股_AI硬體"), ("semi", "成分股_半導體"), ("tech", "成分股_科技")):
        cs = wb.create_sheet(title)
        first = "族群" if key == "universe" else "產業（Yahoo 分類）"
        header(cs, 1, ["代號", "名稱", first, "市值（十億美元）", "權重", "目前排列", "近一月報酬", "距一年高點"],
               [8, 34, 22, 14, 9, 9, 11, 11])
        rows_ = rb["constituents"][key]
        for i, x in enumerate(rows_, start=2):
            grp = GRP_TC.get(x["group"], x["group"]) if key == "universe" else ind_tc.get(x["industry"], x["industry"])
            vals = [x["ticker"], x["name"], grp, x["cap_bn"], None, STATE_TC.get(x["state"], ""),
                    None if x["ret_1m"] is None else x["ret_1m"] / 100, None if x["from_high"] is None else x["from_high"] / 100]
            for c, (v, fm) in enumerate(zip(vals, [None, None, None, "#,##0.0", None, None, "0.0%", "0.0%"]), 1):
                put(cs, i, c, v, fm)
            put(cs, i, 5, f"=D{i}/SUM(D$2:D${len(rows_) + 1})", "0.0%")   # weight from the cap column
        n = len(rows_) + 1
        put(cs, n + 1, 3, "合計", font=FB)
        put(cs, n + 1, 4, f"=SUM(D2:D{n})", "#,##0.0", FB)
        put(cs, n + 1, 5, f"=SUM(E2:E{n})", "0.0%", FB)
        put(cs, n + 3, 1, ("多空排列差每檔一票，權重只供參考。" if key == "universe" else "重建指數依此權重（固定股數）計算。") +
            "排列依最新日線：多頭＝收盤 > 50 日 > 200 日均線，空頭反之。", font=FN)

    # ------------------------------------------------------------------ 圖表
    ch = wb.create_sheet("圖表")
    c1 = LineChart(); c1.title = f"{U} 多空排列差（週線）"; c1.height, c1.width = 9, 26
    c1.add_data(Reference(ws, min_col=5, max_col=6, min_row=1, max_row=nW), titles_from_data=True)
    c1.set_categories(Reference(ws, min_col=1, min_row=2, max_row=nW))
    c1.y_axis.title = "多空排列差"; c1.y_axis.scaling.min, c1.y_axis.scaling.max = -100, 100
    c1.x_axis.number_format = "yyyy"; c1.x_axis.tickLblSkip = 52
    ch.add_chart(c1, "A1")
    c2 = LineChart(); c2.title = f"科技／半導體／{rb['ew']['label']} 重建指數（週線，2015-08 = 100，對數刻度）"; c2.height, c2.width = 9, 26
    c2.add_data(Reference(ws, min_col=7, max_col=8, min_row=1, max_row=nW), titles_from_data=True)
    c2.add_data(Reference(ws, min_col=14, max_col=14, min_row=1, max_row=nW), titles_from_data=True)
    if has_off:
        c2.add_data(Reference(ws, min_col=16, max_col=16, min_row=1, max_row=nW), titles_from_data=True)
    c2.set_categories(Reference(ws, min_col=1, min_row=2, max_row=nW))
    c2.y_axis.scaling.logBase = 10
    c2.x_axis.number_format = "yyyy"; c2.x_axis.tickLblSkip = 52
    ch.add_chart(c2, "A20")

    # ------------------------------------------------------------------ 說明
    rm = wb.create_sheet("說明", 0)
    rm.column_dimensions["A"].width = 22
    rm.column_dimensions["B"].width = 100
    put(rm, 1, 1, f"{U}多空排列差 資料檔", font=FT)
    info = [
        ("資料日", asof),
        ("檔案產出", rd.get("generated") or date.today().isoformat()),
        ("來源", "yfinance 日線／週線收盤（data/weekly_reutin/sp500_ohlc.csv），由 repo 的分析程式計算。"),
        ("名單", f"{U} {tr['n_members']} 檔（data/tableau/{tr['universe'].get('source', '')}），明細見「成分股_AI硬體」。"),
        ("多空排列差", "每檔每天判斷：多頭排列＝收盤 > 50 日均線 > 200 日均線；空頭排列＝收盤 < 50 日 < 200 日；其餘為整理。"
                   "多空排列差＝多頭排列占比 − 空頭排列占比（百分點，-100～+100），每檔一票。週線改用 10 週與 40 週均線。"),
        ("指數", f"{labels['tech']}（{rb['indices']['tech']['n']} 檔，Yahoo technology 類股）與 {labels['semi']}"
               f"（{rb['indices']['semi']['n']} 檔，Yahoo 半導體＋半導體設備產業）：S&P 500 成分股以市值加權、逐期連鎖重建，"
               "股數以最新市值÷最新收盤固定。不是官方指數。"),
        ("官方指數", (f"{OFF['label']}（{OFF['symbol']}，週線 P 欄）：每日抓取的官方收盤，以第一個共同週對齊重建科技指數的水準。"
                     f"共同期間週報酬相關 {OFF['corr_wk']:.2f}、年化追蹤誤差 {OFF['te_ann']:.1f}%。只供對照，統計仍用重建指數。")
                    if has_off else f"{OFF.get('symbol', '^SP500-45')}：資料檔還沒有官方指數（index_ohlc.csv），有資料後才會出現在週線表。"),
        ("等權重指數", f"{rb['ew']['label']}指數（週線 N 欄）：{U}名單 {rb['ew']['n']} 檔，每週取各檔報酬的簡單平均後連乘，"
                   f"晚上市的成分（{rb['ew']['n'] - rb['ew']['n_start']} 檔）上市後才加入。和多空排列差是同一批股票，只供對照，"
                   "不用於任何統計。"),
        ("限制", "名單與指數成分都用今天的名單回推（存活者偏差，早年偏樂觀）；固定股數忽略增資、買回與成分變動；"
               f"半導體指數與{U}名單重疊 {rb['indices']['semi']['overlap_n']} 檔（市值 {rb['indices']['semi']['overlap_cap']:.0f}%）。"),
        ("工作表", "摘要（公式）、週線、日線、背離、週期段落、成分股_AI硬體／半導體／科技、圖表。"
                 "距高點、變化與報酬欄、權重與摘要都是公式，改動資料欄會自動重算。"),
        ("重新產生", "python analysis/export_xlsx.py（先依序跑 breadth_sector → trend_regime → regime_backtest → build_report_data）。"),
        ("聲明", "僅為數據整理，非投資建議。"),
    ]
    for i, (k, v) in enumerate(info, start=3):
        put(rm, i, 1, k, font=FB)
        c = put(rm, i, 2, v); c.alignment = Alignment(wrap_text=True, vertical="top")
        rm.row_dimensions[i].height = 15 * max(1, len(str(v)) // 60 + 1)

    out = REPO / "analysis" / "reports" / f"ai_spread_{asof}.xlsx"
    wb.save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
