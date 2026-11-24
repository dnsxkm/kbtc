"""Lv.1 vs Lv.7(국면 필터: |종가/20일전 종가 - 1| < 임계값이면 관망) 비교."""
import sys, types
import os as _os; _os.chdir(_os.path.dirname(_os.path.abspath(__file__)))  # 어디서 실행해도 이 폴더 기준
import pandas as pd
src = open(sys.argv[1] if len(sys.argv) > 1 else "backtest_lv1_eth.py", encoding="utf-8").read().split("df = klines()")[0]
OUTDIR = sys.argv[2] if len(sys.argv) > 2 else "결과"
FEE, SLIP, MMR = 0.0005, 0.0002, 0.005
START = pd.Timestamp("2020-01-01", tz="UTC")

def run(df, fr, expo, band=None):
    eq, q, side = 1.0, 0.0, 0
    curve, trades, liq, entry_eq, flat_days = [], [], None, None, 0
    c = df.c.values
    for i in range(len(df)):
        row = df.iloc[i]
        if i >= 1 and q:
            prev = c[i - 1]; worst = row.l if q > 0 else row.h
            if eq + q * (worst - prev) <= MMR * abs(q) * worst:
                eq, q, liq = 0.0, 0.0, row.date
            else:
                eq += q * (row.c - prev) - fr.get(row.date, 0.0) * q * row.c
        curve.append(eq)
        if eq <= 0:
            curve += [0.0] * (len(df) - i - 1); break
        if i < 59 or row.date < START - pd.Timedelta(days=1):
            continue
        sma = c[i - 49:i + 1].mean()
        target = 1 if c[i] > sma else -1 if c[i] < sma else side
        if band is not None and abs(c[i] / c[i - 20] - 1) < band:
            target = 0  # 국면 필터: 관망
        if target == 0 and row.date >= START: flat_days += 1
        if target != side:
            if q:
                eq -= abs(q) * c[i] * (FEE + SLIP); trades.append(eq / entry_eq - 1); q = 0.0
            if target:
                q = target * eq * expo / c[i]; eq -= abs(q) * c[i] * (FEE + SLIP); entry_eq = eq
            side = target; curve[-1] = eq
    s = pd.Series(curve, index=df.date[:len(curve)]); s = s[s.index >= START]
    return s / s.iloc[0], trades, liq, flat_days

def st(s, tr, liq, flat):
    yrs = (s.index[-1] - s.index[0]).days / 365.25; f = s.iloc[-1]
    cagr = f ** (1 / yrs) - 1 if f > 0 else -1; mdd = (s / s.cummax() - 1).min()
    return dict(final=f, cagr=cagr, mdd=mdd, calmar=cagr / -mdd if mdd else 0, n=len(tr),
                win=sum(t > 0 for t in tr) / max(len(tr), 1), flat=flat / len(s), liq=liq)

data, out = {}, {}
for sym in ["BTCUSDT", "ETHUSDT"]:
    g = {"__name__": "bt", "sys": types.SimpleNamespace(argv=["x", "/dev/null"])}
    exec(src.replace('SYM = "ETHUSDT"', f'SYM = "{sym}"').replace("OUT = sys.argv[1]", "OUT=None"), g)
    df = g["klines"](); mk = g["klines"]("markPriceKlines").set_index("t")[["h", "l"]]
    df[["h", "l"]] = mk.reindex(df.t).values
    data[sym] = (df, g["funding"]())

print("=== 1) 추천 실노출에서 Lv.1 vs Lv.7(±5%) ===")
for sym, expo in [("BTCUSDT", 1.5), ("ETHUSDT", 1.0)]:
    df, fr = data[sym]
    for name, band in [("Lv.1", None), ("Lv.7 ±5%", 0.05)]:
        s, tr, liq, fl = run(df, fr, expo, band); r = st(s, tr, liq, fl)
        out[(sym, name)] = s
        print(f"{sym[:3]} {expo}배 {name:9}: 최종 {r['final']:6.1f}배  CAGR {r['cagr']:+6.1%}  MDD {r['mdd']:6.1%}  CAGR/MDD {r['calmar']:.2f}  매매 {r['n']:3}  승률 {r['win']:.0%}  관망 {r['flat']:.0%}")
    # 연도별
    yrs = sorted(set(out[(sym, 'Lv.1')].index.year))
    line = "   연도별 Lv.1 / Lv.7: "
    for y in yrs:
        vals = []
        for name in ("Lv.1", "Lv.7 ±5%"):
            s = out[(sym, name)]; prev = s[s.index.year < y]
            a0 = prev.iloc[-1] if len(prev) else s.iloc[0]; vals.append(s[s.index.year == y].iloc[-1] / a0 - 1)
        line += f"{y} {vals[0]:+.0%}/{vals[1]:+.0%}  "
    print(line)

print("\n=== 2) 임계값 민감도 (과최적화 점검) ===")
for sym, expo in [("BTCUSDT", 1.5), ("ETHUSDT", 1.0)]:
    df, fr = data[sym]
    for band in [None, 0.02, 0.03, 0.05, 0.07, 0.10]:
        s, tr, liq, fl = run(df, fr, expo, band); r = st(s, tr, liq, fl)
        print(f"{sym[:3]} {expo}배 band {('없음' if band is None else f'±{band:.0%}'):5}: CAGR {r['cagr']:+6.1%}  MDD {r['mdd']:6.1%}  CAGR/MDD {r['calmar']:.2f}  관망 {r['flat']:.0%}")

print("\n=== 3) Lv.7(±5%) 실노출 스윕 ===")
for sym in data:
    df, fr = data[sym]
    for expo in [1, 1.5, 2, 2.5, 3]:
        r1 = st(*run(df, fr, expo, None)); r7 = st(*run(df, fr, expo, 0.05))
        print(f"{sym[:3]} 실노출 {expo:>3}배: Lv.1 CAGR {r1['cagr']:+6.1%} MDD {r1['mdd']:6.1%}  |  Lv.7 CAGR {r7['cagr']:+6.1%} MDD {r7['mdd']:6.1%}")

print("\n=== 4) 최대낙폭 구간 재확인 ===")
for sym, expo, a, b in [("BTCUSDT", 1.5, "2022-01-22", "2022-11-08"), ("BTCUSDT", 1.5, "2022-06-15", "2022-11-08"), ("ETHUSDT", 1.0, "2021-05-11", "2021-06-03")]:
    for name in ("Lv.1", "Lv.7 ±5%"):
        s = out[(sym, name)][a:b]
        print(f"{sym[:3]} {a}~{b} {name:9}: {s.iloc[-1]/s.iloc[0]-1:+.0%}")

import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import FuncFormatter
font_manager.fontManager.addfont("/System/Library/Fonts/AppleSDGothicNeo.ttc")
plt.rcParams["font.family"] = "Apple SD Gothic Neo"; plt.rcParams["axes.unicode_minus"] = False
fig, axes = plt.subplots(2, 2, figsize=(15, 9), gridspec_kw={"height_ratios": [3, 1.4]})
for k, (sym, expo) in enumerate([("BTCUSDT", 1.5), ("ETHUSDT", 1.0)]):
    ax, ax2 = axes[0][k], axes[1][k]
    for name, color in (("Lv.1", "#7a7a7a"), ("Lv.7 ±5%", "#2e8b57")):
        s = out[(sym, name)]; mdd = (s / s.cummax() - 1)
        ax.plot(s.index, s, color=color, lw=1.5, label=f"{name} → {s.iloc[-1]:.1f}배, MDD {mdd.min():.0%}")
        ax2.fill_between(mdd.index, mdd * 100, 0, color=color, alpha=.35, label=f"{name} 낙폭")
    ax.set_yscale("log"); ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:g}배"))
    ax.set_title(f"{sym[:3]} · 실노출 {expo:g}배 · Lv.1 vs Lv.7 국면 필터", fontsize=13)
    ax.legend(fontsize=10, loc="upper left"); ax.grid(alpha=.3, which="both")
    ax2.set_ylabel("낙폭 (%)"); ax2.legend(fontsize=9, loc="lower left"); ax2.grid(alpha=.3)
fig.suptitle("Lv.7 국면 필터: 최근 20일 등락 ±5% 미만이면 관망  (수수료·슬리피지·펀딩·마크가격 청산 반영, 2020-01 ~ )", fontsize=12)
plt.tight_layout(); p = OUTDIR + "/Lv1_vs_Lv7_국면필터.png"; plt.savefig(p, dpi=120); print("\nsaved", p)
