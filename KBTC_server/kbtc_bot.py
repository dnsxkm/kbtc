#!/usr/bin/env python3
"""KBTC 서버 봇 - KOREA BITCOIN 앱의 Lv.1 50일 추세 매매를 화면 없이 24시간 실행.

규칙 (앱과 동일)
- 매일 09:00 KST(00:00 UTC) 일봉이 확정되면, 확정 종가 > 50일 평균이면 롱, < 이면 숏.
- 방향이 바뀔 때만 기존 포지션 전량 청산 후 재진입. 같은 방향이면 유지.
- 진입 규모 = 사용 가능 USDT x 비중% x 배율 (청산 후 잔고 기준 = 복리).

앱과 다른 점
- 하루 한 번만 판단하며, 서버가 늦게 깨어나도 그날 확정봉으로 판단한다 (state.json 으로 중복 방지).
- 처음 시작하면 기본은 다음 09:00 까지 기다린다. ENTER_NOW=true 면 바로 현재 신호대로 맞춘다.

사용법
  python3 kbtc_bot.py            # 계속 실행 (systemd 로 띄우는 용도)
  python3 kbtc_bot.py status     # 신호/포지션/잔고만 확인 (주문 없음)
  python3 kbtc_bot.py once       # 지금 한 번 판단하고 종료 (오늘 이미 판단했으면 건너뜀)
설정은 같은 폴더의 config.env 에서 읽는다.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal as D
from statistics import mean
from uuid import uuid4

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_LEV = 15  # 레버리지 상한
LOCK = threading.Lock()
# Railway 등에서는 볼륨 경로(예: /data)를 STATE_DIR 로 지정해야 재배포 후에도 기록이 남는다.
STATE = os.path.join(os.getenv("STATE_DIR", HERE), "state.json")


# ───────────────────────── 설정 ─────────────────────────
def load_config():
    path = os.path.join(HERE, "config.env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    cfg = dict(
        key=os.getenv("BINANCE_API_KEY", ""),
        secret=os.getenv("BINANCE_API_SECRET", ""),
        mode=os.getenv("MODE", "demo").lower(),
        symbol=os.getenv("SYMBOL", "BTCUSDT").upper(),
        weight=D(os.getenv("WEIGHT", "30")),
        leverage=int(os.getenv("LEVERAGE", "10")),
        persona=os.getenv("PERSONA", "에겐"),
        enter_now=os.getenv("ENTER_NOW", "false").lower() == "true",
        tg_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        tg_chat=os.getenv("TELEGRAM_CHAT_ID", ""),
    )
    if cfg["mode"] not in ("demo", "live"):
        raise SystemExit("MODE 는 demo 또는 live 여야 합니다.")
    if not 0 < cfg["weight"] <= 100:
        raise SystemExit("WEIGHT 는 0 초과 100 이하(%)여야 합니다.")
    if not 1 <= cfg["leverage"] <= MAX_LEV:
        raise SystemExit(f"LEVERAGE 는 1~{MAX_LEV} 정수여야 합니다.")
    if not cfg["key"] or not cfg["secret"]:
        raise SystemExit("config.env 에 BINANCE_API_KEY / BINANCE_API_SECRET 을 넣으세요.")
    return cfg


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


# ───────────────────────── 바이낸스 선물 ─────────────────────────
class Futures:
    def __init__(self, cfg):
        self.key, self.secret, self.symbol = cfg["key"], cfg["secret"], cfg["symbol"]
        self.base = "https://demo-fapi.binance.com" if cfg["mode"] == "demo" else "https://fapi.binance.com"
        self.offset = 0

    def req(self, method, path, params=None, signed=False):
        params = dict(params or {})
        if signed:
            params["timestamp"] = int(time.time() * 1000) + self.offset
            params["recvWindow"] = 15000
            q = urllib.parse.urlencode(params)
            params["signature"] = hmac.new(self.secret.encode(), q.encode(), hashlib.sha256).hexdigest()
        q = urllib.parse.urlencode(params)
        url = self.base + path + ("?" + q if q else "")
        r = urllib.request.Request(url, method=method, headers={"User-Agent": "KBTC/1.0", "X-MBX-APIKEY": self.key})
        try:
            with urllib.request.urlopen(r, timeout=15) as res:
                return json.loads(res.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            try:
                body = json.loads(body).get("msg", body)
            except json.JSONDecodeError:
                pass
            raise RuntimeError(f"Binance HTTP {e.code}: {body}") from e

    def sync(self):
        self.offset = int(self.req("GET", "/fapi/v1/time")["serverTime"]) - int(time.time() * 1000)
        return int(time.time() * 1000) + self.offset

    def closed_daily(self, now):
        bars = self.req("GET", "/fapi/v1/klines", {"symbol": self.symbol, "interval": "1d", "limit": 70})
        return [b for b in bars if b[6] < now]

    def position(self):
        rows = self.req("GET", "/fapi/v3/positionRisk", {"symbol": self.symbol}, True)
        if any(r["positionSide"] != "BOTH" for r in rows):
            raise RuntimeError("단방향(One-way) 포지션 모드가 필요합니다.")
        return sum((D(r["positionAmt"]) for r in rows), D(0))

    def account(self):
        return self.req("GET", "/fapi/v3/account", signed=True)

    def available(self):
        rows = self.req("GET", "/fapi/v3/balance", signed=True)
        return next((D(b["availableBalance"]) for b in rows if b["asset"] == "USDT"), D(0))

    def set_leverage(self, lev):
        return int(self.req("POST", "/fapi/v1/leverage", {"symbol": self.symbol, "leverage": lev}, True)["leverage"])

    def price(self):
        return D(self.req("GET", "/fapi/v1/ticker/price", {"symbol": self.symbol})["price"])

    def filters(self):
        info = next(s for s in self.req("GET", "/fapi/v1/exchangeInfo")["symbols"] if s["symbol"] == self.symbol)
        return {f["filterType"]: f for f in info["filters"]}

    def order(self, delta, closing):
        data = self.req("POST", "/fapi/v1/order", {
            "symbol": self.symbol, "side": "BUY" if delta > 0 else "SELL", "type": "MARKET",
            "quantity": format(abs(delta), "f"), "reduceOnly": "true" if closing else "false",
            "newClientOrderId": "kbtc-" + uuid4().hex[:26], "newOrderRespType": "RESULT",
        }, True)
        if data["status"] != "FILLED" or D(data["executedQty"]) != abs(delta):
            raise RuntimeError("주문이 완전히 체결되지 않았습니다. 바이낸스에서 확인하세요.")
        # Demo 응답에 avgPrice 가 빠지는 경우가 있어 체결금액/수량 → 주문 조회 → 현재가 순으로 채운다
        avg = D(data.get("avgPrice") or 0)
        if not avg and D(data.get("cumQuote") or 0):
            avg = D(data["cumQuote"]) / D(data["executedQty"])
        if not avg:
            try:
                o = self.req("GET", "/fapi/v1/order", {"symbol": self.symbol, "orderId": data["orderId"]}, True)
                avg = D(o.get("avgPrice") or 0)
            except Exception:
                pass
        data["avgPrice"] = str(avg or self.price())
        return data

    # ── TP/SL (바이낸스는 조건부 주문을 Algo Order API 로만 받는다) ──
    def open_algos(self):
        return self.req("GET", "/fapi/v1/openAlgoOrders", {"symbol": self.symbol}, True)

    def cancel_algos(self):
        for o in self.open_algos():
            self.req("DELETE", "/fapi/v1/algoOrder", {"algoId": o["algoId"]}, True)

    def tick(self):
        f = self.filters()
        return D(f["PRICE_FILTER"]["tickSize"])

    def place_tpsl(self, side, entry, tp_pct, sl_pct):
        """side: 1 롱 / -1 숏. entry 대비 가격 % 로 익절·손절(마크가격 기준, 전량 청산)."""
        tick, out = self.tick(), []
        close_side = "SELL" if side > 0 else "BUY"
        for kind, pct, sign in (("TAKE_PROFIT_MARKET", tp_pct, 1), ("STOP_MARKET", sl_pct, -1)):
            if not pct:
                continue
            px = D(entry) * (1 + side * sign * D(str(pct)) / 100)
            px = (px / tick).quantize(D(1)) * tick
            self.req("POST", "/fapi/v1/algoOrder", {
                "algoType": "CONDITIONAL", "symbol": self.symbol, "side": close_side, "type": kind,
                "triggerPrice": format(px, "f"), "closePosition": "true", "workingType": "MARK_PRICE",
                "clientAlgoId": "kbtc-" + uuid4().hex[:20]}, True)
            out.append((kind, px))
        return out


# ───────────────────────── 알림 ─────────────────────────
class Telegram:
    def __init__(self, cfg, st=None):
        self.token, self.chat = cfg["tg_token"], cfg["tg_chat"]
        self.st = st if st is not None else {}

    def send(self, text, notify=True):
        log(text.replace("\n", " | "))
        with LOCK:
            ev = self.st.setdefault("events", [])
            ev.append([time.strftime("%m/%d %H:%M"), text.replace("[KBTC] ", "")])
            del ev[:-40]
        if not notify or not self.token or not self.chat:
            return
        try:
            data = urllib.parse.urlencode({"chat_id": self.chat, "text": text}).encode()
            urllib.request.urlopen(urllib.request.Request(
                f"https://api.telegram.org/bot{self.token}/sendMessage", data=data, method="POST"), timeout=10).read()
        except Exception as e:  # 알림 실패가 매매를 막지 않게
            log(f"텔레그램 전송 실패: {e}")


# ───────────────────────── 상태 ─────────────────────────
def load_state(path=None):
    path = path or STATE
    try:
        st = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    st["__path"] = path
    return st


def save_state(st):
    path = st.get("__path", STATE)
    with LOCK:
        tmp = path + ".tmp"
        json.dump({k: v for k, v in st.items() if k != "__path"}, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, path)


def apply_overrides(cfg, st):
    """폰(웹/텔레그램)에서 바꾼 비중·배율·말투는 state 에 저장되어 환경변수보다 우선한다."""
    o = st.get("overrides", {})
    if "weight" in o:
        cfg["weight"] = D(str(o["weight"]))
    if "leverage" in o:
        cfg["leverage"] = int(o["leverage"])
    if "persona" in o:
        cfg["persona"] = o["persona"]
    cfg["tp_pct"] = float(o.get("tp_pct") or 0)
    cfg["sl_pct"] = float(o.get("sl_pct") or 0)


# ───────────────────────── 전략 ─────────────────────────
NAME = {1: "롱", -1: "숏", 0: "없음"}


def signal(closes, current):
    if len(closes) < 60:
        raise RuntimeError("확정 일봉 60개가 필요합니다.")
    last, sma = closes[-1], mean(closes[-50:])
    sig = 1 if last > sma else -1 if last < sma else current
    return sig, last, sma, (last / sma - 1) * 100


def talk(cfg, kind, **k):
    teto = cfg["persona"] == "테토"
    if kind == "enter":
        if teto:
            return (f"[KBTC] {k['side']} 진입. 간다.\n{k['date']} 종가 {k['last']:,.0f}, 50일선 대비 {k['gap']:+.1f}%\n"
                    f"{k['weight']}% x {k['lev']}배 = {k['notional']:,.0f} USDT ({k['size']} BTC) 박았다")
        return (f"[KBTC] {k['side']} 들어갔어요! ♪\n{k['date']} 종가 {k['last']:,.0f}가 50일선보다 {abs(k['gap']):.1f}% "
                f"{'위' if k['sig'] > 0 else '아래'}예요\n{k['weight']}% x {k['lev']}배 = {k['notional']:,.0f} USDT ({k['size']} BTC)")
    if kind == "hold":
        if teto:
            return f"[KBTC] {k['side']} 홀딩. 안 흔들린다.\n종가 {k['last']:,.0f}, 50일선 대비 {k['gap']:+.1f}%\n총자산 {k['equity']:,.2f} USDT"
        return (f"[KBTC] 오늘도 {k['side']} 꼭 쥐고 있어요 ♡\n종가 {k['last']:,.0f} (50일선 대비 {k['gap']:+.1f}%)\n"
                f"총자산 {k['equity']:,.2f} USDT")
    return ""


def decide(cfg, ex, tg, st, force=False):
    """오늘 확정봉 기준으로 한 번 판단. 이미 처리한 날이면 아무것도 안 한다."""
    if st.get("paused") and not force:
        return False
    now = ex.sync()
    closed = ex.closed_daily(now)
    day = closed[-1][6]
    if st.get("last_day") == day and not force:
        return False
    closes = [D(b[4]) for b in closed]
    qty = ex.position()
    cur = int(qty > 0) - int(qty < 0)
    sig, last, sma, gap = signal(closes, cur)
    date = time.strftime("%m/%d", time.localtime(day / 1000))
    if ex.req("GET", "/fapi/v1/openOrders", {"symbol": cfg["symbol"]}, True):
        raise RuntimeError(f"{cfg['symbol']} 미체결 주문이 있어 매매를 건너뜁니다. 바이낸스에서 정리하세요.")
    if sig != cur:
        try:
            ex.cancel_algos()  # 이전 포지션의 TP/SL 정리
        except Exception as e:
            log(f"TP/SL 취소 실패: {e}")
        if qty:
            r = ex.order(-qty, True)
            tg.send(f"[KBTC] {NAME[cur]} 청산 {r['executedQty']} @ {r['avgPrice']}")
            if ex.position() != 0:
                raise RuntimeError("청산 후에도 포지션이 남아 있습니다.")
        lev = ex.set_leverage(cfg["leverage"])
        f = ex.filters()
        lot, step = f["MARKET_LOT_SIZE"], D(f["MARKET_LOT_SIZE"]["stepSize"])
        price = ex.price()
        notional = ex.available() * cfg["weight"] / 100 * lev
        size = (notional / price // step) * step
        if not D(lot["minQty"]) <= size <= D(lot["maxQty"]) or size * price < D(f["MIN_NOTIONAL"]["notional"]):
            raise RuntimeError(f"진입 규모 {notional:.2f} USDT 가 거래소 주문 범위 밖입니다.")
        r = ex.order(sig * size, False)
        st["last_entry"] = dict(at=time.time(), target=sig, date=date, last=float(last), gap=float(gap),
                                weight=float(cfg["weight"]), lev=lev, size=str(size),
                                notional=float(size * D(r["avgPrice"])), flipped=bool(qty))
        tg.send(talk(cfg, "enter", side=NAME[sig], sig=sig, date=date, last=last, gap=gap,
                     weight=cfg["weight"], lev=lev, notional=size * D(r["avgPrice"]), size=size))
        if cfg.get("tp_pct") or cfg.get("sl_pct"):
            try:
                placed = ex.place_tpsl(sig, r["avgPrice"], cfg.get("tp_pct"), cfg.get("sl_pct"))
                tg.send("[KBTC] TP/SL 설정 · " + " · ".join(f"{'익절' if k.startswith('TAKE') else '손절'} {p:,.1f}" for k, p in placed))
            except Exception as e:
                tg.send(f"[KBTC] TP/SL 설정 실패: {e}")
    else:
        eq = D(ex.account()["totalMarginBalance"])
        tg.send(talk(cfg, "hold", side=NAME[sig], last=last, gap=gap, equity=eq))
    st["last_day"] = day
    st["last_signal"] = sig
    save_state(st)
    return True


def status(cfg, ex):
    now = ex.sync()
    closed = ex.closed_daily(now)
    qty = ex.position()
    sig, last, sma, gap = signal([D(b[4]) for b in closed], int(qty > 0) - int(qty < 0))
    acct = ex.account()
    lev = ex.req("GET", "/fapi/v2/positionRisk", {"symbol": cfg["symbol"]}, True)[0]["leverage"]
    left = (closed[-1][6] + 86_400_000 - now) / 1000
    st = load_state()
    print(f"모드 {cfg['mode']} · {cfg['symbol']} · 비중 {cfg['weight']}% · 설정 배율 {cfg['leverage']}x (현재 계정 {lev}x)")
    print(f"신호 {NAME[sig]} · 확정 종가 {last:,.1f} vs 50일 평균 {sma:,.1f} ({gap:+.2f}%)")
    print(f"포지션 {qty} · 총자산 {D(acct['totalMarginBalance']):,.2f} USDT · 사용 가능 {D(acct['availableBalance']):,.2f} USDT")
    print(f"다음 판단까지 {int(left // 3600)}시간 {int(left % 3600 // 60)}분 · 마지막 처리일 "
          + (time.strftime('%Y-%m-%d', time.localtime(st['last_day'] / 1000)) if st.get("last_day") else "없음"))


def run_forever(cfg, ex, tg, st):
    # 시작 점검: 지역 차단(HTTP 451/403)이나 키 오류를 바로 알 수 있게
    try:
        ex.sync()
        qty = ex.position()
        eq = D(ex.account()["totalMarginBalance"])
        log(f"연결 확인 OK · {cfg['mode']} · 포지션 {qty} · 총자산 {eq:,.2f} USDT · state={STATE}")
    except Exception as e:
        tg.send(f"[KBTC] 시작 점검 실패: {e}\n(HTTP 451/403 이면 서버 지역이 바이낸스에서 막힌 것입니다. 지역을 바꾸세요.)")
        raise
    import users, web
    store = users.Store(cfg, st, tg)
    web.start(store)
    if not st.get("last_day") and not cfg["enter_now"]:
        now = ex.sync()
        st["last_day"] = ex.closed_daily(now)[-1][6]
        save_state(st)
        tg.send(f"[KBTC] 서버 봇 시작 ({cfg['mode']}, 비중 {cfg['weight']}%, {cfg['leverage']}배). 다음 09:00 일봉 마감부터 매매합니다.\n/help 로 사용법을 볼 수 있어요.")
    else:
        tg.send(f"[KBTC] 서버 재시작 ({cfg['mode']}, 비중 {cfg['weight']}%, {cfg['leverage']}배, 사용자 {len(store.all())}명).", notify=False)  # 재배포마다 알림 X
    while True:
        for ctx in store.all():  # 서버 주인 + 폰에서 API 연결한 사용자 모두
            try:
                decide(ctx.cfg, ctx.ex, ctx.tg, ctx.st)
                ctx.last_err = None
                try:
                    import trade
                    trade.snap(ctx)
                except Exception as e:
                    log(f"[{ctx.uid}] 자산 스냅샷 실패: {e}")
            except Exception as e:
                msg = f"[KBTC] 오류: {e}"
                log(f"[{ctx.uid}] " + traceback.format_exc().strip().splitlines()[-1])
                if msg != ctx.last_err or time.time() - ctx.err_at > 3600:  # 같은 오류는 1시간에 한 번
                    ctx.tg.send(msg + "\n1분 뒤 다시 시도합니다.")
                    ctx.last_err, ctx.err_at = msg, time.time()
        time.sleep(30)


def main():
    cfg = load_config()
    st = load_state()
    apply_overrides(cfg, st)
    ex, tg = Futures(cfg), Telegram(cfg, st)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "status":
        status(cfg, ex)
    elif cmd == "once":
        print("처리함" if decide(cfg, ex, tg, st) else "오늘은 이미 처리했거나 일시정지 상태입니다.")
    else:
        run_forever(cfg, ex, tg, st)


if __name__ == "__main__":
    main()
