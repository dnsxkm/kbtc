"""BTCUSDT USD-M futures desk. Run with python futures_app.py."""
import time
import os
import tkinter as tk
from decimal import Decimal as D
from statistics import mean
from tkinter import ttk, messagebox
from uuid import uuid4

from quant_floor.binance import BinanceClient
from quant_floor.notify import Notifier

SYMBOL = "BTCUSDT"
LEVELS = ("Lv.1  50일 추세",)


def direction(closes, level, current):
    """Lv.1: last confirmed daily close vs 50-day average."""
    if len(closes) < 60:
        raise ValueError("확정 일봉 60개 필요")
    fast, slow = closes[-1], mean(closes[-50:])
    return 1 if fast > slow else -1 if fast < slow else current


class Exchange(BinanceClient):
    def __init__(self, demo, key, secret):
        super().__init__(key, secret)
        self.base_url = "https://demo-fapi.binance.com" if demo else "https://fapi.binance.com"

    def get(self, route, params=None, private=False):
        return self._request("GET", "/fapi/" + route, params, signed=private)

    def position(self):
        rows = self.get("v3/positionRisk", {"symbol": SYMBOL}, True)
        if any(r["positionSide"] != "BOTH" for r in rows):
            raise ValueError("단방향 포지션 모드가 필요합니다.")
        return sum((D(r["positionAmt"]) for r in rows), D(0))

    def leverage(self):
        rows = self.get("v2/positionRisk", {"symbol": SYMBOL}, True)
        return D(rows[0]["leverage"])

    def set_leverage(self, lev):
        data = self._request("POST", "/fapi/v1/leverage", {"symbol": SYMBOL, "leverage": lev}, signed=True)
        return int(data["leverage"])

    def snapshot(self):
        pos = self.get("v2/positionRisk", {"symbol": SYMBOL}, True)[0]
        return pos, self.get("v3/account", private=True)

    def usdt_available(self):
        rows = self.get("v3/balance", private=True)
        return next((D(b["availableBalance"]) for b in rows if b["asset"] == "USDT"), D(0))

    def order(self, delta, closing):
        data = self._request("POST", "/fapi/v1/order", {
            "symbol": SYMBOL, "side": "BUY" if delta > 0 else "SELL",
            "type": "MARKET", "quantity": format(abs(delta), "f"),
            "reduceOnly": "true" if closing else "false",
            "newClientOrderId": "qfloor-" + uuid4().hex[:26], "newOrderRespType": "RESULT",
        }, signed=True)
        if data["status"] != "FILLED" or D(data["executedQty"]) != abs(delta):
            raise ValueError("주문 상태를 바이낸스에서 확인하세요.")
        return data


class Desk:
    def __init__(self, root):
        self.root = root
        root.title("KBTC")
        root.configure(bg="#0e202d")
        root.geometry("810x650")
        self.client = None
        self.running = False
        self.expected = D(0)
        self.last_day = None
        self.job = None
        self.refresh_job = None
        self.refresh_err = None
        self.market_err = None
        self.market_job = None
        self.closes = None
        self.closes_at = 0
        self.last_close_time = None
        self.entry_bubble = None
        self.ndx, self.ndx_at, self.ndx_busy = None, 0, False
        self.eth_1h, self.majors = [], []
        self.toggle_api = lambda show=None: None
        self.notifier = Notifier(os.getenv("TELEGRAM_BOT_TOKEN",""), os.getenv("TELEGRAM_CHAT_ID",""))
        self.mode = tk.StringVar(value="Demo")
        self.level = tk.StringVar(value=LEVELS[0])
        self.persona = tk.StringVar(value="에겐")
        self.state = tk.StringVar(value="계좌 연결 대기")
        self.metrics = tk.StringVar(value="최근 24시간   —")
        from quant_floor.floor_view import build
        build(self, LEVELS)
        self.persona.trace_add("write", lambda *_: self.closes and self.update_bubble(self.last_price, force=True))
        self.last_price = None
        self.market()

    def fetch_ndx(self):
        """나스닥 종합지수(^IXIC)를 별도 스레드에서 받아온다 (Yahoo Finance 공개 차트)."""
        import json, urllib.request
        try:
            req=urllib.request.Request("https://query1.finance.yahoo.com/v8/finance/chart/%5EIXIC?range=1d&interval=5m",
                                       headers={"User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req,timeout=10) as r:
                res=json.loads(r.read())["chart"]["result"][0]
            m=res["meta"]; price=m["regularMarketPrice"]; prev=m.get("chartPreviousClose") or m.get("previousClose")
            closes=[c for c in res["indicators"]["quote"][0]["close"] if c]
            self.ndx=dict(price=price,chg=(price/prev-1)*100 if prev else None,closes=closes,
                          live=time.time()-m.get("regularMarketTime",0)<900)
        except Exception:
            pass
        finally:
            self.ndx_busy=False

    def market(self):
        """5초마다 시세/본부 모니터/말풍선 갱신. 계좌 연결 없이도 동작."""
        import threading
        if self.market_job is not None:
            self.root.after_cancel(self.market_job)
        self.market_job=None
        try:
            from quant_floor.floor_view import show_price
            c=self.client or Exchange(self.mode.get()=="Demo","","")
            t=c.get("v1/ticker/24hr",{"symbol":SYMBOL})
            eth=c.get("v1/ticker/24hr",{"symbol":"ETHUSDT"})
            prem=c.get("v1/premiumIndex",{"symbol":SYMBOL})
            mark=D(prem["markPrice"])
            price=D(t["lastPrice"])
            self.last_price=price
            show_price(self,price,D(t["priceChangePercent"]),mark)
            if self.closes is None or time.time()-self.closes_at>60:
                now=int(c.get("v1/time")["serverTime"])
                bars=c.get("v1/klines",{"symbol":SYMBOL,"interval":"1d","limit":100})
                closed=[b for b in bars if b[6]<now]
                self.closes=[D(b[4]) for b in closed]
                self.last_close_time=closed[-1][6]
                self.eth_1h=[float(b[4]) for b in c.get("v1/klines",{"symbol":"ETHUSDT","interval":"1h","limit":48})]
                majors={r["symbol"]:r for r in c.get("v1/ticker/24hr") if r["symbol"] in ("SOLUSDT","XRPUSDT","BNBUSDT","DOGEUSDT")}
                self.majors=[(k[:-4],float(majors[k]["lastPrice"]),float(majors[k]["priceChangePercent"])) for k in ("SOLUSDT","XRPUSDT","BNBUSDT","DOGEUSDT") if k in majors]
                self.closes_at=time.time()
            if not self.ndx_busy and time.time()-self.ndx_at>60:
                self.ndx_busy=True; self.ndx_at=time.time()
                threading.Thread(target=self.fetch_ndx,daemon=True).start()
            sma=mean(self.closes[-50:])
            left=max(0,(self.last_close_time+86400000-time.time()*1000)/1000)
            nf=max(0,(int(prem["nextFundingTime"])-time.time()*1000)/1000)
            ec=float(eth["priceChangePercent"]); bc=float(t["priceChangePercent"])
            tape=[f"BTC {float(price):,.1f} {bc:+.2f}%", f"ETH {float(eth['lastPrice']):,.2f} {ec:+.2f}%"]
            if self.ndx:
                tape.append(f"NASDAQ {self.ndx['price']:,.0f} {self.ndx['chg']:+.2f}%")
            tape+=[f"{n} {p:,.4g} {ch:+.2f}%" for n,p,ch in self.majors]
            tape.append(f"FUNDING {float(prem['lastFundingRate'])*100:+.4f}%  ({int(nf//3600)}h{int(nf%3600//60):02d}m)")
            self.floor.data=dict(btc=float(price),btc_chg=bc,eth=float(eth["lastPrice"]),eth_chg=ec,
                                 btc_daily=[float(x) for x in self.closes],eth_1h=self.eth_1h,ndx=self.ndx,
                                 signal=1 if self.closes[-1]>sma else -1,gap=float((self.closes[-1]/sma-1)*100),
                                 next=f"{int(left//3600)}h {int(left%3600//60)}m",funding=float(prem["lastFundingRate"]),
                                 mark=float(mark),tape=tape)
            if not self.running or self.floor.signals[0]=="대기":
                self.floor.signals=[{1:"롱",-1:"숏"}[self.floor.data["signal"]]]
            self.floor.paint()
            self.update_bubble(price)
            self.market_err=None
        except Exception as e:
            msg=f"시세 조회 실패 · {e}"
            if msg!=self.market_err:
                self.note(msg)
            self.market_err=msg
        self.market_job=self.root.after(5000,self.market)

    def update_bubble(self,price,force=False):
        """말풍선 문구를 만든다. 말투: 에겐(다정·귀여움) / 테토(직설·자신감)."""
        closes=self.closes
        last,sma=closes[-1],mean(closes[-50:])
        gap=(last/sma-1)*100
        sig=1 if last>sma else -1
        name={1:"롱",-1:"숏"}
        teto=self.persona.get()=="테토"
        if not self.running or self.floor.signals[0]=="대기":
            self.floor.signals=[name[sig]]
        fresh=bool(self.entry_bubble) and time.time()-self.entry_bubble[0]<1800
        if fresh:
            e=self.entry_bubble[1]
            side=name[e["target"]]; up=e["target"]>0
            kind="long" if up else "short"
            size_line=f"{e['weight']}% × {e['lev']}배 = {e['notional']:,.0f} USDT ({e['size']} BTC)"
            if teto:
                title=f"{side} 진입. 간다."
                lines=[f"{e['date']} 종가 {e['last']:,.0f}, 50일선 대비 {e['gap']:+.1f}%",
                       f"{'상승' if up else '하락'} 추세 확정. 망설임 없다" + (" (기존 포지션 정리 완료)" if e["flipped"] else ""),
                       size_line+" 박았다"]
            else:
                title=f"{side} 들어갔어요! ♪"
                lines=[f"{e['date']} 종가 {e['last']:,.0f}가 50일선보다 {abs(e['gap']):.1f}% {'위' if up else '아래'}예요",
                       f"{'올라가는' if up else '내려가는'} 추세라고 판단했어요" + (" (기존 건 정리했어요)" if e["flipped"] else ""),
                       size_line]
        else:
            kind="wait"
            hold=int(self.expected>0)-int(self.expected<0)
            left=max(0,(self.last_close_time+86400000-time.time()*1000)/1000)
            when=f"{int(left//3600)}시간 {int(left%3600//60)}분"
            state=("noacct" if not self.client else "off" if not self.running else "hold" if hold==sig else "wait9")
            contra=(price>sma)!=(sig>0)
            if teto:
                title,why={"noacct":("계좌 연결해. 바로.","키 없으면 아무것도 못 한다"),
                           "off":("대기 중. 버튼 눌러.","[퀀트 트레이딩 시작] 누르면 바로 간다"),
                           "hold":(f"{name[sig]} 홀딩. 안 흔들린다.","신호 그대로다. 추가 진입 없음"),
                           "wait9":("9시까지 대기.","종가 확정 전엔 안 움직인다")}[state]
                lines=[f"신호 {name[sig]}. 종가가 50일선 {abs(gap):.1f}% {'위' if sig>0 else '아래'}다", why, f"다음 판단 {when} 뒤"]
                if contra:
                    lines.append("장중 흔들림? 종가 아니면 무시한다")
            else:
                title,why={"noacct":("계좌를 기다리는 중이에요 ♪","계좌부터 연결해 주세요~"),
                           "off":("출근 대기 중이에요 ☕︎","[퀀트 트레이딩 시작] 눌러주시면 일할게요!"),
                           "hold":(f"{name[sig]} 꼭 쥐고 있어요 ♡","신호 그대로라 더 들어가진 않을게요"),
                           "wait9":("아침 9시를 기다려요 ☾","종가 확정되면 그때 들어갈게요")}[state]
                lines=[f"신호는 {name[sig]}! 어제 종가가 50일선보다 {abs(gap):.1f}% {'위' if sig>0 else '아래'}예요", why, f"다음 판단까지 {when} 남았어요"]
                if contra:
                    lines.append("지금 가격은 반대쪽인데… 종가가 아니라 무시할게요")
        old=self.floor.bubble
        self.floor.bubble=(kind,title,lines,"teto" if teto else "egen")
        if force or old is None or old[0]!=kind or old[1]!=title:
            self.floor.show()
        elif not self.floor.typing:
            self.floor.draw_bubble()

    def note(self,s):
        self.log.configure(state="normal")
        self.log.insert("end",time.strftime("%H:%M:%S  ")+s+"\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def refresh(self):
        """5초마다 포지션 카드와 전체 계좌를 갱신한다."""
        if self.refresh_job is not None:
            self.root.after_cancel(self.refresh_job)
        self.refresh_job=None
        if not self.client:
            return
        try:
            from quant_floor.floor_view import show_account
            pos,account=self.client.snapshot()
            show_account(self,pos,account)
            self.refresh_err=None
        except Exception as e:
            msg=f"계좌 조회 실패 · {e}"
            if msg!=self.refresh_err:
                self.note(msg)
            self.refresh_err=msg
        self.refresh_job=self.root.after(5000,self.refresh)

    def read_leverage(self):
        text=self.lev_entry.get().strip().lower().rstrip("x")
        if not text.isdigit() or not 1<=int(text)<=15:
            raise ValueError("배율은 1~15배까지만 가능해요.")
        return int(text)

    def apply_leverage(self,event=None):
        """배율 입력칸에서 Enter를 누르면 바로 바이낸스에 적용한다."""
        try:
            if not self.client:
                raise ValueError("계좌를 먼저 연결하세요.")
            if self.running:
                raise ValueError("자동매매 중에는 배율을 바꿀 수 없습니다. 중지 후 변경하세요.")
            lev=self.client.set_leverage(self.read_leverage())
            self.note(f"배율 설정 완료 · BTCUSDT {lev}x")
            self.refresh()
        except Exception as e:
            self.note(f"배율 설정 실패 · {e}")

    def connect(self):
        self.stop()
        if self.refresh_job is not None:
            self.root.after_cancel(self.refresh_job)
            self.refresh_job=None
        self.client=None
        for tile in self.tiles:
            tile.configure(text="—")
        self.floor.signals=["대기"]*len(LEVELS)
        self.floor.paint()
        try:
            c=Exchange(self.mode.get()=="Demo",self.key.get().strip(),self.secret.get().strip())
            now=int(c.get("v1/time")["serverTime"])
            c._time_offset=now-int(time.time()*1000)
            account=c.get("v3/balance",private=True)
            balance=next((b["availableBalance"] for b in account if b["asset"]=="USDT"),"0")
            qty=c.position()
            self.stats(c,now)
            self.tiles[0].configure(text=f"{qty:f}")
            self.client=c
            self.environment=self.mode.get()
            self.state.set(f"{self.environment} 연결됨   |   사용 가능 {D(balance):,.2f} USDT   |   {qty} BTC")
            self.note(f"{self.environment} API 설정 완료 · 계좌 연결됨 · 사용 가능 {D(balance):,.2f} USDT · 포지션 {qty} BTC · 배율 {c.leverage()}x")
            self.refresh()
            self.root.after(1500,lambda: self.toggle_api(False))  # 연결되면 API 칸 자동 접기
        except Exception as e:
            self.state.set("연결 실패")
            self.note(f"API 연결 실패 · {e}")

    def stats(self,c,now):
        rows=c.get("v1/userTrades",{"symbol":SYMBOL,"startTime":now-86400000,"limit":1000},True)
        if len(rows)==1000:
            for tile in self.tiles[1:]:
                tile.configure(text="집계 한도 초과")
            self.metrics.set("24시간 집계 한도 초과")
            return
        counts=[len({r["orderId"] for r in rows if r["side"]==side}) for side in ("BUY","SELL")]
        pnl=sum((D(r["realizedPnl"]) for r in rows),D(0))
        # USDT-linear contracts: closed notional minus signed PnL recovers entry notional.
        basis=sum((D(r["quoteQty"])+(1 if r["side"]=="BUY" else -1)*D(r["realizedPnl"])
                   for r in rows if D(r["realizedPnl"])!=0),D(0))
        roi=f"{100*pnl/basis:+.2f}%" if basis else "—"
        for tile,value in zip(self.tiles[1:],(f"{counts[0]}  /  {counts[1]}",f"{pnl:+,.2f}",roi)):
            tile.configure(text=value)
        self.metrics.set(f"24h 매수 {counts[0]} · 매도 {counts[1]}   |   실현 {pnl:+.2f} USDT   |   유손익 청산 원금 대비 {roi} (비용 전)")

    def stop(self):
        self.running=False
        for w in (self.select, self.strategy):
            w.configure(state="readonly")
        for w in (self.key, self.secret, self.amount, self.lev_entry):
            w.configure(state="normal")
        if self.job is not None:
            self.root.after_cancel(self.job)
            self.job=None
        self.state.set("자동매매 중지 · 보유 포지션 유지")

    def start(self):
        if self.running:
            return
        try:
            if not self.client or self.environment!=self.mode.get():
                raise ValueError("선택한 환경으로 계좌를 먼저 연결하세요.")
            self.weight=D(self.amount.get().strip().rstrip("%"))
            if not self.weight.is_finite() or not 0<self.weight<=100:
                raise ValueError("비중은 0보다 크고 100 이하인 %로 입력하세요.")
            lev=self.read_leverage()
            self.active_level=self.level.get()
            if self.client.get("v1/positionSide/dual",private=True)["dualSidePosition"]:
                raise ValueError("바이낸스 단방향 모드가 필요합니다.")
            qty=self.client.position()
            if self.client.get("v1/openOrders",{"symbol":SYMBOL},True):
                raise ValueError("BTCUSDT 미체결 주문을 먼저 확인하세요.")
            if not messagebox.askyesno("퀀트 트레이딩 시작",f"{self.environment} BTCUSDT · {self.active_level}\n진입 비중 {self.weight}% (사용 가능 USDT 대비 증거금) · 배율 {lev}x\n기존 {qty} BTC 전체도 전략에 따라 청산합니다. 시작할까요?"):
                return
            lev=self.client.set_leverage(lev)
            self.note(f"배율 설정 완료 · BTCUSDT {lev}x")
            self.expected=qty
            self.last_day=None
            self.running=True
            for w in (self.select,self.strategy,self.key,self.secret,self.amount,self.lev_entry):
                w.configure(state="disabled")
            self.tick()
        except Exception as e:
            self.stop()
            self.note(str(e))

    def fill(self,delta,closing):
        result=self.client.order(delta,closing)
        self.expected+=delta
        message=f"{self.environment} 체결 {result['side']} {result['executedQty']} BTC @ {result.get('avgPrice') or result.get('cumQuote') and float(result['cumQuote'])/float(result['executedQty']) or '시장가'}"
        self.note(message)
        self.root.bell()
        self.refresh()
        try:
            self.notifier.send(message)
        except Exception:
            self.note("텔레그램 알림 전송 실패")

    def tick(self):
        self.job=None
        try:
            c=self.client
            now=int(c.get("v1/time")["serverTime"])
            bars=c.get("v1/klines",{"symbol":SYMBOL,"interval":"1d","limit":65})
            closed=[b for b in bars if b[6]<now]
            day=closed[-1][6]
            qty=c.position()
            if qty!=self.expected:
                raise ValueError("거래소 포지션이 바뀌어 중지했습니다.")
            sign=int(qty>0)-int(qty<0)
            target=direction([D(b[4]) for b in closed],self.active_level,sign)
            closes=[D(b[4]) for b in closed]
            self.floor.signals=[{0:"관망",1:"롱",-1:"숏"}[direction(closes,level,sign)] for level in LEVELS]
            self.floor.paint()
            if self.last_day!=day and now-day<=120000 and target!=sign:
                if qty:
                    self.fill(-qty,True)
                    if c.position()!=0:
                        raise ValueError("청산 후 포지션 확인 필요")
                if target:
                    last,sma=closes[-1],mean(closes[-50:])
                    gap=(last/sma-1)*100
                    # 비중: 청산 후 사용 가능 USDT x 비중% = 증거금, x 계좌 배율 = 명목금액
                    info=next(s for s in c.get("v1/exchangeInfo")["symbols"] if s["symbol"]==SYMBOL)
                    filters={f["filterType"]:f for f in info["filters"]}
                    lot=filters["MARKET_LOT_SIZE"]
                    step=D(lot["stepSize"])
                    price=D(c.get("v1/ticker/price",{"symbol":SYMBOL})["price"])
                    lev=c.leverage()
                    notional=c.usdt_available()*self.weight/100*lev
                    size=(notional/price//step)*step
                    if not D(lot["minQty"])<=size<=D(lot["maxQty"]) or size*price<D(filters["MIN_NOTIONAL"]["notional"]):
                        raise ValueError(f"비중 {self.weight}% · {lev}x → 명목 {notional:.2f} USDT가 거래소 주문 범위 밖입니다.")
                    self.note(f"진입 계산 · 비중 {self.weight}% · {lev}x · 명목 {notional:.2f} USDT · {size} BTC")
                    self.fill(target*size,False)
                    side={1:"롱",-1:"숏"}[target]
                    self.entry_bubble=(time.time(),dict(target=target,date=time.strftime('%m/%d', time.localtime(day/1000)),
                                       last=last,gap=gap,flipped=bool(qty),weight=self.weight,lev=lev,size=size,notional=size*price))
                    self.note(f"{side} 진입 근거 · 종가 {last:,.1f} vs 50일 평균 {sma:,.1f} ({gap:+.2f}%)")
                    self.update_bubble(price)
            self.last_day=day
            self.tiles[0].configure(text=f"{self.expected:f}")
            self.stats(c,now)
            self.state.set(f"{self.environment} 자동 감시 · {self.active_level} · 목표 {['관망','롱','숏'][target]} · {self.expected} BTC")
            self.job=self.root.after(30000,self.tick)
        except Exception as e:
            self.stop()
            self.note(f"감시 중지 · 거래소 포지션 및 주문 확인: {e}")


if __name__=="__main__":
    root=tk.Tk()
    Desk(root)
    root.mainloop()
