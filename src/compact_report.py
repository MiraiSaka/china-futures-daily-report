# -*- coding: utf-8 -*-
"""适合移动端浏览的精简版 HTML 日报。

跟 report.py 的完整版是两条渲染路径，不是把完整版正则改写过来 ——
之前那样做又脆又大（242 KB）。这里直接从同一份 DataFrame 渲染，
样式全部行内、能用 HTML 属性表达的就不用 CSS，目标压到 100 KB 以内
输出体积默认控制在 100 KB 左右，便于浏览和传输。
"""
import datetime as dt
import html
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
# Jupyter 的 stdout 是 ipykernel 的 OutStream，没有 reconfigure，直接调会 AttributeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

import report as R

UP, DN, MUT, LINE = "#c8372d", "#12855a", "#6b7280", "#e8eaee"
FONT = ("font-family:'PingFang SC','Microsoft YaHei',Arial,sans-serif")
TBL = ('cellpadding="5" cellspacing="0" border="0" width="100%%" '
       'style="border-collapse:collapse;font-size:13px;background:#fff;'
       'border:1px solid %s"' % LINE)
THS = "background:#eef1f5;font-size:11.5px;color:#3d434d;border-bottom:1px solid #dfe3e9"


def _pct(v):
    """涨跌单元格：只有红绿文字，没有底色。"""
    if v is None or v != v:
        return '<td align="right" style="color:#c9cdd4">—</td>'
    c = UP if v > 0 else (DN if v < 0 else MUT)
    return '<td align="right" style="color:%s">%+.2f%%</td>' % (c, v * 100)


def _price(v):
    if v is None or v != v or v == 0:
        return '<td align="right" style="color:#c9cdd4">—</td>'
    return '<td align="right">%s</td>' % format(round(v, 3), ",.3f").rstrip("0").rstrip(".")


def _wan(v):
    if v is None or v != v:
        return '<td align="right" style="color:#c9cdd4">—</td>'
    return '<td align="right">%s万</td>' % format(v / 1e4, ",.1f")


def _head(cols):
    return ("<tr>" + "".join(
        '<th align="%s" style="%s">%s</th>' % ("right" if a else "left", THS, t)
        for t, a in cols) + "</tr>")


def _rows(n):
    """偶数行加个浅底，用 bgcolor 属性比写 style 省一半字符。"""
    return ' bgcolor="#fbfcfd"' if n % 2 else ""


def main_table(d, names):
    h = ["<table %s>" % TBL,
         _head([("品种", 0), ("合约", 0), ("收盘", 1), ("1日", 1), ("年初至今", 1),
                ("成交量", 1), ("5日均量", 1), ("持仓", 1)])]
    for n, (_, r) in enumerate(d.iterrows()):
        h.append("<tr%s>" % _rows(n))
        h.append("<td><b>%s</b></td>" % html.escape(names.get(r["product"], r["product"].upper())))
        h.append('<td style="color:#5b626d;font-size:12px">%s</td>' % html.escape(str(r["contract"])))
        h.append(_price(r["close"]))
        h.append(_pct(r.get("ret1")))
        h.append(_pct(r.get("ytd")))
        h.append(_wan(r["volume"]))
        h.append(_wan(r["vol_ma5"]))
        h.append(_wan(r["open_interest"]))
        h.append("</tr>")
    h.append("</table>")
    return "".join(h)


def basis_table(bf, idx, date):
    if not len(bf):
        return '<div style="color:#9ca3af;font-size:13px">当日无股指期货数据</div>'
    idx_d = idx[idx["trade_date"] == date].set_index("index_code")
    order = {p: i for i, p in enumerate(R.IDX_ORDER)}
    bf = bf.assign(_o=bf["product"].map(order)).sort_values(["_o", "days"])
    h = ["<table %s>" % TBL,
         _head([("合约", 0), ("期货收盘", 1), ("指数点位", 1), ("期货涨跌", 1),
                ("指数涨跌", 1), ("基差率", 1), ("年化基差率", 1),
                ("剩余天数", 1), ("持仓", 1)])]
    for n, (_, r) in enumerate(bf.iterrows()):
        code = R.IDX_MAP[r["product"]]
        chg = float(idx_d.loc[code, "pct_chg"]) / 100 if code in idx_d.index else float("nan")
        a = r["ann"]
        h.append("<tr%s>" % _rows(n))
        h.append("<td><b>%s</b></td>" % html.escape(str(r["contract"])))
        h.append(_price(r["close"]))
        h.append(_price(r["spot"]))
        h.append(_pct(r.get("fchg")))
        h.append(_pct(chg))
        h.append(_pct(r["basis"] / r["spot"]))
        h.append('<td align="right" style="color:%s">%+.2f%%</td>'
                 % (UP if a > 0 else DN, a))
        h.append('<td align="right">%d</td>' % int(r["days"]))
        h.append(_wan(r["open_interest"]))
        h.append("</tr>")
    h.append("</table>")
    return "".join(h)


def build_compact_report(date=None, min_oi=10000, with_sub=True, cap_kb=100, out=None, prep=None):
    """cap_kb: 精简版体积上限。超限时先省略次主力表。

    prep: R.prepare() 的结果。发信时完整版和精简版共用同一份，省掉一遍重复计算。
    """
    prep = prep or R.prepare(date, min_oi)
    fut, idx, names = prep["fut"], prep["idx"], prep["names"]
    D, mt, st, min_oi = prep["D"], prep["mt"], prep["st"], prep["min_oi"]

    day = R.to_single_side(fut[fut["trade_date"] == D])
    up, dn = int((mt["ret1"] > 0).sum()), int((mt["ret1"] < 0).sum())
    cards = [("上涨 / 下跌品种",
              '<span style="color:%s">%d</span> / <span style="color:%s">%d</span>'
              % (UP, up, DN, dn), UP),
             ("全市场成交量", "%.0f<small style='color:%s'>万手</small>"
              % (day["volume"].sum() / 1e4, MUT), "#2f5fd0"),
             ("全市场持仓量", "%.0f<small style='color:%s'>万手</small>"
              % (day["open_interest"].sum() / 1e4, MUT), "#b4761a"),
             ("全市场成交额", "%.0f<small style='color:%s'>亿元</small>"
              % (day["amount"].sum() / 1e8, MUT), DN)]

    bf = prep["bf"]

    def h2(t, col="#2f5fd0"):
        return ('<h2 style="font-size:16px;margin:22px 0 4px;font-weight:600;'
                'border-left:4px solid %s;padding-left:8px">%s</h2>' % (col, t))

    note = ('<div style="color:%s;font-size:12px;margin:4px 0 8px">%%s</div>' % MUT)

    h = ['<div style="%s;color:#171a1f;background:#f4f6f9;padding:0 0 24px">' % FONT,
         '<div style="background:#1b2436;color:#fff;padding:20px 22px">',
         '<div style="font-size:22px;font-weight:600;letter-spacing:1px">期货市场日报</div>',
         '<div style="font-size:12.5px;opacity:.78;margin-top:5px">'
         '六家交易所 · 成交量与持仓量为单边口径 · 涨跌为主力连续复权收益率</div>',
         '<div style="font-size:14px;font-weight:600;margin-top:8px">%s</div></div>'
         % D.strftime("%Y年%m月%d日"),
         '<div style="padding:0 22px">',
         '<table cellpadding="0" cellspacing="8" border="0" width="100%" '
         'style="margin:12px 0 2px"><tr>']
    for k, v, col in cards:
        h.append('<td width="25%%" valign="top" style="background:#fff;border:1px solid %s;'
                 'border-left:3px solid %s;padding:10px 12px">'
                 '<div style="font-size:11.5px;color:%s">%s</div>'
                 '<div style="font-size:19px;font-weight:600;margin-top:2px">%s</div></td>'
                 % (LINE, col, MUT, k, v))
    h.append("</tr></table>")

    h.append(h2("股指期货基差", "#b4761a"))
    h.append(note % "负值即贴水，做多股指期货相当于每年多赚这个百分比。剩余不足 5 天的合约不列。")
    h.append(basis_table(bf, idx, D))

    h.append(h2("主力合约"))
    h.append(note % ("持仓量 &gt; %s 手，共 %d 个品种，按当日涨跌从高到低排。"
                     % (format(min_oi, ","), len(mt))))
    h.append(main_table(mt, names))
    head = "".join(h)

    tail_sub = (h2("次主力合约")
                + note % ("品种跟上表一致，同样按当日涨跌从高到低排，共 %d 个。" % len(st))
                + main_table(st, names))
    foot = ('<div style="margin-top:22px;padding-top:12px;border-top:1px solid %s;'
            'color:#9aa0a8;font-size:11.5px;line-height:1.8">'
            '完整版（可点表头排序）见附件。数据来源：上期所 / 能源中心 / 郑商所 / 大商所 / '
            '中金所 / 广期所官方历史行情，指数优先采用上交所官方行情、腾讯备用。'
            '主力换月：某合约收盘持仓量超过当前主力 1.1 倍时下一交易日起切换，'
            '且只能切到交割月不早于当前主力的合约。本报告仅供参考，不构成投资建议。<br>'
            '生成时间 %s</div></div></div>'
            % (LINE, dt.datetime.now().strftime("%Y-%m-%d %H:%M")))

    body = head + (tail_sub if with_sub else "") + foot
    kb = len(body.encode("utf-8")) / 1024
    if with_sub and kb > cap_kb:
        print("  含次主力 %.0f KB 超过 %d KB，砍掉次主力表" % (kb, cap_kb))
        body = head + foot
        kb = len(body.encode("utf-8")) / 1024

    R.OUTDIR.mkdir(parents=True, exist_ok=True)
    out = Path(out) if out else R.OUTDIR / ("compact_%s.html" % D.strftime("%Y%m%d"))
    out.write_text(body, encoding="utf-8")
    print("-> %s  %.1f KB%s" % (out, kb, "" if kb <= cap_kb else "  ⚠ 超出建议体积"))
    return out


if __name__ == "__main__":
    build_compact_report(*(sys.argv[1:2] or []))
