"""QUANT FLOOR Lv.1 BTC/ETH 실노출(배율x비중) 스윕. bt_eth.py 의 run()/klines()/funding() 재사용."""
import sys, types
import os as _os; _os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # 어디서 실행해도 이 폴더 기준
src = open(sys.argv[1] if len(sys.argv) > 1 else "backtest_lv1_eth.py", encoding="utf-8").read().split("df = klines()")[0]
OUTDIR = sys.argv[2] if len(sys.argv) > 2 else "결과"
import pandas as pd
EXPOS = [0.5, 1, 1.5, 2, 2.5, 3, 4, 5]
STARTS = ["2020-01-01", "2021-01-01", "2022-01-01", "2023-01-01", "2024-01-01"]
results = {}
for sym in ["BTCUSDT", "ETHUSDT"]:
    g = {"__name__": "bt", "sys": types.SimpleNamespace(argv=["x", "/dev/null"])}
    exec(src.replace('SYM = "ETHUSDT"', f'SYM = "{sym}"').replace("OUT = sys.argv[1]", "OUT=None"), g)
    df = g["klines"](); mk = g["klines"]("markPriceKlines").set_index("t")[["h", "l"]]
    df[["h", "l"]] = mk.reindex(df.t).values
    fr = g["funding"]()
    rows = []
    for e in EXPOS:
        per = []
        for st in STARTS:
            g["START"] = st
            s, tr, liq = g["run"](df, fr, e * 10, lev=10)
            per.append(g["stats"](s, tr, liq))
        full = per[0]
        rows.append(dict(expo=e, final=full["final"], cagr=full["cagr"], mdd=full["mdd"], liq=full["liq"],
                         worst_mdd=min(p["mdd"] for p in per), liq_any=sum(p["liq"] != "-" for p in per),
                         min_cagr=min(p["cagr"] for p in per), n=full["n"], win=full["win"]))
        g["START"] = STARTS[0]
    g["START"] = STARTS[0]
    curves = {e: g["run"](df, fr, e * 10, lev=10)[0] for e in [1, 1.5, 2, 3]}
    bh = df.set_index("date").c; bh = bh[bh.index >= pd.Timestamp(STARTS[0], tz="UTC")]
    results[sym] = (pd.DataFrame(rows), curves, bh / bh.iloc[0], df.date.iloc[-1])
    t = pd.DataFrame(rows)
    print(f"\n=== {sym} (수수료·슬리피지·펀딩 반영, 마크가격 청산) 기간 2020-01 ~ {df.date.iloc[-1]:%Y-%m-%d} / 현물보유 {bh.iloc[-1]/bh.iloc[0]:.1f}배")
    for r in rows:
        print(f"실노출 {r['expo']:>3}배: 최종 {r['final']:>8.1f}배  CAGR {r['cagr']:+7.1%}  MDD {r['mdd']:7.1%} | 시작연도 5개 중 최악MDD {r['worst_mdd']:7.1%}  최저CAGR {r['min_cagr']:+7.1%}  청산 {r['liq_any']}/5  | 매매 {r['n']} 승률 {r['win']:.0%}")

import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import FuncFormatter
font_manager.fontManager.addfont("/System/Library/Fonts/AppleSDGothicNeo.ttc")
plt.rcParams["font.family"] = "Apple SD Gothic Neo"; plt.rcParams["axes.unicode_minus"] = False
col = {1: "#7a7a7a", 1.5: "#2e8b57", 2: "#d9822b", 3: "#c0392b"}
fig, axes = plt.subplots(2, 2, figsize=(15, 9), gridspec_kw={"height_ratios": [3, 1.4]})
for k, sym in enumerate(results):
    t, curves, bh, end = results[sym]
    ax, ax2 = axes[0][k], axes[1][k]
    for e, s in curves.items():
        v = s / s.iloc[0]; v = v[v > 0]
        r = t[t.expo == e].iloc[0]
        ax.plot(v.index, v, color=col[e], lw=1.6 if e in (1.5, 2) else 1.1,
                label=f"실노출 {e:g}배 (10배·비중 {e*10:g}%) → {r['final']:.1f}배, MDD {r['mdd']:.0%}")
        dd = s / s.cummax() - 1
        if e in (1.5, 3): ax2.fill_between(dd.index, dd * 100, 0, color=col[e], alpha=.35, label=f"실노출 {e:g}배 낙폭")
    ax.plot(bh.index, bh, color="#222", ls="--", lw=1, label=f"{sym[:3]} 보유 → {bh.iloc[-1]:.1f}배")
    ax.set_yscale("log"); ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:g}배"))
    ax.set_title(f"{sym[:3]}  ·  Lv.1 (종가 vs 50일 평균)  ·  2020-01 ~ {end:%Y-%m}", fontsize=13)
    ax.legend(fontsize=8.5, loc="upper left"); ax.grid(alpha=.3, which="both")
    ax2.set_ylabel("낙폭 (%)"); ax2.legend(fontsize=8.5, loc="lower left"); ax2.grid(alpha=.3)
fig.suptitle("QUANT FLOOR Lv.1  BTC vs ETH  실노출별 백테스트  (수수료 0.05%+슬리피지 0.02%, 실제 펀딩비, 마크가격 청산, 복리)", fontsize=12)
plt.tight_layout(); out = OUTDIR + "/Lv1_BTC_ETH_실노출별.png"; plt.savefig(out, dpi=120); print("\nsaved", out)
