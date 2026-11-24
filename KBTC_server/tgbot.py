"""KBTC 텔레그램 봇 (서버 주인 전용).

- 시작 시 명령 메뉴·소개 문구를 텔레그램에 등록 (/ 누르면 메뉴가 뜸)
- /start, /help: 사용법 안내 + 버튼 패널
- 버튼(인라인 키보드)으로 상태·신호·포지션·설정·중지/시작·백테스트
- 명령: /status /signal /position /settings /pause /resume /weight 20 /lev 5 /persona 테토 /backtest /app /users
TELEGRAM_CHAT_ID 가 비어 있으면 /start 보낸 채팅의 ID 를 알려준다. 다른 채팅은 무시.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

import kbtc_bot as bot
import web

# 앱 주소: APP_URL 변수 > Railway 공개 도메인 자동 감지 > 없음
APP_URL = os.getenv("APP_URL") or ("https://" + os.environ["RAILWAY_PUBLIC_DOMAIN"] if os.getenv("RAILWAY_PUBLIC_DOMAIN") else "")

COMMANDS = [
    ("status", "📊 지금 상황 한눈에"),
    ("signal", "📈 오늘 신호와 근거"),
    ("position", "💼 내 포지션·계좌"),
    ("settings", "⚙️ 비중·배율·말투 보기/변경"),
    ("pause", "⏸ 퀀트 트레이딩 중지"),
    ("resume", "▶️ 퀀트 트레이딩 시작"),
    ("backtest", "📉 배율별 백테스트 요약"),
    ("app", "📱 앱(대시보드) 열기"),
    ("help", "❓ 사용법"),
]

DESCRIPTION = ("KBTC · Korea Bitcoin 퀀트 트레이딩 봇\n\n"
               "BTC 무기한 선물을 50일 이동평균 추세로 자동 매매하고, 진입·청산·매일 아침 브리핑을 알려줘요.\n\n"
               "아래 [시작]을 누르면 사용법이 나와요.")
SHORT = "BTC 50일선 추세 자동매매 · 진입/청산 알림 · 매일 09:00 브리핑"

HELP = """🇰🇷 KBTC 사용법

이 봇은 서버에서 24시간 돌아가는 자동매매를 알려주고 조종하는 리모컨이에요. 맥북을 꺼도 매매는 계속돼요.

🧠 전략 (Lv.1 50일 추세)
• 매일 09:00(한국) 일봉이 마감되면 한 번 판단해요.
• 종가가 50일 평균보다 위 → 롱, 아래 → 숏.
• 신호가 바뀔 때만 기존 포지션을 정리하고 반대로 들어가요.
• 진입 규모 = 사용 가능 USDT × 비중% × 배율

🔔 자동으로 오는 알림
• 진입·청산 체결 (가격·수량·근거)
• 매일 09:00 보유 브리핑 (신호·총자산)
• 설정 변경, 오류

⌨️ 명령어 (왼쪽 아래 / 메뉴에도 있어요)
/status  지금 상황 한눈에
/signal  오늘 신호와 근거
/position  포지션·계좌
/settings  비중·배율·말투
/pause · /resume  중지 · 시작
/weight 20  비중 20%로
/lev 5  배율 5배로
/persona 테토  말투 (에겐/테토)
/backtest  배율별 백테스트
/app  앱 열기

💡 추천: 비중 30%면 배율 3~5배. (10배 이상은 과거에 계좌가 -95% 넘게 빠졌어요)"""


def _api(token, method, payload=None, timeout=15):
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=data,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def panel(ctx):
    paused = ctx.st.get("paused")
    return {"inline_keyboard": [
        [{"text": "📊 상태", "callback_data": "status"}, {"text": "📈 신호", "callback_data": "signal"},
         {"text": "💼 포지션", "callback_data": "position"}],
        [{"text": "▶️ 퀀트 트레이딩 시작" if paused else "⏸ 중지", "callback_data": "resume" if paused else "pause"},
         {"text": "⚙️ 설정", "callback_data": "settings"}],
        [{"text": "📉 백테스트", "callback_data": "backtest"}] + ([{"text": "📱 앱 열기", "url": APP_URL}] if APP_URL else []),
    ]}


def settings_kb(ctx):
    w, lev, p = float(ctx.cfg["weight"]), ctx.cfg["leverage"], ctx.cfg["persona"]
    mark = lambda ok, t: ("✅ " if ok else "") + t
    return {"inline_keyboard": [
        [{"text": mark(w == v, f"비중 {v:g}%"), "callback_data": f"w:{v:g}"} for v in (10, 20, 30, 50)],
        [{"text": mark(lev == v, f"{v}배"), "callback_data": f"l:{v}"} for v in (1, 3, 5, 10)],
        [{"text": mark(p == v, v), "callback_data": f"p:{v}"} for v in ("에겐", "테토")],
        [{"text": "← 메뉴", "callback_data": "menu"}],
    ]}


def _money(v):
    return f"{v:,.2f}"


def text_status(ctx):
    s = web.snapshot(ctx)
    b, p, a = s["briefing"], s.get("pos", {}), s.get("acct", {})
    amt = p.get("amt", 0)
    side = "🟢 롱" if amt > 0 else "🔴 숏" if amt < 0 else "⚪ 없음"
    sig = b.get("signal")
    lines = [f"📊 KBTC 상황  ({time.strftime('%m/%d %H:%M')})", "",
             f"💬 {b['title']}", *[f"   {x}" for x in b["lines"]], "",
             f"BTC  {s.get('btc', 0):,.1f}  ({s.get('btc_chg', 0):+.2f}%)",
             f"신호  {'롱' if sig == 1 else '숏' if sig == -1 else '—'}  (50일선 대비 {b.get('gap', 0):+.1f}%)",
             f"포지션  {side}" + (f" {abs(amt)} BTC  ·  미실현 {p.get('upnl', 0):+,.2f}" if amt else ""),
             f"총자산  {_money(a.get('equity', 0))} USDT",
             f"설정  비중 {ctx.cfg['weight']}% · {ctx.cfg['leverage']}배 · {ctx.cfg['persona']}",
             f"상태  {'⏸ 중지됨' if ctx.st.get('paused') else '▶️ 자동매매 중'}"]
    return "\n".join(lines)


def text_signal(ctx):
    cl = web.CACHE.get("daily") or []
    if len(cl) < 50:
        return "데이터를 받는 중이에요. 잠시 후 다시 눌러 주세요."
    last, sma = cl[-1], sum(cl[-50:]) / 50
    gap = (last / sma - 1) * 100
    sig = "롱 🟢" if last > sma else "숏 🔴"
    left = max(0, (web.CACHE.get("close_time", 0) + 86_400_000 - time.time() * 1000) / 1000)
    now = web.CACHE.get("btc", last)
    return (f"📈 오늘 신호: {sig}\n\n"
            f"• 어제 확정 종가  {last:,.1f}\n"
            f"• 50일 평균      {sma:,.1f}\n"
            f"• 차이            {gap:+.2f}%\n"
            f"• 지금 가격       {now:,.1f}  (50일선 대비 {(now / sma - 1) * 100:+.2f}%)\n\n"
            f"⏰ 다음 판단: 09:00 일봉 마감 ({int(left // 3600)}시간 {int(left % 3600 // 60)}분 뒤)\n"
            f"장중 가격은 무시하고, 종가로만 판단해요.")


def text_position(ctx):
    s = web.snapshot(ctx)
    p, a = s.get("pos", {}), s.get("acct", {})
    if s.get("acct_err"):
        return f"⚠️ 계좌 조회 실패: {s['acct_err']}"
    amt = p.get("amt", 0)
    out = ["💼 포지션 · 계좌", ""]
    if amt:
        margin = abs(amt) * p["entry"] / p["lev"] if p["lev"] else 0
        roe = p["upnl"] / margin * 100 if margin else 0
        out += [f"{'🟢 Long' if amt > 0 else '🔴 Short'}  {abs(amt)} BTC  ·  {p['mode']} {p['lev']}x",
                f"진입가  {p['entry']:,.1f}",
                f"시장가  {p['mark']:,.1f}",
                f"청산가  {p['liq']:,.1f}" if p.get("liq") else "청산가  —",
                f"미실현  {p['upnl']:+,.2f} USDT ({roe:+.2f}%)", ""]
    else:
        out += ["포지션 없음", ""]
    out += [f"총자산      {_money(a.get('equity', 0))} USDT",
            f"지갑 잔고   {_money(a.get('wallet', 0))} USDT",
            f"사용 가능   {_money(a.get('avail', 0))} USDT",
            f"사용 증거금 {_money(a.get('used', 0))} USDT"]
    return "\n".join(out)


def text_settings(ctx):
    w, lev = float(ctx.cfg["weight"]), ctx.cfg["leverage"]
    return (f"⚙️ 설정\n\n비중  {w:g}%\n배율  {lev}배  (실노출 {w * lev / 100:.1f}배)\n말투  {ctx.cfg['persona']}\n\n"
            f"아래 버튼으로 바로 바꿀 수 있어요. 다른 값은 /weight 25, /lev 4 처럼 입력하세요.\n"
            f"비중·배율은 다음 진입부터 적용돼요 (배율은 거래소에도 즉시 반영).")


def text_backtest(ctx):
    try:
        d = json.load(open(os.path.join(web.STATIC, "backtest_btc_w30.json"), encoding="utf-8"))
    except Exception:
        return "백테스트 데이터가 없어요."
    cur = ctx.cfg["leverage"]
    pc = lambda v: f"{v * 100:+.2f}%" if v <= -0.99 else f"{v * 100:+.1f}%"
    rows = [f"{'👉' if r['lev'] == cur else '  '} {r['lev']:>2}배  {r['usdt']:>9,.0f}  낙폭 {pc(r['mdd'])}  {r['verdict'].replace('공격 · ', '')}"
            for r in d["rows"]]
    return (f"📉 배율별 백테스트 · BTC · 비중 30%\n{d['start']} ~ {d['end']} · 시작 {d['capital']:,} USDT · 전체 계좌 기준\n\n"
            + "\n".join(rows) +
            f"\n\nBTC 그냥 보유: {d['hold']:.1f}배\n💡 추천: 배율 3~5배. 과거 결과일 뿐 미래를 보장하지 않아요.\n자세한 표·차트는 📱 앱에서 볼 수 있어요.")


def setup(token):
    """명령 메뉴·소개 문구 등록 (한 번 해두면 텔레그램에 남는다)."""
    try:
        _api(token, "setMyCommands", {"commands": [{"command": c, "description": d} for c, d in COMMANDS]})
        _api(token, "setMyDescription", {"description": DESCRIPTION})
        _api(token, "setMyShortDescription", {"short_description": SHORT})
        _api(token, "setChatMenuButton", {"menu_button": {"type": "commands"}})
    except Exception as e:
        bot.log(f"텔레그램 메뉴 등록 실패: {e}")


def loop(store):
    ctx = store.get(store.owner_uid)
    tg = ctx.tg
    if not tg.token:
        return
    setup(tg.token)
    offset = 0
    while True:
        try:
            res = _api(tg.token, "getUpdates", {"timeout": 50, "offset": offset,
                                                "allowed_updates": ["message", "callback_query"]}, timeout=60)
            for u in res.get("result", []):
                offset = u["update_id"] + 1
                try:
                    handle(store, ctx, tg, u)
                except Exception as e:
                    bot.log(f"텔레그램 처리 오류: {e}")
        except Exception as e:
            bot.log(f"텔레그램 수신 오류: {e}")
            time.sleep(10)


def handle(store, ctx, tg, u):
    cq = u.get("callback_query")
    msg = (cq or {}).get("message") or u.get("message") or {}
    chat = str(msg.get("chat", {}).get("id", ""))
    send = lambda text, kb=None: _api(tg.token, "sendMessage", {"chat_id": chat, "text": text, **({"reply_markup": kb} if kb else {})})
    if not tg.chat:
        bot.log(f"텔레그램 chat id = {chat} (TELEGRAM_CHAT_ID 로 설정하세요)")
        send(f"이 채팅의 ID는 {chat} 입니다. 서버 변수 TELEGRAM_CHAT_ID 에 넣어 주세요.")
        return
    if chat != str(tg.chat):
        return  # 주인 채팅 외에는 무시
    if cq:
        _api(tg.token, "answerCallbackQuery", {"callback_query_id": cq["id"]})
        cmd, args = cq.get("data", ""), []
        if ":" in cmd:  # 설정 버튼
            k, v = cmd.split(":", 1)
            try:
                web.change(ctx, **{{"w": "weight", "l": "leverage", "p": "persona"}[k]: v}, via="텔레그램")
            except Exception as e:
                send(f"실패: {e}")
            _api(tg.token, "editMessageText", {"chat_id": chat, "message_id": msg["message_id"],
                                               "text": text_settings(ctx), "reply_markup": settings_kb(ctx)})
            return
        cmd = "/" + cmd
    else:
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            send("버튼이나 명령어로 말해 주세요 👇", panel(ctx))
            return
        cmd, *args = text.split()
        cmd = cmd.split("@")[0].lower()
    try:
        if cmd in ("/start", "/help", "/menu"):
            send(HELP if cmd != "/menu" else "무엇을 볼까요?", panel(ctx))
        elif cmd == "/status":
            send(text_status(ctx), panel(ctx))
        elif cmd == "/signal":
            send(text_signal(ctx), panel(ctx))
        elif cmd == "/position":
            send(text_position(ctx), panel(ctx))
        elif cmd == "/settings":
            send(text_settings(ctx), settings_kb(ctx))
        elif cmd == "/pause":
            web.pause(ctx, True, "텔레그램")
            send("⏸ 퀀트 트레이딩을 멈췄어요. 열린 포지션은 그대로예요.", panel(ctx))
        elif cmd == "/resume":
            web.pause(ctx, False, "텔레그램")
            send("▶️ 퀀트 트레이딩 시작! 매일 09:00 일봉 마감 직후 판단해요.", panel(ctx))
        elif cmd == "/weight" and args:
            web.change(ctx, weight=args[0].rstrip("%"), via="텔레그램")
        elif cmd == "/lev" and args:
            web.change(ctx, leverage=args[0].rstrip("xX배"), via="텔레그램")
        elif cmd == "/persona" and args:
            web.change(ctx, persona=args[0], via="텔레그램")
        elif cmd == "/backtest":
            send(text_backtest(ctx), panel(ctx))
        elif cmd == "/app" and not APP_URL:
            send("앱 주소가 설정되지 않았어요. 서버 변수 APP_URL 에 대시보드 주소를 넣어 주세요.")
        elif cmd == "/app":
            send(f"📱 KBTC 앱: {APP_URL}\n폰에서 열고 '홈 화면에 추가'하면 앱처럼 쓸 수 있어요.",
                 {"inline_keyboard": [[{"text": "📱 앱 열기", "url": APP_URL}]]})
        elif cmd == "/users":
            n = len(store.all()) - 1
            on = sum(1 for c in store.all() if not c.owner and not c.st.get("paused"))
            send(f"👥 앱 사용자 {n}명 · 자동매매 중 {on}명")
        else:
            send("모르는 명령이에요. /help 를 눌러 보세요.", panel(ctx))
    except Exception as e:
        send(f"⚠️ 실패: {e}")
