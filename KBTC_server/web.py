"""KBTC 폰용 창구: 모바일 웹 앱(여러 사용자) + 서버 주인용 텔레그램 명령.

웹 (각자 자기 바이낸스/OKX/Gate Demo API 키로 접속)
  GET  /                 앱 화면 (홈 화면에 추가하면 앱처럼 사용)
  POST /api/connect      {"exchange": "binance|okx|gate", "key": "...", "secret": "...", "passphrase": "(OKX)"}  → 키 확인 후 세션 쿠키
  GET  /api/state        시세·내 포지션·내 계좌·브리핑·설정·활동 기록
  POST /api/settings     {"weight": 30, "leverage": 10, "persona": "에겐"}
  POST /api/pause        {"paused": true|false}  (false = 퀀트 트레이딩 시작)
  POST /api/logout       이 기기에서 로그아웃 (서버의 매매는 계속)
  POST /api/disconnect   서버에서 내 API 키·기록 삭제 (매매 중지)
텔레그램 (서버 주인만): tgbot.py 참고
표준 라이브러리만 사용.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from decimal import Decimal as D
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from statistics import mean

import kbtc_bot as bot
import trade
import users

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
CACHE: dict = {}


# ───────────────────────── 공용 시세 (10초) ─────────────────────────
def collect(ex, symbol):
    slow_at = 0.0
    while True:
        try:
            g = lambda path, p=None: ex.req("GET", path, p)
            btc = g("/fapi/v1/ticker/24hr", {"symbol": symbol})
            eth = g("/fapi/v1/ticker/24hr", {"symbol": "ETHUSDT"})
            prem = g("/fapi/v1/premiumIndex", {"symbol": symbol})
            c = dict(btc=float(btc["lastPrice"]), btc_chg=float(btc["priceChangePercent"]),
                     eth=float(eth["lastPrice"]), eth_chg=float(eth["priceChangePercent"]),
                     mark=float(prem["markPrice"]), funding=float(prem["lastFundingRate"]))
            if time.time() - slow_at > 60:
                now = ex.sync()
                daily = [b for b in g("/fapi/v1/klines", {"symbol": symbol, "interval": "1d", "limit": 100}) if b[6] < now]
                CACHE["daily"] = [float(b[4]) for b in daily]
                CACHE["close_time"] = daily[-1][6]
                CACHE["eth_1h"] = [float(b[4]) for b in g("/fapi/v1/klines", {"symbol": "ETHUSDT", "interval": "1h", "limit": 48})]
                CACHE["ndx"] = nasdaq() or CACHE.get("ndx")
                slow_at = time.time()
            CACHE.update(c, at=time.time(), err=None)
        except Exception as e:
            CACHE["err"] = str(e)
        time.sleep(10)


def nasdaq():
    try:
        req = urllib.request.Request("https://query1.finance.yahoo.com/v8/finance/chart/%5EIXIC?range=1d&interval=5m",
                                     headers={"User-Agent": "Mozilla/5.0"})
        res = json.loads(urllib.request.urlopen(req, timeout=10).read())["chart"]["result"][0]
        m = res["meta"]; price = m["regularMarketPrice"]; prev = m.get("chartPreviousClose") or m.get("previousClose")
        return dict(price=price, chg=(price / prev - 1) * 100 if prev else None,
                    closes=[x for x in res["indicators"]["quote"][0]["close"] if x],
                    live=time.time() - m.get("regularMarketTime", 0) < 900)
    except Exception:
        return None


# ───────────────────────── 내 계좌 (사용자별 8초 캐시) ─────────────────────────
def account_of(ctx):
    if ctx.acct_cache and time.time() - ctx.acct_at < 8:
        return ctx.acct_cache
    pos = ctx.ex.pos_info()
    acct = ctx.ex.account()
    ctx.acct_cache = dict(
        pos=dict(amt=float(pos["positionAmt"]), entry=float(pos["entryPrice"]), mark=float(pos["markPrice"]),
                 upnl=float(pos["unRealizedProfit"]), liq=float(pos["liquidationPrice"]), lev=int(pos["leverage"]),
                 mode="Cross" if pos["marginType"].lower().startswith("cross") else "Isolated",
                 notional=abs(float(pos["notional"]))),
        acct=dict(equity=float(acct["totalMarginBalance"]), wallet=float(acct["totalWalletBalance"]),
                  upnl=float(acct["totalUnrealizedProfit"]), avail=float(acct["availableBalance"]),
                  used=float(acct["totalInitialMargin"]), maint=float(acct["totalMaintMargin"])))
    ctx.acct_at = time.time()
    return ctx.acct_cache


# ───────────────────────── 브리핑 문구 (에겐/테토) ─────────────────────────
def briefing(ctx, amt):
    cfg, st = ctx.cfg, ctx.st
    cl = CACHE.get("daily") or []
    if len(cl) < 50:
        return dict(kind="wait", title="데이터 받는 중…", lines=[])
    last, sma = cl[-1], mean(cl[-50:])
    gap = (last / sma - 1) * 100
    sig = 1 if last > sma else -1
    name = {1: "롱", -1: "숏"}
    teto = cfg["persona"] == "테토"
    e = st.get("last_entry")
    if e and time.time() - e["at"] < 1800:
        up = e["target"] > 0; side = name[e["target"]]
        size = f"{e['weight']:g}% x {e['lev']}배 = {e['notional']:,.0f} USDT ({e['size']} BTC)"
        if teto:
            return dict(kind="long" if up else "short", title=f"{side} 진입. 간다.",
                        lines=[f"{e['date']} 종가 {e['last']:,.0f}, 50일선 대비 {e['gap']:+.1f}%",
                               f"{'상승' if up else '하락'} 추세 확정. 망설임 없다" + (" (기존 포지션 정리 완료)" if e["flipped"] else ""),
                               size + " 박았다"], signal=sig, gap=gap)
        return dict(kind="long" if up else "short", title=f"{side} 들어갔어요! ♪",
                    lines=[f"{e['date']} 종가 {e['last']:,.0f}가 50일선보다 {abs(e['gap']):.1f}% {'위' if up else '아래'}예요",
                           f"{'올라가는' if up else '내려가는'} 추세라고 판단했어요" + (" (기존 건 정리했어요)" if e["flipped"] else ""),
                           size], signal=sig, gap=gap)
    hold = (amt > 0) - (amt < 0)
    left = max(0, (CACHE.get("close_time", 0) + 86_400_000 - time.time() * 1000) / 1000)
    when = f"{int(left // 3600)}시간 {int(left % 3600 // 60)}분"
    state = ("off" if st.get("paused") and not st.get("started") and not ctx.owner else
             "paused" if st.get("paused") else "hold" if hold == sig else "wait9")
    contra = (CACHE.get("btc", last) > sma) != (sig > 0)
    if teto:
        title, why = {"off": ("대기 중. 버튼 눌러.", "[퀀트 트레이딩 시작] 누르면 바로 간다"),
                      "paused": ("일시정지. 대기한다.", "시작 누르기 전엔 안 움직인다"),
                      "hold": (f"{name[sig]} 홀딩. {'상승' if sig > 0 else '하락'} 추세 견고해보임.", "신호 그대로다. 추가 진입 없음"),
                      "wait9": ("9시까지 대기.", "종가 확정 전엔 안 움직인다")}[state]
        lines = [f"신호 {name[sig]}. 종가가 50일선 {abs(gap):.1f}% {'위' if sig > 0 else '아래'}다", why, f"다음 판단 {when} 뒤"]
        if contra:
            lines.append("장중 흔들림? 종가 아니면 무시한다")
    else:
        title, why = {"off": ("출근 대기 중이에요 ☕︎", "[퀀트 트레이딩 시작] 눌러주시면 일할게요!"),
                      "paused": ("잠깐 쉬는 중이에요 ☕︎", "[퀀트 트레이딩 시작] 눌러주시면 다시 일할게요!"),
                      "hold": (f"{name[sig]} 꼭 쥐고 있어요 ♡", "신호 그대로라 더 들어가진 않을게요"),
                      "wait9": ("아침 9시를 기다려요 ☾", "종가 확정되면 그때 들어갈게요")}[state]
        lines = [f"신호는 {name[sig]}! 어제 종가가 50일선보다 {abs(gap):.1f}% {'위' if sig > 0 else '아래'}예요", why,
                 f"다음 판단까지 {when} 남았어요"]
        if contra:
            lines.append("지금 가격은 반대쪽인데… 종가가 아니라 무시할게요")
    return dict(kind="wait", title=title, lines=lines, signal=sig, gap=gap)


def snapshot(ctx):
    try:
        mine, err = account_of(ctx), None
    except Exception as e:
        mine, err = {}, str(e)
    st = ctx.st
    return dict(CACHE, **mine, acct_err=err, briefing=briefing(ctx, mine.get("pos", {}).get("amt", 0)),
                paused=bool(st.get("paused")), owner=ctx.owner, key_hint=ctx.cfg["key"][:6] + "…" + ctx.cfg["key"][-4:],
                exchange=ctx.cfg.get("exchange", "binance"), exchange_name=ctx.ex.NAME,
                events=list(reversed(st.get("events", [])[-20:])),
                settings=dict(weight=float(ctx.cfg["weight"]), leverage=ctx.cfg["leverage"], persona=ctx.cfg["persona"],
                              mode=ctx.cfg["mode"], symbol=ctx.cfg["symbol"], max_lev=bot.MAX_LEV,
                              tp_pct=ctx.cfg.get("tp_pct", 0), sl_pct=ctx.cfg.get("sl_pct", 0)),
                tpsl=trade.current_tpsl(ctx), realized=trade._cache.get((ctx.uid, "realized"), (0, None))[1], now=time.time())


# ───────────────────────── 설정 변경 (웹·텔레그램 공용) ─────────────────────────
def change(ctx, weight=None, leverage=None, persona=None, via="앱"):
    cfg, st = ctx.cfg, ctx.st
    o = st.setdefault("overrides", {})
    msgs = []
    if weight is not None:
        w = D(str(weight))
        if not 0 < w <= 100:
            raise ValueError("비중은 0 초과 100 이하")
        cfg["weight"] = w; o["weight"] = float(w); msgs.append(f"비중 {w}%")
    if leverage is not None:
        lev = int(leverage)
        if not 1 <= lev <= bot.MAX_LEV:
            raise ValueError(f"배율은 1~{bot.MAX_LEV}배까지만 가능해요")
        lev = ctx.ex.set_leverage(lev)  # 즉시 거래소에도 적용
        cfg["leverage"] = lev; o["leverage"] = lev; msgs.append(f"배율 {lev}x")
    if persona is not None:
        if persona not in ("에겐", "테토"):
            raise ValueError("말투는 에겐/테토")
        cfg["persona"] = persona; o["persona"] = persona; msgs.append(f"말투 {persona}")
    if msgs:
        ctx.tg.send(f"[KBTC] 설정 변경({via}) · " + " · ".join(msgs))
        ctx.acct_at = 0
        bot.save_state(st)


def pause(ctx, paused, via="앱"):
    st = ctx.st
    st["paused"] = bool(paused)
    if not paused:
        if not st.get("last_day") and CACHE.get("close_time"):
            st["last_day"] = CACHE["close_time"]  # 시작은 다음 09:00 일봉 마감부터 (앱과 동일)
        st["started"] = True
    ctx.tg.send(f"[KBTC] {'중지' if paused else '퀀트 트레이딩 시작'}({via}) · " +
                ("새 매매를 멈춥니다. 열린 포지션은 그대로예요." if paused else "매일 09:00 일봉 마감 직후 판단해서 매매합니다."))
    bot.save_state(st)


# ───────────────────────── 웹 서버 ─────────────────────────
def make_handler(store):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def me(self):
            for p in self.headers.get("Cookie", "").split(";"):
                k, _, v = p.strip().partition("=")
                if k == "kbtc_s":
                    uid = users.verify(v)
                    return store.get(uid) if uid else None
            return None

        def send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False)
            if isinstance(body, str):
                body = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/api/state":
                ctx = self.me()
                return self.send(200, snapshot(ctx)) if ctx else self.send(401, {"error": "login"})
            if path == "/api/history":
                ctx = self.me()
                if not ctx:
                    return self.send(401, {"error": "login"})
                kind = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("kind", ["orders"])[0]
                fn = {"orders": trade.orders, "positions": trade.positions, "calendar": trade.calendar, "equity": trade.equity,
                      "realized": trade.realized_now, "funding": trade.funding, "snaps": trade.snaps}.get(kind)
                if not fn:
                    return self.send(404, {"error": "kind"})
                try:
                    return self.send(200, {"kind": kind, "data": fn(ctx)})
                except Exception as e:
                    return self.send(400, {"error": str(e)})
            if path == "/healthz":
                return self.send(200, {"ok": True, "users": len(store.all())})
            files = {"/": ("index.html", "text/html; charset=utf-8"), "/manifest.json": ("manifest.json", "application/manifest+json"),
                     "/logo.png": ("logo.png", "image/png"), "/icon.png": ("icon.png", "image/png"),
                     "/backtest.json": ("backtest_btc_w30.json", "application/json; charset=utf-8"), "/backtest.png": ("backtest.png", "image/png")}
            if path in files:
                name, ctype = files[path]
                with open(os.path.join(STATIC, name), "rb") as f:
                    return self.send(200, f.read(), ctype)
            self.send(404, {"error": "not found"})

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            n = int(self.headers.get("Content-Length") or 0)
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self.send(400, {"error": "bad json"})
            if path == "/api/connect":
                try:
                    ctx = store.connect(str(data.get("key", "")), str(data.get("secret", "")),
                                        str(data.get("exchange") or "binance").lower(), str(data.get("passphrase", "")))
                except Exception as e:
                    time.sleep(1)
                    return self.send(400, {"error": str(e)})
                return self.send(200, snapshot(ctx), extra={
                    "Set-Cookie": f"kbtc_s={users.sign(ctx.uid)}; Max-Age=7776000; Path=/; HttpOnly; Secure; SameSite=Strict"})
            ctx = self.me()
            if not ctx:
                return self.send(401, {"error": "login"})
            clear = {"Set-Cookie": "kbtc_s=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Strict"}
            try:
                if path == "/api/settings":
                    change(ctx, data.get("weight"), data.get("leverage"), data.get("persona"))
                elif path == "/api/pause":
                    pause(ctx, data.get("paused"))
                elif path == "/api/close":
                    r = trade.close_position(ctx, data.get("ratio", 1))
                    ctx.acct_at = 0
                    ctx.tg.send(f"[KBTC] 수동 {'Close all' if r['all'] else 'Close'}(앱) · {r['side']} {r['qty']} BTC @ {r['price']:,.1f}")
                    if data.get("pause"):
                        pause(ctx, True)
                elif path == "/api/tpsl" and ("tp_price" in data or "sl_price" in data):
                    placed = trade.set_tpsl_price(ctx, data.get("tp_price"), data.get("sl_price"), data.get("auto", True), data.get("ratio", 1))
                    bot.save_state(ctx.st)
                    ctx.tg.send("[KBTC] TP/SL 설정(앱) · " + (" · ".join(f"{'TP' if k.startswith('TAKE') else 'SL'} {p:,.1f}" for k, p in placed) or "해제"))
                elif path == "/api/tpsl":
                    placed = trade.set_tpsl(ctx, data.get("tp"), data.get("sl"))
                    bot.save_state(ctx.st)
                    ctx.tg.send("[KBTC] TP/SL 저장(앱) · " + (f"익절 {ctx.cfg['tp_pct']:g}% / 손절 {ctx.cfg['sl_pct']:g}%"
                                + ("".join(f" · {'익절' if k.startswith('TAKE') else '손절'} {p:,.1f}" for k, p in placed))))
                elif path == "/api/logout":
                    return self.send(200, {"ok": True}, extra=clear)
                elif path == "/api/disconnect":
                    store.remove(ctx.uid)
                    return self.send(200, {"ok": True}, extra=clear)
                else:
                    return self.send(404, {"error": "not found"})
            except Exception as e:
                return self.send(400, {"error": str(e)})
            self.send(200, snapshot(ctx))

    return H


def start(store):
    owner = store.get(store.owner_uid)
    threading.Thread(target=collect, args=(bot.Futures(owner.cfg), owner.cfg["symbol"]), daemon=True).start()
    import tgbot
    threading.Thread(target=tgbot.loop, args=(store,), daemon=True).start()
    port = int(os.getenv("PORT", "8080"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), make_handler(store))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    bot.log(f"앱 서버 대기 중 · 포트 {port} · 사용자 {len(store.all())}명")
