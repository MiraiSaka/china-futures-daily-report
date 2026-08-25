# -*- coding: utf-8 -*-
"""期货市场日报 → 单文件 HTML。

主力 / 次主力各一张表（只列当日持仓 > 阈值的），外加股指期货基差三张图。
不引任何 CDN，数据内联，断网也能打开。
"""
import sys
import warnings

warnings.filterwarnings("ignore")
# Jupyter 的 stdout 是 ipykernel 的 OutStream，没有 reconfigure，直接调会 AttributeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

import calendar
import datetime as dt
import glob
import html
import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

BASE   = Path(os.environ.get("FUTURES_REPORT_BASE", Path(__file__).resolve().parents[1])).resolve()
PARSED = BASE / "parsed"
DOM    = BASE / "dominant"
OUTDIR = BASE / "报告"

EX_CN = {"SHFE": "上期所", "INE": "能源中心", "CZCE": "郑商所",
         "DCE": "大商所", "CFFEX": "中金所", "GFEX": "广期所"}
# 股指期货 → 标的指数
IDX_MAP = {"if": "000300", "ic": "000905", "im": "000852", "ih": "000016"}
IDX_ORDER = ["if", "ic", "im", "ih"]
QUALITY_FIELDS = ("settle", "close", "open_interest", "volume")
FUTURES_ROW_RATIO = 0.95

RED, GREEN, GREY = "#c0392b", "#1a8a4a", "#8a8f98"


# ------------------------------------------------------------------ 数据加载
def load_all():
    fut = pd.concat([pd.read_parquet(f) for f in
                     sorted(glob.glob(str(PARSED / "futures" / "futures_*.parquet")))[-3:]],
                    ignore_index=True)
    fut["trade_date"] = pd.to_datetime(fut["trade_date"])
    main = pd.read_parquet(DOM / "main.parquet")
    sub  = pd.read_parquet(DOM / "sub.parquet")
    idx  = pd.read_parquet(PARSED / "index" / "index_daily.parquet")
    names = json.loads((PARSED / "product_name.json").read_text(encoding="utf-8"))
    return fut, main, sub, idx, names


def as_date(x):
    """接受 None / 20260819 / "20260819" / "2026-08-19" / date，统一成 Timestamp。"""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        x = "%d" % int(x)
    return pd.Timestamp(str(x))


def exchange_quality(df, expected, min_rows=5, row_ratio=0.8, lookback=20,
                     min_coverage=0.9):
    """按交易所评估单日完整性；行数门槛由 ``row_ratio`` 控制。

    固定 ``min_rows=5`` 只能挡空文件，挡不住 250 行被截成 5 行的响应。
    滚动门槛既能适应品种逐年增加，也不会让一个异常小样本冒充完整交易日。
    """
    expected = list(expected)
    missing = [c for c in QUALITY_FIELDS if c not in df.columns]
    if missing:
        raise ValueError("行情 schema 缺少完整性字段：%s" % ", ".join(missing))
    d = df[df["exchange"].isin(expected)].copy()
    if not len(d):
        return pd.DataFrame(columns=["trade_date", "exchange", "rows", "quality_ok"])
    fields = list(QUALITY_FIELDS)
    grouped = d.groupby(["trade_date", "exchange"], sort=True, observed=True)
    rows = grouped.size().rename("rows")
    coverage = grouped[fields].count().div(rows, axis=0)
    coverage.columns = [c + "_coverage" for c in coverage.columns]
    per = (pd.concat([rows, coverage], axis=1).reset_index()
             .sort_values(["exchange", "trade_date"]).reset_index(drop=True))
    per["reference_rows"] = per.groupby("exchange")["rows"].transform(
        lambda s: s.shift(1).rolling(lookback, min_periods=1).median())
    floor = per["reference_rows"].fillna(float(min_rows)) * float(row_ratio)
    per["required_rows"] = np.ceil(np.maximum(float(min_rows), floor)).astype(int)
    ok = per["rows"].ge(per["required_rows"])
    for c in fields:
        ok &= per[c + "_coverage"].ge(min_coverage)
    per["quality_ok"] = ok
    return per


def complete_exchange_dates(df, expected, min_rows=5, row_ratio=0.8, lookback=20,
                            min_coverage=0.9):
    per = exchange_quality(df, expected, min_rows, row_ratio, lookback, min_coverage)
    if not len(per):
        return pd.DatetimeIndex([])
    expected = set(expected)
    good = (per[per["quality_ok"]].groupby("trade_date")["exchange"]
            .agg(lambda x: expected.issubset(set(x))))
    return pd.DatetimeIndex(good[good].index)


def complete_dates(fut, min_rows=5, min_settled=0.9):
    """返回六所均达到动态行数门槛且关键字段覆盖完整的交易日。"""
    return complete_exchange_dates(fut, EX_CN, min_rows=min_rows,
                                   row_ratio=FUTURES_ROW_RATIO,
                                   min_coverage=min_settled)


def pick_date(fut, want=None):
    """取不晚于目标日的最后一个六所完整结算日。"""
    want = as_date(want)
    ok = complete_dates(fut)
    if want is not None:
        eligible = ok[ok <= want]
        if want in ok:
            return want
        print("  %s 数据不完整或非交易日，改用此前最后一个完整交易日" % want.date())
        ok = eligible
    if not len(ok):
        raise SystemExit("找不到完整的交易日")
    return ok.max()


# ------------------------------------------------------------ 口径 / 收益率
def to_single_side(df):
    """双边口径的成交量和持仓量折半，统一成单边。

    DCE 至今双边，郑商所 2020-01-01 之前双边。跨所放在一张表里比大小，
    不折半的话大商所的持仓凭空大一倍。

    **成交额跟成交量同口径**，所以也要折半。这一点是实测出来的：
    用 amount/(volume*settle) 反推合约乘数，27 个品种全部精确等于已知乘数
    （豆粕 10、铜 5、黄金 1000、沪深300 300……），说明两列是同一个口径。
    """
    d = df.copy()
    k = np.where(d["double_side"].fillna(False), 2.0, 1.0)
    for c in ("volume", "open_interest", "amount"):
        d[c] = d[c] / k
    return d


def adjusted_returns(tags, fut, windows=(1, 5, 20), since=None):
    """主力连续的复权收益率。

    since: 只算这个日期之后的序列。复权指数是连乘出来的，但 ret / ytd 都是
    两点之比，起点整体缩放不影响结果 —— 只要切点比「上一年最后一个交易日」
    和「往回 20 个交易日」都更早就行。

    换月当天不能拿新旧两个合约的收盘价相减 —— 那是两个东西的价差。
    正确做法是取**新合约自己**昨天的收盘价算当日涨跌，再把日收益连乘成复权序列，
    5 日 / 20 日收益从这条序列上取。这样换月的跳空自然被消掉。
    """
    if since is not None:
        since = pd.Timestamp(since)
        tags = tags[tags["trade_date"] >= since]
        fut = fut[fut["trade_date"] >= since]

    close = (fut[["trade_date", "contract", "close"]]
             .assign(close=lambda d: d["close"].where(d["close"] > 0))
             .drop_duplicates(["trade_date", "contract"])
             .rename(columns={"trade_date": "_pd", "close": "_prev"}))

    # 「当日合约在上一交易日的收盘价」用一次 merge 拿到，别在 Python 里逐行 .get()
    # —— 那是 20 万次 MultiIndex 查找，单这一行就 8.8s。
    t = tags.sort_values(["product", "trade_date"]).reset_index(drop=True)
    t["_pd"] = t.groupby("product", sort=False)["trade_date"].shift(1)
    t = t.merge(close, on=["_pd", "contract"], how="left")

    out = []
    for prod, g in t.groupby("product", sort=False):
        g = g.reset_index(drop=True)
        dates = list(g["trade_date"])
        cur   = g["close"].where(g["close"] > 0).astype(float).values

        prev = g["_prev"].astype(float).values.copy()
        prev[0] = np.nan                        # 第一天没有上一交易日
        r = cur / prev - 1
        idxs = np.concatenate([[1.0], np.nancumprod(1 + np.nan_to_num(r[1:]))])

        o = pd.DataFrame({"trade_date": dates, "product": prod})
        for w in windows:
            o["ret%d" % w] = pd.Series(idxs).pct_change(w).values

        # 年初至今：基准取**上一年最后一个交易日**的复权点位，
        # 不能取当年第一天 —— 那样 1 月 2 日的涨跌会被吞掉。
        # 当年才上市的品种没有上一年，就从它自己的第一个点算起。
        yrs = pd.Series(dates).dt.year.values
        starts = [0] + [i for i in range(1, len(yrs)) if yrs[i] != yrs[i - 1]]
        base = np.empty(len(o))
        for n, st in enumerate(starts):
            end = starts[n + 1] if n + 1 < len(starts) else len(o)
            base[st:end] = idxs[st - 1] if st > 0 else idxs[st]
        o["ytd"] = idxs / base - 1
        out.append(o)
    return pd.concat(out, ignore_index=True)


def contract_stats(fut1, date, lookback=180):
    """合约级的持仓变化和 5 日均量。

    必须按**合约自己**算，不能按品种的主力序列算 —— 换月那天主力序列会把两个
    不同合约的量拼在一起，出来的均量没有意义（实测次主力换月后出现
    「成交 3,304、5日均量 110,983」这种荒唐对比）。

    只有目标日那一行会被用到，所以先截掉 date 之前 lookback 天以外的数据再滚动。
    5 日窗口离 180 天远得很，含春节长假也够。
    """
    lo = pd.Timestamp(date) - pd.Timedelta(days=lookback)
    f = fut1[(fut1["trade_date"] >= lo) & (fut1["trade_date"] <= pd.Timestamp(date))]
    f = f.sort_values(["contract", "trade_date"])
    g = f.groupby("contract")
    return pd.DataFrame({
        "trade_date": f["trade_date"].values,
        "contract": f["contract"].values,
        "oi_d1": g["open_interest"].diff().values,
        "oi_d5": g["open_interest"].diff(5).values,
        "vol_ma5": g["volume"].transform(lambda x: x.rolling(5, min_periods=1).mean()).values,
    })


def build_table(tags, fut, date, min_oi=10000, only=None, windows=(1, 5, 20),
                fut1=None, stats=None):
    """only 给一组品种时，就不按 min_oi 过滤了，直接取这些品种 —— 次主力表用它
    跟主力表保持同一批品种，免得两张表对不上。

    fut1 / stats: 主力表和次主力表算出来的是同一份，由 prepare() 传进来复用。
    """
    tags = to_single_side(tags)
    fut1 = to_single_side(fut) if fut1 is None else fut1

    # ytd 的基准在上一年最后一个交易日，ret20 往回 20 个交易日 ——
    # 从上一年 10 月 1 日起算，两者都有充足余量。
    since = pd.Timestamp(year=pd.Timestamp(date).year - 1, month=10, day=1)
    rets = adjusted_returns(tags, fut1, windows, since=since)
    tags = tags.merge(rets, on=["trade_date", "product"], how="left")

    stats = contract_stats(fut1, date) if stats is None else stats
    tags = tags.merge(stats, on=["trade_date", "contract"], how="left")

    d = tags[tags["trade_date"] == date].copy()
    d = d[d["product"].isin(only)] if only is not None else d[d["open_interest"] > min_oi]
    return (d.sort_values("ret1", ascending=False, na_position="last")
             .reset_index(drop=True))


# ---------------------------------------------------------------- 股指基差
def cffex_expiry(contract):
    """中金所股指期货：交割月第三个周五。"""
    m = re.search(r"(\d{4})\s*$", contract)
    y, mo = 2000 + int(m.group(1)[:2]), int(m.group(1)[2:])
    fri = [x for x in calendar.Calendar().itermonthdates(y, mo)
           if x.month == mo and x.weekday() == 4]
    return pd.Timestamp(fri[2])


def basis_frame(fut, idx, date, min_days=5):
    spot = (idx[idx["trade_date"] == date].set_index("index_code")["close"])
    f = fut[(fut["trade_date"] == date) & (fut["product"].isin(IDX_MAP))].copy()
    f = f[f["close"] > 0]
    if not len(f) or not len(spot):
        return pd.DataFrame()
    f["spot"] = f["product"].map(IDX_MAP).map(spot)
    f["expiry"] = f["contract"].map(cffex_expiry)
    f["days"] = (f["expiry"] - date).dt.days
    prev = (fut[fut["trade_date"] < date].sort_values("trade_date")
            .groupby("contract")["close"].last())
    f["fchg"] = f["close"] / f["contract"].map(prev).where(lambda x: x > 0) - 1
    f["basis"] = f["close"] - f["spot"]
    f["ann"] = f["basis"] / f["spot"] * 365 / f["days"].clip(lower=1) * 100
    return f[f["days"] >= min_days].sort_values(["product", "days"])


def fmt_pct(v, tint=0.0):
    """tint 参数留着但不再用 —— 之前按 min/max 缩放的底色在邮件客户端里辨识度很差，
    现在统一只用红涨绿跌的文字颜色。"""
    if v is None or v != v:
        return '<td class="num dim">—</td>'
    cls = "up" if v > 0 else ("down" if v < 0 else "flat")
    return '<td class="num %s" data-v="%.6f">%+.2f%%</td>' % (cls, v, v * 100)


def fmt_int(v, signed=False):
    if v is None or v != v:
        return '<td class="num dim">—</td>'
    cls = ""
    if signed:
        cls = "up" if v > 0 else ("down" if v < 0 else "flat")
    s = format(v, "+,.0f") if signed else format(v, ",.0f")
    return '<td class="num %s" data-v="%.1f">%s</td>' % (cls, v, s)


def fmt_wan(v):
    """成交量 / 持仓统一用万手，保留一位小数 —— 原值七八位数太占宽度。"""
    if v is None or v != v:
        return '<td class="num dim">—</td>'
    return ('<td class="num" data-v="%.1f">%s<em>万</em></td>'
            % (v, format(v / 1e4, ",.1f")))


def fmt_price(v):
    """小数位按数值本身定：国债期货是 109.565，螺纹是 3017，别统一成两位。"""
    if v is None or v != v or v == 0:
        return '<td class="num dim">—</td>'
    s = format(round(v, 3), ",.3f").rstrip("0").rstrip(".")
    return '<td class="num" data-v="%.4f">%s</td>' % (v, s)


def basis_table_html(bf, idx, date, names, tid="t3"):
    """股指期货基差表：四个品种的全部在挂合约，按品种 + 到期先后排。"""
    if not len(bf):
        return "<p class='empty'>当日无股指期货数据</p>"
    idx_d = idx[idx["trade_date"] == date].set_index("index_code")
    heads = [("合约", "t"), ("期货收盘", "n"), ("指数点位", "n"), ("期货涨跌", "n"),
             ("指数涨跌", "n"), ("基差率", "n"), ("年化基差率", "n"),
             ("剩余天数", "n"), ("持仓", "n")]
    h = ['<div class="tw"><table id="%s"><thead><tr>' % tid]
    for i, (t, k) in enumerate(heads):
        h.append('<th class="%s" onclick="srt(&#39;%s&#39;,%d)">%s<i></i></th>' % (k, tid, i, t))
    h.append("</tr></thead><tbody>")

    order = {p: i for i, p in enumerate(IDX_ORDER)}
    bf = bf.assign(_o=bf["product"].map(order)).sort_values(["_o", "days"])
    for _, r in bf.iterrows():
        code = IDX_MAP[r["product"]]
        chg = float(idx_d.loc[code, "pct_chg"]) / 100 if code in idx_d.index else float("nan")
        h.append("<tr>")
        h.append('<td class="prod code">%s</td>' % html.escape(str(r["contract"])))
        h.append(fmt_price(r["close"]))
        h.append(fmt_price(r["spot"]))
        h.append(fmt_pct(r.get("fchg")))
        h.append(fmt_pct(chg))
        h.append(fmt_pct(r["basis"] / r["spot"]))
        a = r["ann"]
        h.append('<td class="num %s" data-v="%.4f">%+.2f%%</td>'
                 % ("up" if a > 0 else "down", a, a))
        h.append(fmt_int(r["days"]))
        h.append(fmt_wan(r["open_interest"]))
        h.append("</tr>")
    h.append("</tbody></table></div>")
    return "".join(h)


def table_html(d, names, tid):
    heads = [("品种", "t"), ("合约", "t"), ("收盘", "n"), ("1日", "n"), ("年初至今", "n"),
             ("成交量", "n"), ("5日均量", "n"), ("持仓", "n")]
    h = ['<div class="tw"><table id="%s"><thead><tr>' % tid]
    for i, (t, k) in enumerate(heads):
        h.append('<th class="%s" onclick="srt(\'%s\',%d)">%s<i></i></th>' % (k, tid, i, t))
    h.append("</tr></thead><tbody>")
    for _, r in d.iterrows():
        nm = names.get(r["product"], r["product"].upper())
        h.append("<tr>")
        h.append('<td class="prod">%s</td>' % html.escape(nm))
        h.append('<td class="code">%s</td>' % html.escape(str(r["contract"])))
        h.append(fmt_price(r["close"]))
        h.append(fmt_pct(r.get("ret1")))
        h.append(fmt_pct(r.get("ytd")))
        h.append(fmt_wan(r["volume"]))
        h.append(fmt_wan(r["vol_ma5"]))
        h.append(fmt_wan(r["open_interest"]))
        h.append("</tr>")
    h.append("</tbody></table></div>")
    return "".join(h)


CSS = """
*{box-sizing:border-box}
:root{
 --ink:#171a1f; --mut:#6b7280; --line:#e8eaee; --bg:#f4f6f9; --card:#fff;
 --up:#c8372d; --dn:#12855a; --accent:#2f5fd0; --amber:#b4761a;
}
body{margin:0;padding:0 0 56px;background:var(--bg);color:var(--ink);
 font:14px/1.5 "PingFang SC","Microsoft YaHei","Hiragino Sans GB",system-ui,sans-serif;
 -webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:0 18px}

/* 页头 */
.hero{background:linear-gradient(120deg,#1b2436 0%,#28405f 55%,#2f5fd0 140%);
 color:#fff;padding:26px 0 22px;margin-bottom:20px}
.hero .wrap{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap}
.hero h1{font-size:25px;margin:0;letter-spacing:1px;font-weight:600}
.hero .d{font-size:13px;opacity:.78;margin-top:5px;line-height:1.7}
.hero .big{font-size:15px;opacity:.95;font-weight:600;letter-spacing:.5px}

/* 概览卡 */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(178px,1fr));gap:11px;margin:0 0 6px}
.card{background:var(--card);border:1px solid var(--line);border-radius:9px;
 padding:11px 13px 12px;position:relative;overflow:hidden}
.card:before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--accent)}
.card.c1:before{background:var(--up)} .card.c2:before{background:var(--accent)}
.card.c3:before{background:var(--amber)} .card.c4:before{background:var(--dn)}
.card .k{font-size:11.5px;color:var(--mut);letter-spacing:.3px}
.card .v{font-size:20px;font-weight:650;margin-top:2px;font-variant-numeric:tabular-nums}
.card .v small{font-size:12px;font-weight:500;color:var(--mut);margin-left:2px}

/* 标题 */
h2{font-size:17px;margin:30px 0 3px;display:flex;align-items:center;gap:8px;font-weight:600}
h2:before{content:"";width:4px;height:15px;border-radius:2px;background:var(--accent)}
h2.g:before{background:var(--amber)}
.note{color:var(--mut);font-size:12px;margin:5px 0 9px;line-height:1.65}

/* 表 */
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:9px;background:var(--card);
 box-shadow:0 1px 2px rgba(16,24,40,.04)}
table{width:100%;border-collapse:separate;border-spacing:0;font-variant-numeric:tabular-nums}
th{position:sticky;top:0;z-index:2;background:#eef1f5;font-size:11.5px;font-weight:600;
 color:#3d434d;padding:7px 9px;white-space:nowrap;cursor:pointer;user-select:none;
 border-bottom:1px solid #dfe3e9;letter-spacing:.2px}
th.n{text-align:right}th.t{text-align:left}
th:hover{background:#e4e9f0;color:var(--accent)}
th i{display:inline-block;width:0;height:0;margin-left:3px;vertical-align:middle;opacity:.25;
 border-left:3.5px solid transparent;border-right:3.5px solid transparent;border-bottom:4.5px solid #333}
th.desc i{border-bottom:none;border-top:4.5px solid var(--accent);opacity:1}
th.asc i{border-bottom-color:var(--accent);opacity:1}
td{padding:4px 9px;border-bottom:1px solid #f2f3f5;font-size:13px;white-space:nowrap;line-height:1.45}
tbody tr:nth-child(even) td{background-color:#fbfcfd}
tbody tr:hover td{background-color:#f0f4fb}
tbody tr:last-child td{border-bottom:none}
.num{text-align:right}
.prod{font-weight:600;white-space:nowrap}
.code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:#5b626d}
td em{font-style:normal;font-size:11px;color:var(--mut);margin-left:1px}
.up{color:var(--up)}.down{color:var(--dn)}.flat{color:var(--mut)}.dim{color:#c9cdd4}
.empty{color:#9ca3af;font-size:13px}
footer{margin-top:34px;padding-top:13px;border-top:1px solid var(--line);
 color:#9aa0a8;font-size:11.5px;line-height:1.8}
@media(max-width:720px){
 .wrap{padding:0 10px} .hero h1{font-size:21px}
 td,th{padding:4px 6px;font-size:12px}
}
"""

JS = """
function srt(id,i){
 var t=document.getElementById(id),b=t.tBodies[0],
     ths=t.tHead.rows[0].cells,th=ths[i],
     desc=!th.classList.contains('desc');
 for(var k=0;k<ths.length;k++){ths[k].classList.remove('asc','desc');}
 th.classList.add(desc?'desc':'asc');
 var rows=[].slice.call(b.rows);
 rows.sort(function(x,y){
   var a=x.cells[i],c=y.cells[i],
       av=a.dataset.v,cv=c.dataset.v;
   if(av===undefined&&cv===undefined)
     return a.textContent.localeCompare(c.textContent,'zh')*(desc?-1:1);
   if(av===undefined)return 1; if(cv===undefined)return -1;
   return (parseFloat(cv)-parseFloat(av))*(desc?1:-1);
 });
 rows.forEach(function(r){b.appendChild(r);});
}
"""


def prepare(date=None, min_oi=10000, loaded=None):
    """两种版式共用的那一份计算。完整版和邮件版都要它，算一次就够。"""
    fut, main, sub, idx, names = loaded or load_all()
    D = pick_date(fut, date)
    print("报告日期", D.date())

    fut1 = to_single_side(fut)              # 两张表共用，别算两遍
    stats = contract_stats(fut1, D)
    mt = build_table(main, fut, D, min_oi, fut1=fut1, stats=stats)
    st = build_table(sub,  fut, D, only=set(mt["product"]), fut1=fut1, stats=stats)
    miss = sorted(set(mt["product"]) - set(st["product"]))
    print("主力 %d 个（持仓 > %s，单边口径），次主力 %d 个%s"
          % (len(mt), format(min_oi, ","), len(st),
             ("，缺 " + " ".join(miss)) if miss else ""))
    return {"fut": fut, "idx": idx, "names": names, "D": D, "mt": mt, "st": st,
            "bf": basis_frame(fut, idx, D), "min_oi": min_oi}


def validate_report_ready(prep):
    """正式发信前的最后一道门：主/次主力和四个股指基差都必须齐全。"""
    D, idx, mt, st, bf = (prep[k] for k in ("D", "idx", "mt", "st", "bf"))
    mt_products = set(mt["product"].astype(str)) if "product" in mt else set()
    st_products = set(st["product"].astype(str)) if "product" in st else set()
    if not mt_products or st_products != mt_products:
        raise RuntimeError("主力/次主力表不完整：%d / %d" % (len(mt), len(st)))
    for label, table in (("主力", mt), ("次主力", st)):
        bad = [c for c in ("close", "volume", "open_interest")
               if c not in table or table[c].isna().any()]
        if bad:
            raise RuntimeError("%s表关键字段不完整：%s" % (label, ", ".join(bad)))
    idx_day = idx[idx["trade_date"].eq(D)].copy()
    usable = idx_day[idx_day["close"].notna() & idx_day["pct_chg"].notna()]
    missing_index = sorted(set(IDX_MAP.values()) - set(usable["index_code"].astype(str)))
    if missing_index:
        raise RuntimeError("报告日缺少股指现货数据：%s" % ", ".join(missing_index))
    basis_products = set(bf["product"].astype(str)) if "product" in bf else set()
    missing_basis = sorted(set(IDX_MAP) - basis_products)
    if missing_basis:
        raise RuntimeError("报告日缺少股指期货基差：%s" % ", ".join(x.upper() for x in missing_basis))
    return True


def build_report(date=None, min_oi=10000, out=None, prep=None):
    prep = prep or prepare(date, min_oi)
    fut, idx, names = prep["fut"], prep["idx"], prep["names"]
    D, mt, st, min_oi = prep["D"], prep["mt"], prep["st"], prep["min_oi"]

    # 概览
    day = to_single_side(fut[fut["trade_date"] == D])
    up = int((mt["ret1"] > 0).sum()); dn = int((mt["ret1"] < 0).sum())
    cards = [("上涨 / 下跌品种", '<span class="up">%d</span> / <span class="down">%d</span>' % (up, dn)),
             ("全市场成交量", "%.0f<small>万手</small>" % (day["volume"].sum() / 1e4)),
             ("全市场持仓量", "%.0f<small>万手</small>" % (day["open_interest"].sum() / 1e4)),
             ("全市场成交额", "%.0f<small>亿元</small>" % (day["amount"].sum() / 1e8))]

    # 股指基差
    bf = prep["bf"]
    bsum = ""
    if len(bf):
        near = bf.sort_values(["product", "days"]).groupby("product").first()
        bsum = "；".join("%s %+.1f%%" % (p.upper(), near.loc[p, "ann"])
                         for p in IDX_ORDER if p in near.index)

    h = ['<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
         "<title>期货市场日报 %s</title>" % D.strftime("%Y-%m-%d"),
         "<style>%s</style>" % CSS,
         '<div class="hero"><div class="wrap"><div>',
         "<h1>期货市场日报</h1>",
         '<div class="d">六家交易所 &nbsp;·&nbsp; 成交量与持仓量为单边口径 &nbsp;·&nbsp; '
         '涨跌为主力连续复权收益率</div></div>',
         '<div class="big">%s</div>' % D.strftime("%Y年%m月%d日"),
         '</div></div><div class="wrap">',
         '<div class="cards">']
    for n, (k, v) in enumerate(cards, 1):
        h.append('<div class="card c%d"><div class="k">%s</div><div class="v">%s</div></div>'
                 % (n, k, v))
    h.append("</div>")

    h.append('<h2 class="g">股指期货基差</h2>')
    h.append('<div class="note">负值即贴水，做多股指期货相当于每年多赚这个百分比。'
             '剩余不足 5 天的合约不列。</div>')
    h.append(basis_table_html(bf, idx, D, names))

    h.append("<h2>主力合约</h2>")
    h.append('<div class="note">持仓量 &gt; %s 手，共 %d 个品种，按当日涨跌从高到低排。'
             '点表头可换其它排序。</div>'
             % (format(min_oi, ","), len(mt)))
    h.append(table_html(mt, names, "t1"))

    h.append("<h2>次主力合约</h2>")
    h.append('<div class="note">品种跟上表一致，同样按当日涨跌从高到低排，共 %d 个。</div>'
             % len(st))
    h.append(table_html(st, names, "t2"))

    h.append("<footer>数据来源：上期所 / 能源中心 / 郑商所 / 大商所 / 中金所 / 广期所官方历史行情，"
             "指数优先采用上交所官方行情、腾讯备用。主力合约的换月规则：某合约收盘持仓量超过当前主力 1.1 倍时，"
             "下一交易日起切换，且只能切到交割月不早于当前主力的合约。"
             "本报告仅供参考，不构成投资建议。<br>生成时间 %s</footer>"
             % dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    h.append("</div><script>%s</script>" % JS)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    out = Path(out) if out else OUTDIR / ("report_%s.html" % D.strftime("%Y%m%d"))
    out.write_text("\n".join(h), encoding="utf-8")
    print("-> %s  (%.0f KB)" % (out, out.stat().st_size / 1024))
    return out


if __name__ == "__main__":
    build_report(*(sys.argv[1:2] or []))
