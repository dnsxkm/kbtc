"""주문/포지션 기록, 월 PNL 캘린더, 계좌 그래프, CLOSE, TP/SL (USDT 무기한 선물 · 바이낸스/OKX/Gate 공통).

거래소 호출은 ctx.ex 의 공통 메서드(바이낸스 모양 응답)만 쓴다. 거래소별 차이는 kbtc_bot.Futures / exchanges.py 에.
바이낸스는 '포지션 기록' API 가 없어서 체결(userTrades)을 시간순으로 따라가며
포지션이 0 이 되거나 방향이 바뀌는 지점을 '종료된 포지션'으로 묶는다.
계좌 그래프는 현재 지갑 잔고에서 수입 내역(income: 실현손익·수수료·펀딩·입출금)을 거꾸로 빼서 일별로 복원한다.
"""
from __future__ import annotations

import time
from collections import defaultdict
from decimal import Decimal as D

import kbtc_bot as bot

DAY = 86_400_000
KST = 9 * 3_600_000
LOOKBACK_DAYS = 90
_cache: dict = {}


def _cached(ctx, key, ttl, fn):
    k = (ctx.uid, key)
    hit = _cache.get(k)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    if time.time() - getattr(ctx.ex, "_synced", 0) > 600:  # 서명 요청 전 서버 시간 맞추기
        ctx.ex.sync(); ctx.ex._synced = time.time()
    val = fn()
    _cache[k] = (time.time(), val)
    return val


def invalidate(ctx):
    for k in [k for k in _cache if k[0] == ctx.uid]:
        _cache.pop(k, None)


def _trades(ctx):
    def f():
        rows = ctx.ex.trades_hist(LOOKBACK_DAYS)
        return sorted({r["id"]: r for r in rows}.values(), key=lambda r: (r["time"], r["id"]))
    return _cached(ctx, "trades", 120, f)


def _income(ctx):
    return _cached(ctx, "income", 120, lambda: _income_raw(ctx))


def _income_raw(ctx):
    rows = ctx.ex.income_hist(LOOKBACK_DAYS)
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: r["time"]):
        key = (r["time"], r["incomeType"], r["income"], r.get("tranId"), r.get("tradeId"))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


# ───────────────────────── 주문 기록 ─────────────────────────
def orders(ctx, limit=50):
    def f():
        rows = ctx.ex.orders_hist(limit)
        out = []
        for o in sorted(rows, key=lambda o: o["time"], reverse=True):
            out.append(dict(time=o["time"], side=o["side"], type=o["type"], status=o["status"],
                            qty=float(o["executedQty"] or o["origQty"]), price=float(o.get("avgPrice") or o.get("price") or 0),
                            reduce=o.get("reduceOnly", False), bot="kbtc" in (o.get("clientOrderId") or "")))
        try:
            for a in ctx.ex.open_algos():
                out.insert(0, dict(time=a.get("createTime", 0), side=a["side"], type=a["orderType"], status="대기(TP/SL)",
                                   qty=0, price=float(a.get("triggerPrice") or 0), reduce=True, bot=True))
        except Exception:
            pass
        return out
    return _cached(ctx, "orders", 20, f)


# ───────────────────────── 포지션 기록 ─────────────────────────
def positions(ctx):
    def f():
        lev = ctx.cfg["leverage"]
        out, cur = [], None
        net = D(0)
        for t in _trades(ctx):
            q = D(t["qty"]) * (1 if t["side"] == "BUY" else -1)
            px, pnl, fee = D(t["price"]), D(t["realizedPnl"]), D(t["commission"])
            if cur is None:
                cur = dict(side=1 if q > 0 else -1, open=t["time"], qty=D(0), cost=D(0), exit_qty=D(0), exit_val=D(0), pnl=D(0), fee=D(0))
            opening = (q > 0) == (cur["side"] > 0)
            if opening:
                cur["qty"] += abs(q); cur["cost"] += abs(q) * px
            else:
                close_q = min(abs(q), abs(net))
                cur["exit_qty"] += close_q; cur["exit_val"] += close_q * px
            cur["pnl"] += pnl; cur["fee"] += fee
            new_net = net + q
            if net != 0 and (new_net == 0 or (new_net > 0) != (net > 0)):
                entry = cur["cost"] / cur["qty"] if cur["qty"] else D(0)
                exit_ = cur["exit_val"] / cur["exit_qty"] if cur["exit_qty"] else px
                margin = cur["qty"] * entry / lev if lev else D(0)
                net_pnl = cur["pnl"] - cur["fee"]
                out.append(dict(side=cur["side"], open=cur["open"], close=t["time"], qty=float(cur["qty"]),
                                entry=float(entry), exit=float(exit_), pnl=float(cur["pnl"]), fee=float(cur["fee"]),
                                net=float(net_pnl), roi=float(net_pnl / margin * 100) if margin else 0.0, lev=lev))
                cur = None
                if new_net != 0:  # 한 체결로 방향이 뒤집힌 경우 남은 수량으로 새 포지션 시작
                    cur = dict(side=1 if new_net > 0 else -1, open=t["time"], qty=abs(new_net), cost=abs(new_net) * px,
                               exit_qty=D(0), exit_val=D(0), pnl=D(0), fee=D(0))
            net = new_net
        return list(reversed(out))
    return _cached(ctx, "positions", 60, f)


# ───────────────────────── 월 PNL 캘린더 · 계좌 그래프 ─────────────────────────
PNL_TYPES = {"REALIZED_PNL", "COMMISSION", "FUNDING_FEE"}


def _kst_day(ms):
    return time.strftime("%Y-%m-%d", time.gmtime((ms + KST) / 1000))


def _merge(ctx, key, new):
    """바이낸스는 최근 90일만 주므로, 받은 일별 값을 state 에 계속 쌓아 ALL 기간을 만든다."""
    old = ctx.st.setdefault(key, {})
    changed = False
    for k, v in new.items():
        if old.get(k) != v:
            old[k] = v; changed = True
    if changed:
        bot.save_state(ctx.st)
    return dict(sorted(old.items()))


def snap(ctx, every=300, keep_days=8):
    """5분마다 총자산 스냅샷 (1D/1W 계좌 그래프용)."""
    now = time.time()
    s = ctx.st.setdefault("eq_snaps", [])
    if s and now - s[-1][0] / 1000 < every:
        return
    eq = float(ctx.ex.account()["totalMarginBalance"])
    s.append([int(now * 1000), round(eq, 2)])
    cut = (now - keep_days * 86400) * 1000
    ctx.st["eq_snaps"] = [x for x in s if x[0] >= cut]
    bot.save_state(ctx.st)


def snaps(ctx):
    return ctx.st.get("eq_snaps", [])


def calendar(ctx):
    """{'YYYY-MM-DD': 손익} (실현손익 + 수수료 + 펀딩, KST 기준 일자)."""
    def f():
        days = defaultdict(float)
        for r in _income(ctx):
            if r["incomeType"] in PNL_TYPES and r["asset"] == "USDT":
                days[_kst_day(r["time"])] += float(r["income"])
        return _merge(ctx, "pnl_days", {k: round(v, 4) for k, v in sorted(days.items())})
    return _cached(ctx, "calendar", 120, f)


def equity(ctx):
    """[[날짜, 그날 마감 지갑잔고], ...] 최근 90일 + 오늘 총자산."""
    def f():
        acct = ctx.ex.account()
        wallet = float(acct["totalWalletBalance"])
        inc = [r for r in _income(ctx) if r["asset"] == "USDT"]
        now = ctx.ex.sync()
        by_day = defaultdict(float)
        for r in inc:
            by_day[_kst_day(r["time"])] += float(r["income"])
        out, bal = [], wallet
        for i in range(LOOKBACK_DAYS + 1):
            d = _kst_day(now - i * DAY)
            out.append([d, round(bal, 2)])
            bal -= by_day.get(d, 0.0)
        out.reverse()
        out[-1] = [out[-1][0], round(float(acct["totalMarginBalance"]), 2)]  # 오늘은 미실현 포함 총자산
        return [[k, v] for k, v in _merge(ctx, "equity_days", dict(out)).items()]
    return _cached(ctx, "equity", 120, f)


# ───────────────────────── CLOSE · TP/SL ─────────────────────────
def close_position(ctx, ratio=1.0):
    """ratio=1 이면 전량(Close all, TP/SL 도 취소), 0.25/0.5/0.75 면 일부만 시장가 청산(Close)."""
    ex = ctx.ex
    ex.sync()
    qty = ex.position()
    if not qty:
        raise ValueError("닫을 포지션이 없어요.")
    ratio = float(ratio)
    if not 0 < ratio <= 1:
        raise ValueError("청산 비율은 0~100% 사이")
    if ratio >= 0.999:
        part = abs(qty)
        try:
            ex.cancel_algos()
        except Exception:
            pass
    else:
        step = D(ex.filters()["MARKET_LOT_SIZE"]["stepSize"])
        part = (abs(qty) * D(str(ratio)) // step) * step
        if part <= 0:
            raise ValueError("청산 수량이 최소 주문 단위보다 작아요.")
    r = ex.order(-part if qty > 0 else part, True)
    invalidate(ctx)
    return dict(side="롱" if qty > 0 else "숏", qty=float(part), price=float(D(r["avgPrice"])), all=part == abs(qty))


def realized_now(ctx):
    """지금 열린 포지션의 실현손익(부분청산 손익 - 수수료). 포지션이 0이었던 마지막 시점 이후 체결 합계."""
    def f():
        net, acc = D(0), D(0)
        for t in _trades(ctx):
            q = D(t["qty"]) * (1 if t["side"] == "BUY" else -1)
            if net == 0:
                acc = D(0)
            acc += D(t["realizedPnl"]) - D(t["commission"])
            new = net + q
            if net != 0 and (new > 0) != (net > 0) and new != 0:
                acc = D(0)  # 방향이 뒤집힌 체결
            net = new
        return float(acc) if net != 0 else 0.0
    return _cached(ctx, "realized", 60, f)


def set_tpsl_price(ctx, tp_price, sl_price, auto=True, ratio=1.0):
    """OKX 처럼 트리거 가격으로 TP/SL 설정. auto 면 진입가 대비 % 로 저장해 다음 진입에도 자동 적용."""
    if not float(ratio or 0) > 0 and (tp_price or sl_price):
        raise ValueError("Amount 가 0 이라 TP/SL 을 설정하지 않았어요.")
    ex = ctx.ex
    ex.sync()
    pos = ex.pos_info()
    amt, entry = D(pos["positionAmt"]), D(pos["entryPrice"])
    if not amt:
        raise ValueError("열린 포지션이 없어요.")
    side = 1 if amt > 0 else -1
    mark = D(pos["markPrice"])
    tp = D(str(tp_price)) if tp_price else None
    sl = D(str(sl_price)) if sl_price else None
    if tp and (tp - mark) * side <= 0:
        raise ValueError(f"TP 는 현재가 {mark:,.1f} 보다 {'위' if side > 0 else '아래'}여야 해요.")
    if sl and (mark - sl) * side <= 0:
        raise ValueError(f"SL 은 현재가 {mark:,.1f} 보다 {'아래' if side > 0 else '위'}여야 해요.")
    part = None
    if (tp or sl) and float(ratio) < 0.999:  # 일부 수량만 TP/SL
        step = D(ex.filters()["MARKET_LOT_SIZE"]["stepSize"])
        part = (abs(amt) * D(str(ratio)) // step) * step
        if part <= 0:
            raise ValueError("수량이 최소 주문 단위보다 작아요.")
    ex.cancel_algos()
    placed = []
    if tp or sl:
        tick = ex.tick()
        rnd = lambda p: (p / tick).quantize(D(1)) * tick if p else None
        placed = [(k, float(p)) for k, p in ex.place_tpsl_px(side, rnd(tp), rnd(sl), part)]
    o = ctx.st.setdefault("overrides", {})
    if auto:
        o["tp_pct"] = round(float(abs(tp / entry - 1) * 100), 3) if tp else 0.0
        o["sl_pct"] = round(float(abs(sl / entry - 1) * 100), 3) if sl else 0.0
    ctx.cfg["tp_pct"], ctx.cfg["sl_pct"] = o.get("tp_pct", 0), o.get("sl_pct", 0)
    invalidate(ctx)
    return placed


def set_tpsl(ctx, tp_pct, sl_pct, apply_now=True):
    """비율 저장(다음 진입부터 자동) + 지금 포지션에도 바로 적용."""
    for v in (tp_pct, sl_pct):
        if v is not None and not 0 <= float(v) <= 100:
            raise ValueError("TP/SL 은 0~100% 사이로 입력하세요. (0 = 사용 안 함)")
    o = ctx.st.setdefault("overrides", {})
    o["tp_pct"] = float(tp_pct or 0); o["sl_pct"] = float(sl_pct or 0)
    ctx.cfg["tp_pct"], ctx.cfg["sl_pct"] = o["tp_pct"], o["sl_pct"]
    placed = []
    if apply_now:
        ex = ctx.ex
        ex.sync()
        ex.cancel_algos()
        pos = ex.pos_info()
        amt = D(pos["positionAmt"])
        if amt and (o["tp_pct"] or o["sl_pct"]):
            placed = ex.place_tpsl(1 if amt > 0 else -1, D(pos["entryPrice"]), o["tp_pct"], o["sl_pct"])
    invalidate(ctx)
    return [(k, float(p)) for k, p in placed]


def current_tpsl(ctx):
    def f():
        out = {}
        for a in ctx.ex.open_algos():
            out["tp" if a["orderType"].startswith("TAKE") else "sl"] = float(a.get("triggerPrice") or 0)
        return out
    try:
        return _cached(ctx, "tpsl", 10, f)
    except Exception:
        return {}


def funding(ctx):
    """{'YYYY-MM-DD': 펀딩비 합} (KST)."""
    def f():
        days = defaultdict(float)
        for r in _income(ctx):
            if r["incomeType"] == "FUNDING_FEE" and r["asset"] == "USDT":
                days[_kst_day(r["time"])] += float(r["income"])
        return {k: round(v, 4) for k, v in sorted(days.items())}
    return _cached(ctx, "funding", 120, f)
