/* McClellan oscillator panel, shared by the S&P 500 report and the ^SOX review.
   Inlined into both pages at build time (build_report.py, sox_review.py). Every figure and
   every comparison word comes from the payload made by analysis/mcclellan.py. */
window.MCC = (function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg", MONO = "IBM Plex Mono, monospace", RANGE = {};
  function el(tag, at, txt) {
    var e = document.createElementNS(NS, tag);
    for (var k in at) if (at[k] !== null && at[k] !== undefined) e.setAttribute(k, at[k]);
    if (txt !== undefined) e.textContent = txt;
    return e;
  }
  var css = function (v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); };
  var sg = function (v, d) { return (v > 0 ? "+" : "") + v.toFixed(d === undefined ? 1 : d); };
  var pc = function (v, d) { return v === null || v === undefined ? "—" : sg(v, d === undefined ? 1 : d) + "%"; };
  var fmt = function (v) { return Math.round(v).toLocaleString("en-US"); };
  var tip = function () { return document.getElementById("tip"); };
  function showTip(html, ev) {
    var t = tip(); if (!t) return;
    t.innerHTML = html; t.style.opacity = 1;
    var x = ev.clientX + 14, y = ev.clientY + 14, r = t.getBoundingClientRect();
    if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - 14;
    if (y + r.height > innerHeight - 8) y = ev.clientY - r.height - 14;
    t.style.left = x + "px"; t.style.top = y + "px";
  }
  function hideTip() { var t = tip(); if (t) t.style.opacity = 0; }

  function chart(host, M, o, a) {
    var n = M.dates.length - a, dates = M.dates.slice(a), osc = M.osc.slice(a), sum = M.sum.slice(a), idx = M.idx.slice(a);
    var w = Math.max(320, host.clientWidth), small = w < 520;
    var m = { l: small ? 46 : 54, r: small ? 58 : 72 };
    var P1 = { y: 10, h: small ? 130 : 160 }, P2 = { y: 0, h: small ? 130 : 160 }, P3 = { y: 0, h: small ? 90 : 110 };
    P2.y = P1.y + P1.h + 22; P3.y = P2.y + P2.h + 22;
    var h = P3.y + P3.h + 26, iw = w - m.l - m.r, svg = el("svg", { width: w, height: h, viewBox: "0 0 " + w + " " + h });
    svg.style.display = "block";
    var ink3 = css("--ink-3"), rule = css("--rule"), pos = css("--pos"), neg = css("--neg"), ink2 = css("--ink-2");
    var step = iw / n, X = function (i) { return m.l + step * (i + 0.5); };
    var scale = function (P, lo, hi) { return function (v) { return P.y + P.h * (1 - (v - lo) / ((hi - lo) || 1)); }; };
    var ticks = function (lo, hi, k) {
      var raw = (hi - lo) / k, mag = Math.pow(10, Math.floor(Math.log10(raw))), st = [1, 2, 2.5, 5, 10].map(function (f) { return f * mag; }).filter(function (x) { return x >= raw; })[0], out = [];
      for (var v = Math.ceil(lo / st) * st; v <= hi + 1e-9; v += st) out.push(v);
      return out;
    };
    var axis = function (P, Y, lo, hi, k, lab) {
      ticks(lo, hi, k).forEach(function (v) {
        svg.appendChild(el("line", { x1: m.l, x2: m.l + iw, y1: Y(v), y2: Y(v), stroke: v === 0 ? css("--axis") : rule }));
        svg.appendChild(el("text", { x: m.l - 6, y: Y(v) + 4, "text-anchor": "end", fill: ink3, "font-size": 10.5, "font-family": MONO }, lab(v)));
      });
    };
    var mn = function (a) { return Math.min.apply(null, a); }, mx = function (a) { return Math.max.apply(null, a); };
    // panel titles
    [[P1, o.idxName], [P2, "麥克連擺盪指標"], [P3, "總和指標（Summation Index）"]].forEach(function (p) {
      svg.appendChild(el("text", { x: m.l + 4, y: p[0].y + 11, fill: ink3, "font-size": 10.5 }, p[1]));
    });
    // 1: index
    var ilo = mn(idx) * 0.98, ihi = mx(idx) * 1.02, Y1 = scale(P1, ilo, ihi);
    axis(P1, Y1, ilo, ihi, 3, function (v) { return v >= 1000 ? (v / 1000).toFixed(1) + "k" : String(Math.round(v)); });
    var d = ""; idx.forEach(function (v, i) { d += (i ? "L" : "M") + X(i).toFixed(1) + " " + Y1(v).toFixed(1); });
    svg.appendChild(el("path", { d: d, fill: "none", stroke: css("--ink"), "stroke-width": 1.6 }));
    // 2: oscillator bars with the thresholds
    var olo = Math.min(mn(osc), M.lo) * 1.1, ohi = Math.max(mx(osc), M.hi) * 1.1, Y2 = scale(P2, olo, ohi);
    axis(P2, Y2, olo, ohi, 4, function (v) { return String(Math.round(v)); });
    var bw = Math.max(1, step * 0.7);
    osc.forEach(function (v, i) {
      var y0 = Y2(0), y1 = Y2(v);
      svg.appendChild(el("rect", { x: X(i) - bw / 2, y: Math.min(y0, y1), width: bw, height: Math.max(0.5, Math.abs(y1 - y0)), fill: v >= 0 ? pos : neg,
        opacity: (v <= M.lo || v >= M.hi) ? 1 : 0.55 }));
    });
    [M.lo, M.hi].forEach(function (t) {
      svg.appendChild(el("line", { x1: m.l, x2: m.l + iw, y1: Y2(t), y2: Y2(t), stroke: css("--warn"), "stroke-width": 1.2, "stroke-dasharray": "4 3" }));
      svg.appendChild(el("text", { x: m.l + iw + 4, y: Y2(t) + 4, fill: ink2, "font-size": 10, "font-family": MONO }, sg(t, 0)));
    });
    // 3: summation index
    var slo = mn(sum), shi = mx(sum), pad = (shi - slo) * 0.08 || 10, Y3 = scale(P3, slo - pad, shi + pad);
    axis(P3, Y3, slo - pad, shi + pad, 3, function (v) { return fmt(v); });
    d = ""; sum.forEach(function (v, i) { d += (i ? "L" : "M") + X(i).toFixed(1) + " " + Y3(v).toFixed(1); });
    svg.appendChild(el("path", { d: d, fill: "none", stroke: css("--s4"), "stroke-width": 1.6 }));
    // end labels
    var endLab = function (y, t) { svg.appendChild(el("text", { x: m.l + iw + 4, y: y + 4, fill: ink2, "font-size": 10.5, "font-weight": 600, "font-family": MONO }, t)); };
    endLab(Y1(idx[n - 1]), idx[n - 1] >= 1000 ? fmt(idx[n - 1]) : idx[n - 1].toFixed(1));
    var yo = Y2(osc[n - 1]); if (Math.abs(yo - Y2(M.lo)) < 11) yo = Y2(M.lo) + 12; if (Math.abs(yo - Y2(M.hi)) < 11) yo = Y2(M.hi) - 12;
    endLab(yo, sg(osc[n - 1], 0));
    endLab(Y3(sum[n - 1]), fmt(sum[n - 1]));
    // dates
    var stp = Math.max(1, Math.round(n / (small ? 4 : 7)));
    for (var q = 0; q < n; q += stp) {
      if (n - 1 - q < stp * 0.5 && q) continue;
      svg.appendChild(el("text", { x: X(q), y: h - 8, "text-anchor": q ? "middle" : "start", fill: ink3, "font-size": 10.5, "font-family": MONO }, dates[q].slice(2, 7).replace("-", "/")));
    }
    svg.appendChild(el("text", { x: X(n - 1), y: h - 8, "text-anchor": "end", fill: ink3, "font-size": 10.5, "font-family": MONO }, dates[n - 1].slice(5).replace("-", "/")));
    var cross = el("line", { y1: P1.y, y2: P3.y + P3.h, stroke: css("--ink"), opacity: 0 }); svg.appendChild(cross);
    var hit = el("rect", { x: m.l, y: P1.y, width: iw, height: P3.y + P3.h - P1.y, fill: "transparent" });
    hit.addEventListener("mousemove", function (ev) {
      var bb = svg.getBoundingClientRect(), i = Math.max(0, Math.min(n - 1, Math.floor((ev.clientX - bb.left - m.l) / step)));
      cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i)); cross.setAttribute("opacity", 0.3);
      showTip("<div class='tt-h'>" + dates[i] + "</div><div class='tt-r'><span>" + o.idxName + "</span><b>" + (idx[i] >= 1000 ? fmt(idx[i]) : idx[i].toFixed(1)) + "</b></div>" +
        "<div class='tt-r'><span>擺盪指標</span><b>" + sg(osc[i], 1) + "</b></div><div class='tt-r'><span>總和指標</span><b>" + fmt(sum[i]) + "</b></div>", ev);
    });
    hit.addEventListener("mouseleave", function () { hideTip(); cross.setAttribute("opacity", 0); });
    svg.appendChild(hit);
    host.innerHTML = ""; host.appendChild(svg);
  }

  function rangeButtons(host, M, o, redraw) {
    var N = M.dates.length, cur = RANGE[o.key] === undefined ? Infinity : RANGE[o.key];
    host.innerHTML = "";
    [["3 個月", 63], ["6 個月", 126], ["1 年", 252], ["全部", Infinity]].forEach(function (p) {
      if (p[1] !== Infinity && p[1] >= N) return;
      var b = document.createElement("button"); b.type = "button"; b.textContent = p[0];
      if (cur === p[1]) b.className = "on";
      b.setAttribute("aria-pressed", cur === p[1] ? "true" : "false");
      b.addEventListener("click", function () { RANGE[o.key] = p[1]; redraw(); });
      host.appendChild(b);
    });
    return Math.max(0, N - Math.min(N, cur));
  }

  function words(M, o) {
    var NM = (/^[A-Za-z^]/.test(o.idxName) ? " " : "") + o.idxName +                // CJK / Latin spacing
      (/[A-Za-z0-9]$/.test(o.idxName) ? " " : "");
    var lv = function (v) { return v >= 1000 ? fmt(v) : v.toFixed(1); };
    var Z = M.now, S = M.signals, B = M.base, V = M.div, H = M.fwd[M.fwd.length - 1], out = [];
    var zoneTxt = Z.zone === "oversold" ? "落在超賣區（≤ " + sg(M.lo, 0) + "）" : Z.zone === "overbought" ? "落在超買區（≥ " + sg(M.hi, 0) + "）" : "在超買與超賣門檻之間";
    var pTxt = Z.pctile <= 0 ? "為期間最低" : Z.pctile >= 99.5 ? "為期間最高" : "在期間第 " + Z.pctile.toFixed(0) + " 百分位";
    out.push("現在：擺盪指標 " + sg(Z.osc) + "，" + pTxt + "，" + zoneTxt + "；" +
      (Z.cross_date ? Z.since_cross + " 個交易日前（" + Z.cross_date + "）" + (Z.above_zero ? "由負轉正" : "由正轉負") + "。" : "期間沒有穿越零軸。") +
      "期間最低 " + sg(Z.min) + "（" + Z.min_date + "）、最高 " + sg(Z.max) + "（" + Z.max_date + "）。");
    out.push("總和指標 " + fmt(Z.sum) + "，近 10 個交易日" + (Z.sum_chg10 < 0 ? "下降 " + fmt(-Z.sum_chg10) : Z.sum_chg10 > 0 ? "上升 " + fmt(Z.sum_chg10) : "持平") +
      "——" + (Z.sum_chg10 < 0 ? "這 10 天的擺盪指標加總為負，下跌家數占上風。" : Z.sum_chg10 > 0 ? "這 10 天的擺盪指標加總為正，上漲家數占上風。" : "上漲與下跌家數大致相抵。"));
    var basePos = 100 * B.pos / B.n;
    ["oversold", "overbought"].forEach(function (k) {
      var s = S[k], thr = k === "oversold" ? "跌到 " + sg(M.lo, 0) + " 以下" : "升到 " + sg(M.hi, 0) + " 以上";
      if (!s.n) { out.push("期間擺盪指標沒有" + thr + "過。"); return; }
      var t = "過去" + thr + " " + s.n + " 次（" + M.gap + " 個交易日內重複只算一次）";
      if (!s.n_done) { out.push(t + "，都還不到 " + H + " 個交易日，看不到結果。"); return; }
      var gap = s.median - B.median;
      t += "：已有 " + H + " 日結果的 " + s.n_done + " 次，之後 " + H + " 個交易日" + NM + "報酬中位數 " + pc(s.median, 2) + "、上漲 " + s.pos + " 次；" +
        "所有交易日的同一數字是 " + pc(B.median, 2) + "、上漲占 " + basePos.toFixed(0) + "%，" +
        (Math.abs(gap) < 1 ? "相差不大。" : gap > 0 ? "訊號之後較好。" : "訊號之後較差。") + "樣本只有 " + s.n_done + " 次，只能當參考。";
      out.push(t);
    });
    var lowTxt = "近 " + M.recent + " 個交易日" + NM + "低點 " + lv(V.idx_low_recent) + "，前一段（再往前 " + (M.prior - M.recent) + " 日）低點 " + lv(V.idx_low_prior);
    var oscLow = "；擺盪指標低點 " + sg(V.osc_low_recent) + " 對 " + sg(V.osc_low_prior);
    var highTxt = "近 " + M.recent + " 個交易日" + NM + "高點 " + lv(V.idx_high_recent) + "，前一段高點 " + lv(V.idx_high_prior);
    var oscHigh = "；擺盪指標高點 " + sg(V.osc_high_recent) + " 對 " + sg(V.osc_high_prior);
    out.push("背離：" + ({
      positive: lowTxt + oscLow + "。指數創低、擺盪指標的低點卻較高，是正背離：跌的家數沒有跟著擴大，常出現在跌勢後段，但不保證已經見底。",
      confirmed_down: lowTxt + oscLow + "。指數與擺盪指標同步創低，下跌家數仍在擴散，沒有背離。",
      flat_down: lowTxt + oscLow + "。指數創低，擺盪指標低點和前一段相差不到 " + V.tol + " 點，看不出背離。",
      negative: highTxt + oscHigh + "。指數創高、擺盪指標的高點卻較低，是負背離：上漲集中在較少的股票。",
      confirmed_up: highTxt + oscHigh + "。指數與擺盪指標同步創高，上漲家數同步擴散，沒有背離。",
      flat_up: highTxt + oscHigh + "。指數創高，擺盪指標高點和前一段相差不到 " + V.tol + " 點，看不出背離。",
      none: "近 " + M.recent + " 個交易日" + NM + "既沒有跌破、也沒有突破前一段的高低點，不適用背離判讀。"
    })[V.kind]);
    return out;
  }

  function render(M, o) {
    var redraw = function () {
      var a = rangeButtons(document.getElementById(o.ids.rb), M, o, redraw);
      chart(document.getElementById(o.ids.chart), M, o, a);
    };
    redraw();
    document.getElementById(o.ids.lg).innerHTML =
      "<span><i class='swatch' style='background:" + css("--ink") + "'></i>" + o.idxName + "</span>" +
      "<span><i class='swatch' style='background:" + css("--pos") + "'></i>擺盪指標 &gt; 0</span><span><i class='swatch' style='background:" + css("--neg") + "'></i>擺盪指標 &lt; 0</span>" +
      "<span><i class='swatch' style='background:" + css("--warn") + "'></i>超買／超賣門檻</span><span><i class='swatch' style='background:" + css("--s4") + "'></i>總和指標</span>";
    document.getElementById(o.ids.def).textContent = "擺盪指標＝每日（上漲家數 − 下跌家數）÷（上漲 + 下跌 + 平盤）× 1000，取 19 日與 39 日指數移動平均之差；總和指標是擺盪指標的逐日累加。" +
      "計算範圍：" + o.groupName + "。門檻 " + (M.fixed ? sg(M.lo, 0) + "／" + sg(M.hi, 0) + "（與廣度訊號板相同）" :
        sg(M.lo, 0) + "／" + sg(M.hi, 0) + "，取本組自己期間第 10／90 百分位——檔數少，擺盪幅度比全市場大，套用全市場的門檻會太常觸發") +
      "。前 " + M.warmup + " 個交易日是均線暖機期，不列入；資料期間 " + M.dates[0] + " 至 " + M.dates[M.dates.length - 1] + "。";
    document.getElementById(o.ids.cap).textContent = "深色長條是超出門檻的交易日。按鈕只改變畫面範圍，下方解讀是全期數字。";
    document.getElementById(o.ids.take).innerHTML = words(M, o).map(function (t, i) {
      return "<li data-i='" + String(i + 1).padStart(2, "0") + "'><span>" + t + "</span></li>";
    }).join("");
  }
  return { render: render };
})();
