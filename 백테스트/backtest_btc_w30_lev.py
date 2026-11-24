"""BTC Lv.1 (종가 vs 50일선) · 비중 30% 고정 · 배율 1/2/3/5/10/15/20배 백테스트.
수수료 0.05% + 슬리피지 0.02%, 실제 펀딩비, 마크가격 기준 강제청산, 복리. 시작 자금 5,000 USDT.
실행: python3 backtest_btc_w30_lev.py  →  backtest_btc_w30.json / 결과/Lv1_BTC_비중30_배율별.png
결과 json 은 KBTC_desktop·KBTC_server 앱 폴더에도 자동 복사된다 (서버는 다시 배포해야 반영)
"""
import json, sys, types
import os as _os; _os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # 어디서 실행해도 이 폴더 기준
import pandas as pd
sys.argv = [sys.argv[0], "backtest_lv1_eth.py", "."]
src = open("backtest_lv1_vs_lv7.py", encoding="utf-8").read()
src = src[:src.index("data, out = {}, {}")]
g = {"__name__": "x", "__file__": __file__}; exec(src, g)
base = open("backtest_lv1_eth.py", encoding="utf-8").read().split("df = klines()")[0]
h = {"__name__": "bt", "sys": types.SimpleNamespace(argv=["x", "/dev/null"])}
exec(base.replace('SYM = "ETHUSDT"', 'SYM = "BTCUSDT"').replace("OUT = sys.argv[1]", "OUT=None"), h)
df = h["klines"](); mk = h["klines"]("markPriceKlines").set_index("t")[["h", "l"]]
df[["h", "l"]] = mk.reindex(df.t).values
fr = h["funding"]()
W, LEVS, CAP = 30, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20], 5000
rows, curves = [], {}
bh = df.set_index("date").c; bh = bh[bh.index >= g["START"]]; bh = bh / bh.iloc[0]
for lev in LEVS:
    s, tr, liq, flat = g["run"](df, fr, W / 100 * lev, None)
    r = g["st"](s, tr, liq, flat)
    yr = {}
    for y in sorted(set(s.index.year)):
        prev = s[s.index.year < y]; a0 = prev.iloc[-1] if len(prev) else s.iloc[0]
        yr[str(y)] = float(s[s.index.year == y].iloc[-1] / a0 - 1) if a0 > 0 else None
    worst_y = min((v for v in yr.values() if v is not None), default=None)
    rows.append(dict(lev=lev, expo=W / 100 * lev, final=float(r["final"]), usdt=float(r["final"] * CAP), cagr=float(r["cagr"]),
                     mdd=float(r["mdd"]), trades=r["n"], win=float(r["win"]), liq=r["liq"].strftime("%Y-%m-%d") if r["liq"] is not None else None,
                     years=yr, worst_year=worst_y, min_usdt=float(s.min() / s.iloc[0] * CAP),
                     peak_usdt=float(s.cummax()[(s / s.cummax() - 1).idxmin()] / s.iloc[0] * CAP)))
    curves[lev] = s
wk = lambda ser: [[str(i.date()), round(float(v), 4)] for i, v in (ser / ser.iloc[0]).resample("W").last().dropna().items()]
def verdict(m):  # 최대 낙폭(전체 계좌) 기준 판정
    return ("보수" if m > -0.3 else "안정" if m > -0.45 else "균형" if m > -0.6 else "공격" if m > -0.7
            else "공격 · 추천 상한" if m > -0.75 else "위험" if m > -0.97 else "매우 위험")
for r in rows:
    r["verdict"] = verdict(r["mdd"])
info_curves = {str(l): wk(c) for l, c in curves.items()}
info_curves["hold"] = wk(bh)
info = dict(curves=info_curves, symbol="BTCUSDT", weight=W, start=str(s.index[0].date()), end=str(s.index[-1].date()), capital=CAP,
            hold=float(bh.iloc[-1]), hold_mdd=float((bh / bh.cummax() - 1).min()), rows=rows)
for dst in ("backtest_btc_w30.json", "../KBTC_desktop/quant_floor/assets/backtest_btc_w30.json", "../KBTC_server/static/backtest_btc_w30.json"):
    if _os.path.isdir(_os.path.dirname(dst) or "."):
        json.dump(info, open(dst, "w", encoding="utf-8"), ensure_ascii=False)  # 앱 두 곳에도 바로 반영
for r in rows:
    print(f"{r['lev']:>2}배 (실노출 {r['expo']:.1f}배): {r['final']:9.1f}배  {CAP:,}→{r['usdt']:,.0f} USDT  CAGR {r['cagr']:+.1%}  MDD {r['mdd']:.1%}  최악연도 {r['worst_year']:+.0%}  청산 {r['liq']}")
print("보유", info["hold"], info["start"], info["end"])

import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import FuncFormatter
font_manager.fontManager.addfont("/System/Library/Fonts/AppleSDGothicNeo.ttc")
plt.rcParams.update({"font.family": "Apple SD Gothic Neo", "axes.unicode_minus": False, "figure.facecolor": "#0b0c0f",
                     "axes.facecolor": "#111317", "axes.edgecolor": "#33363d", "text.color": "#ede8df",
                     "axes.labelcolor": "#9ea2aa", "xtick.color": "#9ea2aa", "ytick.color": "#9ea2aa"})
cols = {1: "#9ea2aa", 2: "#88e6c4", 3: "#3ecf7a", 4: "#a3d977", 5: "#ffc56b", 6: "#ffb05c", 7: "#ffa14f", 8: "#ff9343", 9: "#ff8a3d", 10: "#ff7a45", 15: "#ff5f7e", 20: "#c0392b"}
fig, ax = plt.subplots(figsize=(12, 6.2))
for lev, s in curves.items():
    v = s / s.iloc[0]; v = v[v > 0]
    r = next(x for x in rows if x["lev"] == lev)
    lab = f"{lev}배 → {r['final']:,.1f}배 · MDD {r['mdd']:.0%}" + (f" · 청산 {r['liq']}" if r["liq"] else "")
    ax.plot(v.index, v, color=cols[lev], lw=2 if lev in (5, 10) else 1.3, label=lab)
    if r["liq"]:
        ax.plot(v.index[-1], v.iloc[-1], "x", ms=11, mew=2.5, color=cols[lev])
ax.plot(bh.index, bh, color="#ede8df", ls="--", lw=1, label=f"BTC 보유 → {info['hold']:.1f}배")
ax.set_yscale("log"); ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:g}배")); ax.set_ylim(0.05, None)
ax.grid(alpha=.18, which="both")
ax.set_title(f"KBTC Lv.1 · BTC · 비중 30% · 배율별  ({info['start']} ~ {info['end']}, 수수료·펀딩·청산 반영)", fontsize=13)
ax.legend(fontsize=9.5, loc="upper left", facecolor="#16181d", edgecolor="#33363d")
plt.tight_layout(); plt.savefig("결과/Lv1_BTC_비중30_배율별.png", dpi=130)
print("saved")
