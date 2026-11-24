"""QUANT FLOOR Lv.1 (종가 vs 50일 평균) 로직을 ETHUSDT 무기한 10배로 백테스트.

앱과 동일한 규칙:
- 매일 09:00 KST(00:00 UTC) 일봉 마감 직후, 확정 종가 > 50일 평균이면 롱, < 이면 숏.
- 방향이 바뀔 때만 전량 청산 후 재진입. 수량 = 사용가능 USDT x 비중% x 배율 / 가격 (복리).
- 방향이 같으면 수량을 유지 (매일 리밸런싱 안 함).
비용: 테이커 수수료 0.05%(진입/청산 각각), 실제 펀딩비(8시간), 진입 슬리피지 0.02%.
청산: 교차(Cross) 기준, 일중 고가/저가에서 계좌 자산이 유지증거금(명목 0.5%) 이하가 되면 강제청산(자산 0).
"""
import json, os, sys, time, urllib.request
from datetime import datetime, timezone

import pandas as pd

OUT = sys.argv[1]
SYM = "ETHUSDT"
LEV = 10
FEE = 0.0005
SLIP = 0.0002
MMR = 0.005
WEIGHTS = [10, 20, 30, 50, 100]
START = "2020-01-01"


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "backtest"}), timeout=30) as r:
        return json.loads(r.read())


def klines(kind="klines"):
    rows, start = [], 0
    while True:
        b = get(f"https://fapi.binance.com/fapi/v1/{kind}?symbol={SYM}&interval=1d&limit=1500&startTime={start}")
        rows += b
        if len(b) < 1500:
            break
        start = b[-1][0] + 1
    df = pd.DataFrame(rows).iloc[:, :7]
    df.columns = ["t", "o", "h", "l", "c", "v", "ct"]
    df = df.astype(float)
    df["date"] = pd.to_datetime(df.t, unit="ms", utc=True)
    now = time.time() * 1000
    return df[df.ct < now].reset_index(drop=True)  # 확정봉만


def funding():
    rows, start = [], 0
    while True:
        b = get(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={SYM}&limit=1000&startTime={start}")
        rows += b
        if len(b) < 1000:
            break
        start = b[-1]["fundingTime"] + 1
    f = pd.DataFrame(rows)
    f["fundingRate"] = f.fundingRate.astype(float)
    f["date"] = pd.to_datetime(f.fundingTime, unit="ms", utc=True).dt.floor("D")
    return f.groupby("date").fundingRate.sum()  # 하루 펀딩비 합


def run(df, fr, weight, lev=LEV):
    eq, q, side = 1.0, 0.0, 0  # 초기자산 1, 보유수량(부호포함)
    curve, trades, liq = [], [], None
    entry_eq = None
    for i in range(len(df)):
        row = df.iloc[i]
        if i >= 1 and q:
            prev = df.c.iloc[i - 1]
            # 일중 최악가로 강제청산 체크
            worst = row.l if q > 0 else row.h
            if eq + q * (worst - prev) <= MMR * abs(q) * worst:
                eq, q = 0.0, 0.0
                liq = row.date
            else:
                eq += q * (row.c - prev)
                eq -= fr.get(row.date, 0.0) * q * row.c  # 롱은 양(+)펀딩 시 지불
        curve.append(eq)
        if eq <= 0:
            curve += [0.0] * (len(df) - i - 1)
            break
        if i < 59 or row.date < pd.Timestamp(START, tz="UTC") - pd.Timedelta(days=1):
            continue
        sma = df.c.iloc[i - 49:i + 1].mean()
        target = 1 if row.c > sma else -1 if row.c < sma else side
        if target != side:
            px = row.c
            if q:
                eq -= abs(q) * px * (FEE + SLIP)
                trades.append(eq / entry_eq - 1)
            q = target * eq * weight / 100 * lev / px
            eq -= abs(q) * px * (FEE + SLIP)
            entry_eq, side = eq, target
            curve[-1] = eq
    s = pd.Series(curve, index=df.date[:len(curve)])
    return s[s.index >= pd.Timestamp(START, tz="UTC")], trades, liq


def stats(s, trades, liq):
    s = s / s.iloc[0]
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    final = s.iloc[-1]
    cagr = final ** (1 / yrs) - 1 if final > 0 else -1
    mdd = (s / s.cummax() - 1).min()
    win = sum(t > 0 for t in trades) / len(trades) if trades else 0
    return dict(final=final, ret=final - 1, cagr=cagr, mdd=mdd, n=len(trades), win=win,
                liq=liq.strftime("%Y-%m-%d") if liq is not None else "-")


df = klines()
mk = klines("markPriceKlines").set_index("t")[["h", "l"]]
# 강제청산은 바이낸스처럼 마크가격 고가/저가로 판정 (2020-03-13 체결가 323 순간 스파이크 제외)
df[["h", "l"]] = mk.reindex(df.t).values
fr = funding()
res = {}
for w in WEIGHTS:
    s, tr, liq = run(df, fr, w)
    res[w] = (s, stats(s, tr, liq), tr)
bh = df.set_index("date").c
bh = bh[bh.index >= pd.Timestamp(START, tz="UTC")]
bh = bh / bh.iloc[0]
s1, tr1, l1 = run(df, fr, 100, lev=1)

print(f"기간 {res[30][0].index[0]:%Y-%m-%d} ~ {res[30][0].index[-1]:%Y-%m-%d}  ETH 현물보유 {bh.iloc[-1]:.2f}배  MDD {(bh/bh.cummax()-1).min():.1%}")
st1 = stats(s1, tr1, l1)
print(f"1배 전액(레버리지 없음): 최종 {st1['final']:.2f}배  CAGR {st1['cagr']:.1%}  MDD {st1['mdd']:.1%}")
for w, (s, st, tr) in res.items():
    print(f"10배 비중 {w:>3}% (실노출 {w*LEV/100:.0f}배): 최종 {st['final']:,.2f}배  수익률 {st['ret']:+,.0%}  CAGR {st['cagr']:+.1%}  MDD {st['mdd']:.1%}  매매 {st['n']}회  승률 {st['win']:.0%}  강제청산 {st['liq']}")

# 연도별 (비중 30%)
s = res[30][0]
print("\n연도별 수익률 (10배·비중30%  vs  ETH 보유)")
for y in sorted(set(s.index.year)):
    a = s[s.index.year == y]; b = bh[bh.index.year == y]
    prev_a = s[s.index.year < y]; prev_b = bh[bh.index.year < y]
    a0 = prev_a.iloc[-1] if len(prev_a) else a.iloc[0]
    b0 = prev_b.iloc[-1] if len(prev_b) else b.iloc[0]
    ra = a.iloc[-1] / a0 - 1 if a0 > 0 else float("nan")
    print(f"  {y}: 전략 {ra:+.0%}   ETH {b.iloc[-1]/b0-1:+.0%}")

# 차트 (파란색 사용 안 함)
import matplotlib
plt_minus=None
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
font_manager.fontManager.addfont("/System/Library/Fonts/AppleSDGothicNeo.ttc")
plt.rcParams["font.family"] = "Apple SD Gothic Neo"
plt.rcParams["axes.unicode_minus"] = False
colors = {10: "#7a7a7a", 20: "#2e8b57", 30: "#d9822b", 50: "#c0392b", 100: "#8e44ad"}
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8.5), sharex=True, gridspec_kw={"height_ratios": [3, 1.3]})
for w, (s, st, _) in res.items():
    v = s / s.iloc[0]
    if st['liq'] != '-':
        v = v[v > 0]
        ax1.plot(v.index[-1], v.iloc[-1], marker="x", ms=11, mew=2.5, color=colors[w])
    ax1.plot(v.index, v, color=colors[w], lw=1.6 if w == 30 else 1.1,
             label=f"10배 · 비중 {w}% → {st['final']:,.1f}배 (MDD {st['mdd']:.0%})" + (" 청산" if st['liq'] != '-' else ""))
ax1.plot(bh.index, bh, color="#222222", lw=1, ls="--", label=f"ETH 보유 → {bh.iloc[-1]:.1f}배")
ax1.set_yscale("log"); ax1.set_ylabel("자산 배수 (로그, x = 강제청산)")
ax1.set_ylim(0.3, 150)
from matplotlib.ticker import FuncFormatter
ax1.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:g}배"))
ax1.set_title(f"QUANT FLOOR Lv.1 (종가 vs 50일 평균)  ·  ETHUSDT 무기한 10배  ·  {START} ~ {s.index[-1]:%Y-%m-%d}\n수수료 0.05%+슬리피지 0.02%, 실제 펀딩비 반영, 복리", fontsize=12)
ax1.legend(fontsize=9, loc="upper left"); ax1.grid(alpha=.3, which="both")
for w in (20, 30):
    s = res[w][0]; dd = s / s.cummax() - 1
    ax2.fill_between(dd.index, dd * 100, 0, color=colors[w], alpha=.35, label=f"비중 {w}% 낙폭")
ax2.set_ylabel("낙폭 (%)"); ax2.legend(fontsize=9, loc="lower left"); ax2.grid(alpha=.3)
plt.tight_layout(); plt.savefig(OUT, dpi=130)
print("\nsaved", OUT)
