"""OKX · Gate USDT 무기한 선물 어댑터.

kbtc_bot.Futures(바이낸스)와 같은 메서드를 갖고, 응답도 바이낸스 모양(키 이름)으로 바꿔서 돌려준다.
그래서 매매(kbtc_bot.decide)·앱(web.py)·분석(trade.py) 코드는 거래소를 몰라도 된다.

수량은 항상 BTC 기준으로 주고받는다. (OKX 1계약 = 0.01 BTC, Gate 1계약 = 0.0001 BTC → 안에서 변환)
- OKX: 모의거래(Demo)는 같은 주소에 'x-simulated-trading: 1' 헤더. 단방향(net) 포지션 모드, 교차(cross) 마진.
- Gate: TestNet 은 api-testnet.gateapi.io. 단일(single) 포지션 모드, 교차(cross) 마진.
표준 라이브러리만 사용.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal as D
from uuid import uuid4

DAY = 86_400_000


def _http(method, url, headers, data, name):
    r = urllib.request.Request(url, data=data.encode() if data else None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=15) as res:
            return json.loads(res.read().decode() or "null")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            j = json.loads(body)
            body = j.get("msg") or j.get("message") or j.get("label") or body
            if isinstance(j, dict) and j.get("label"):
                body = f"{j['label']} {j.get('message', '')}".strip()
            if isinstance(j, dict) and j.get("code"):
                body = f"{j['code']} {body}"
        except (json.JSONDecodeError, AttributeError):
            pass
        raise RuntimeError(f"{name} HTTP {e.code}: {body}") from e


class _Base:
    """공통: % → 가격 TP/SL."""

    def place_tpsl(self, side, entry, tp_pct, sl_pct):
        tick, px = self.tick(), {}
        for kind, pct, sign in (("tp", tp_pct, 1), ("sl", sl_pct, -1)):
            if pct:
                p = D(str(entry)) * (1 + side * sign * D(str(pct)) / 100)
                px[kind] = (p / tick).quantize(D(1)) * tick
        return self.place_tpsl_px(side, px.get("tp"), px.get("sl"))

    def available(self):
        return D(self.account()["availableBalance"])


# ───────────────────────── OKX ─────────────────────────
class Okx(_Base):
    NAME = "OKX"

    def __init__(self, cfg):
        self.key, self.secret, self.pp = cfg["key"], cfg["secret"], cfg.get("passphrase", "")
        self.demo = cfg["mode"] == "demo"
        self.symbol = cfg["symbol"]
        self.inst = cfg["symbol"].replace("USDT", "") + "-USDT-SWAP"   # BTCUSDT → BTC-USDT-SWAP
        self.base = "https://www.okx.com"
        self.offset = 0
        self._info = None

    def req(self, method, path, params=None, signed=False, body=None):
        q = urllib.parse.urlencode(params or {})
        rp = path + ("?" + q if q else "")
        data = json.dumps(body) if body is not None else ""
        h = {"User-Agent": "KBTC/1.0", "Content-Type": "application/json"}
        if self.demo:
            h["x-simulated-trading"] = "1"
        if signed:
            t = time.time() + self.offset / 1000
            ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{int(t * 1000) % 1000:03d}Z"
            sig = base64.b64encode(hmac.new(self.secret.encode(), (ts + method + rp + data).encode(), hashlib.sha256).digest()).decode()
            h.update({"OK-ACCESS-KEY": self.key, "OK-ACCESS-SIGN": sig, "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": self.pp})
        res = _http(method, self.base + rp, h, data, "OKX")
        if str(res.get("code")) != "0":
            d = res.get("data") or []
            detail = d[0].get("sMsg") if d and isinstance(d[0], dict) and d[0].get("sMsg") else res.get("msg")
            code = d[0].get("sCode") if d and isinstance(d[0], dict) and d[0].get("sCode") else res.get("code")
            raise RuntimeError(f"OKX {code}: {detail}")
        return res["data"]

    # ── 기본 ──
    def sync(self):
        self.offset = int(self.req("GET", "/api/v5/public/time")[0]["ts"]) - int(time.time() * 1000)
        return int(time.time() * 1000) + self.offset

    def info(self):
        if not self._info:
            self._info = self.req("GET", "/api/v5/public/instruments", {"instType": "SWAP", "instId": self.inst})[0]
        return self._info

    @property
    def ct(self):
        return D(self.info()["ctVal"])  # 1계약 = 0.01 BTC

    def closed_daily(self, now):
        rows = self.req("GET", "/api/v5/market/candles", {"instId": self.inst, "bar": "1Dutc", "limit": "100"})
        bars = [[int(r[0]), r[1], r[2], r[3], r[4], r[5], int(r[0]) + DAY - 1] for r in reversed(rows)]
        return [b for b in bars if b[6] < now]

    def _pos_rows(self):
        rows = self.req("GET", "/api/v5/account/positions", {"instType": "SWAP", "instId": self.inst}, True)
        if any(r.get("posSide") not in ("net", "") for r in rows):
            raise RuntimeError("OKX 포지션 모드를 단방향(One-way / Net)으로 바꿔 주세요. (설정 → 포지션 모드)")
        return [r for r in rows if D(r.get("pos") or 0) != 0]

    def position(self):
        return sum((D(r["pos"]) * self.ct for r in self._pos_rows()), D(0))

    def pos_info(self):
        rows = self._pos_rows()
        if not rows:
            try:
                lev = self.req("GET", "/api/v5/account/leverage-info", {"instId": self.inst, "mgnMode": "cross"}, True)[0]["lever"]
            except Exception:
                lev = "0"
            return dict(positionAmt="0", entryPrice="0", markPrice=str(self.price()), unRealizedProfit="0",
                        liquidationPrice="0", leverage=str(int(float(lev))), marginType="cross", notional="0")
        r = rows[0]
        return dict(positionAmt=str(D(r["pos"]) * self.ct), entryPrice=r.get("avgPx") or "0", markPrice=r.get("markPx") or "0",
                    unRealizedProfit=r.get("upl") or "0", liquidationPrice=r.get("liqPx") or "0",
                    leverage=str(int(float(r.get("lever") or 0))), marginType=r.get("mgnMode") or "cross",
                    notional=r.get("notionalUsd") or "0")

    def account(self):
        d = self.req("GET", "/api/v5/account/balance", {"ccy": "USDT"}, True)[0]
        det = next((x for x in d.get("details", []) if x.get("ccy") == "USDT"), {})
        f = lambda *ks: next((D(det[k]) for k in ks if det.get(k) not in ("", None)), D(0))
        return dict(totalMarginBalance=str(f("eq")), totalWalletBalance=str(f("cashBal")), totalUnrealizedProfit=str(f("upl")),
                    availableBalance=str(f("availEq", "availBal")), totalInitialMargin=str(f("imr", "frozenBal")),
                    totalMaintMargin=str(f("mmr")))

    def set_leverage(self, lev):
        d = self.req("POST", "/api/v5/account/set-leverage", signed=True, body={"instId": self.inst, "lever": str(lev), "mgnMode": "cross"})
        return int(float(d[0]["lever"]))

    def price(self):
        return D(self.req("GET", "/api/v5/market/ticker", {"instId": self.inst})[0]["last"])

    def filters(self):
        i, ct = self.info(), self.ct
        return {"MARKET_LOT_SIZE": {"stepSize": str(D(i["lotSz"]) * ct), "minQty": str(D(i["minSz"]) * ct),
                                    "maxQty": str(D(i.get("maxMktSz") or "1000000") * ct)},
                "MIN_NOTIONAL": {"notional": "0"}, "PRICE_FILTER": {"tickSize": i["tickSz"]}}

    def tick(self):
        return D(self.info()["tickSz"])

    def _sz(self, btc):
        lot = D(self.info()["lotSz"])
        return (abs(D(btc)) / self.ct // lot) * lot

    def order(self, delta, closing):
        sz = self._sz(delta)
        if sz <= 0:
            raise RuntimeError("주문 수량이 OKX 최소 단위보다 작아요.")
        body = {"instId": self.inst, "tdMode": "cross", "side": "buy" if delta > 0 else "sell", "ordType": "market",
                "sz": format(sz, "f"), "clOrdId": "kbtc" + uuid4().hex[:28]}
        if closing:
            body["reduceOnly"] = True
        oid = self.req("POST", "/api/v5/trade/order", signed=True, body=body)[0]["ordId"]
        o = {}
        for _ in range(20):  # 시장가는 거의 즉시 체결. 상태 확인
            o = self.req("GET", "/api/v5/trade/order", {"instId": self.inst, "ordId": oid}, True)[0]
            if o["state"] in ("filled", "canceled", "mmp_canceled"):
                break
            time.sleep(0.3)
        filled = D(o.get("accFillSz") or 0)
        if o.get("state") != "filled" or filled != sz:
            raise RuntimeError("주문이 완전히 체결되지 않았습니다. OKX 에서 확인하세요.")
        return dict(orderId=oid, status="FILLED", executedQty=str(filled * self.ct), avgPrice=o.get("avgPx") or str(self.price()))

    def open_orders(self):
        return self.req("GET", "/api/v5/trade/orders-pending", {"instType": "SWAP", "instId": self.inst}, True)

    # ── TP/SL (조건부 알고 주문, 마크가격 트리거) ──
    def _algos(self):
        return self.req("GET", "/api/v5/trade/orders-algo-pending", {"ordType": "conditional", "instType": "SWAP", "instId": self.inst}, True)

    def open_algos(self):
        out = []
        for a in self._algos():
            for kind, k in (("TAKE_PROFIT_MARKET", "tpTriggerPx"), ("STOP_MARKET", "slTriggerPx")):
                if a.get(k):
                    out.append(dict(algoId=a["algoId"], side=a["side"].upper(), orderType=kind,
                                    triggerPrice=a[k], createTime=int(a.get("cTime") or 0)))
        return out

    def cancel_algos(self):
        rows = self._algos()
        for i in range(0, len(rows), 10):
            self.req("POST", "/api/v5/trade/cancel-algos", signed=True,
                     body=[{"algoId": a["algoId"], "instId": self.inst} for a in rows[i:i + 10]])

    def place_tpsl_px(self, side, tp, sl, qty=None):
        """OKX 는 전량 청산 TP/SL 을 포지션당 하나만 받으므로 TP·SL 을 한 주문에 같이 건다."""
        if not tp and not sl:
            return []
        body = {"instId": self.inst, "tdMode": "cross", "side": "sell" if side > 0 else "buy", "ordType": "conditional",
                "reduceOnly": True, "algoClOrdId": "kbtc" + uuid4().hex[:28]}
        if qty is None:
            body["closeFraction"] = "1"
        else:
            sz = self._sz(qty)
            if sz <= 0:
                raise ValueError("수량이 최소 주문 단위보다 작아요.")
            body["sz"] = format(sz, "f")
        out = []
        if tp:
            body.update(tpTriggerPx=format(tp, "f"), tpOrdPx="-1", tpTriggerPxType="mark"); out.append(("TAKE_PROFIT_MARKET", tp))
        if sl:
            body.update(slTriggerPx=format(sl, "f"), slOrdPx="-1", slTriggerPxType="mark"); out.append(("STOP_MARKET", sl))
        self.req("POST", "/api/v5/trade/order-algo", signed=True, body=body)
        return out

    # ── 기록 (최근 3개월) ──
    def _pages(self, path, params, days, key="billId", ts="ts", pages=40):
        cut = int(time.time() * 1000) - days * DAY
        out, after = [], None
        for _ in range(pages):
            p = dict(params, limit="100", **({"after": after} if after else {}))
            rows = self.req("GET", path, p, True)
            out += [r for r in rows if int(r[ts]) >= cut]
            if len(rows) < 100 or int(rows[-1][ts]) < cut:
                break
            after = rows[-1][key]
            time.sleep(0.2)  # 초당 요청 제한
        return out

    def trades_hist(self, days):
        ct = self.ct
        rows = self._pages("/api/v5/trade/fills-history", {"instType": "SWAP", "instId": self.inst}, days)
        return [dict(id=int(r["billId"]), time=int(r["ts"]), side=r["side"].upper(), qty=str(D(r["fillSz"]) * ct),
                     price=r["fillPx"], realizedPnl=r.get("fillPnl") or "0", commission=str(-D(r.get("fee") or 0)))
                for r in rows]

    def income_hist(self, days):
        """bills-archive 를 바이낸스 income 모양으로. 각 줄 합계 = 잔고 변화(balChg)."""
        out = []
        for r in self._pages("/api/v5/account/bills-archive", {"ccy": "USDT"}, days):
            t, bal = int(r["ts"]), D(r.get("balChg") or 0)
            row = lambda kind, v: dict(time=t, incomeType=kind, income=str(v), asset="USDT", tranId=r["billId"])
            if r.get("type") == "8":
                out.append(row("FUNDING_FEE", bal))
            elif r.get("instType") in ("SWAP", "FUTURES"):
                pnl, fee = D(r.get("pnl") or 0), D(r.get("fee") or 0)
                out += [row("REALIZED_PNL", pnl), row("COMMISSION", fee)]
                if bal - pnl - fee:
                    out.append(row("OTHER", bal - pnl - fee))
            else:
                out.append(row("TRANSFER", bal))
        return out

    def orders_hist(self, limit):
        ct = self.ct
        rows = self.req("GET", "/api/v5/trade/orders-history", {"instType": "SWAP", "instId": self.inst, "limit": str(min(limit, 100))}, True)
        return [dict(time=int(o["cTime"]), side=o["side"].upper(), type=o["ordType"].upper(),
                     status={"filled": "FILLED", "canceled": "CANCELED"}.get(o["state"], o["state"].upper()),
                     executedQty=str(D(o.get("accFillSz") or 0) * ct), origQty=str(D(o.get("sz") or 0) * ct),
                     avgPrice=o.get("avgPx") or "0", price=o.get("px") or "0", reduceOnly=o.get("reduceOnly") == "true",
                     clientOrderId=o.get("clOrdId") or "") for o in rows]


# ───────────────────────── Gate ─────────────────────────
class Gate(_Base):
    NAME = "Gate"

    def __init__(self, cfg):
        self.key, self.secret = cfg["key"], cfg["secret"]
        self.symbol = cfg["symbol"]
        self.contract = cfg["symbol"].replace("USDT", "") + "_USDT"   # BTCUSDT → BTC_USDT
        self.base = "https://api-testnet.gateapi.io/api/v4" if cfg["mode"] == "demo" else "https://api.gateio.ws/api/v4"
        self.offset = 0
        self._info = None

    def req(self, method, path, params=None, signed=False, body=None):
        q = urllib.parse.urlencode(params or {})
        data = json.dumps(body) if body is not None else ""
        h = {"User-Agent": "KBTC/1.0", "Accept": "application/json", "Content-Type": "application/json"}
        if signed:
            ts = str(int(time.time() + self.offset / 1000))
            msg = "\n".join([method, "/api/v4" + path, q, hashlib.sha512(data.encode()).hexdigest(), ts])
            h.update(KEY=self.key, Timestamp=ts, SIGN=hmac.new(self.secret.encode(), msg.encode(), hashlib.sha512).hexdigest())
        return _http(method, self.base + path + ("?" + q if q else ""), h, data, "Gate")

    # ── 기본 ──
    def sync(self):
        try:
            self.offset = int(self.req("GET", "/spot/time")["server_time"]) - int(time.time() * 1000)
        except Exception:
            self.offset = 0
        return int(time.time() * 1000) + self.offset

    def info(self):
        if not self._info:
            self._info = self.req("GET", f"/futures/usdt/contracts/{self.contract}")
        return self._info

    @property
    def mult(self):
        return D(self.info()["quanto_multiplier"])  # 1계약 = 0.0001 BTC

    def closed_daily(self, now):
        rows = self.req("GET", "/futures/usdt/candlesticks", {"contract": self.contract, "interval": "1d", "limit": 100})
        bars = [[int(r["t"]) * 1000, r["o"], r["h"], r["l"], r["c"], r["v"], int(r["t"]) * 1000 + DAY - 1] for r in rows]
        return [b for b in bars if b[6] < now]

    def _pos(self):
        try:
            p = self.req("GET", f"/futures/usdt/positions/{self.contract}", signed=True)
        except RuntimeError as e:
            if "dual" in str(e).lower():
                raise RuntimeError("Gate 포지션 모드를 단일(Single / One-way)로 바꿔 주세요.") from e
            raise
        if p.get("mode") not in (None, "single"):
            raise RuntimeError("Gate 포지션 모드를 단일(Single / One-way)로 바꿔 주세요.")
        return p

    def position(self):
        return D(self._pos().get("size") or 0) * self.mult

    def pos_info(self):
        p = self._pos()
        cross = str(p.get("leverage")) == "0"
        lev = int(float(p.get("cross_leverage_limit") or 0)) if cross else int(float(p.get("leverage") or 0))
        return dict(positionAmt=str(D(p.get("size") or 0) * self.mult), entryPrice=p.get("entry_price") or "0",
                    markPrice=p.get("mark_price") or "0", unRealizedProfit=p.get("unrealised_pnl") or "0",
                    liquidationPrice=p.get("liq_price") or "0", leverage=str(lev),
                    marginType="cross" if cross else "isolated", notional=p.get("value") or "0")

    def account(self):
        a = self.req("GET", "/futures/usdt/accounts", signed=True)
        f = lambda *ks: next((D(str(a[k])) for k in ks if a.get(k) not in ("", None)), D(0))
        total, upnl = f("total"), f("unrealised_pnl")
        used = f("position_initial_margin") or f("position_margin")
        return dict(totalMarginBalance=str(total + upnl), totalWalletBalance=str(total), totalUnrealizedProfit=str(upnl),
                    availableBalance=str(f("cross_available", "available")), totalInitialMargin=str(used + f("order_margin")),
                    totalMaintMargin=str(f("maintenance_margin", "cross_maintenance_margin")))

    def set_leverage(self, lev):
        p = self.req("POST", f"/futures/usdt/positions/{self.contract}/leverage",
                     {"leverage": "0", "cross_leverage_limit": str(lev)}, True)
        return int(float(p.get("cross_leverage_limit") or p.get("leverage") or lev))

    def price(self):
        return D(self.req("GET", "/futures/usdt/tickers", {"contract": self.contract})[0]["last"])

    def filters(self):
        i, m = self.info(), self.mult
        return {"MARKET_LOT_SIZE": {"stepSize": str(m), "minQty": str(D(i["order_size_min"]) * m),
                                    "maxQty": str(D(i.get("market_order_size_max") or i["order_size_max"]) * m)},
                "MIN_NOTIONAL": {"notional": "0"}, "PRICE_FILTER": {"tickSize": i["order_price_round"]}}

    def tick(self):
        return D(self.info()["order_price_round"])

    def _size(self, btc):
        return int(abs(D(btc)) / self.mult)

    def order(self, delta, closing):
        n = self._size(delta)
        if n <= 0:
            raise RuntimeError("주문 수량이 Gate 최소 단위보다 작아요.")
        body = {"contract": self.contract, "size": n if delta > 0 else -n, "price": "0", "tif": "ioc",
                "text": "t-kbtc" + uuid4().hex[:20]}
        if closing:
            body["reduce_only"] = True
        o = self.req("POST", "/futures/usdt/orders", signed=True, body=body)
        filled = abs(int(o.get("size", 0))) - abs(int(o.get("left", 0)))
        if o.get("finish_as") != "filled" or filled != n:
            raise RuntimeError("주문이 완전히 체결되지 않았습니다. Gate 에서 확인하세요.")
        return dict(orderId=o["id"], status="FILLED", executedQty=str(filled * self.mult),
                    avgPrice=o.get("fill_price") or str(self.price()))

    def open_orders(self):
        return self.req("GET", "/futures/usdt/orders", {"contract": self.contract, "status": "open"}, True)

    # ── TP/SL (가격 트리거 주문, 마크가격) ──
    def _price_orders(self):
        return self.req("GET", "/futures/usdt/price_orders", {"status": "open", "contract": self.contract}, True)

    def open_algos(self):
        rows = self._price_orders()
        if not rows:
            return []
        side = 1 if self.position() >= 0 else -1
        out = []
        for a in rows:
            rule = int(a["trigger"]["rule"])  # 1: 가격 >= 트리거, 2: 가격 <= 트리거
            tp = (rule == 1) == (side > 0)
            out.append(dict(algoId=a["id"], side="SELL" if side > 0 else "BUY", orderType="TAKE_PROFIT_MARKET" if tp else "STOP_MARKET",
                            triggerPrice=a["trigger"]["price"], createTime=int(float(a.get("create_time") or 0) * 1000)))
        return out

    def cancel_algos(self):
        if self._price_orders():
            self.req("DELETE", "/futures/usdt/price_orders", {"contract": self.contract}, True)

    def place_tpsl_px(self, side, tp, sl, qty=None):
        out = []
        for kind, px in (("TAKE_PROFIT_MARKET", tp), ("STOP_MARKET", sl)):
            if not px:
                continue
            rule = 1 if (kind.startswith("TAKE") == (side > 0)) else 2
            init = {"contract": self.contract, "price": "0", "tif": "ioc"}
            if qty is None:
                init.update(size=0, close=True)
            else:
                n = self._size(qty)
                if n <= 0:
                    raise ValueError("수량이 최소 주문 단위보다 작아요.")
                init.update(size=-n if side > 0 else n, reduce_only=True)
            self.req("POST", "/futures/usdt/price_orders", signed=True, body={
                "initial": init, "trigger": {"strategy_type": 0, "price_type": 1, "price": format(px, "f"), "rule": rule, "expiration": 0}})
            out.append((kind, px))
        return out

    # ── 기록 ──
    def _range(self, path, params, days, pages=20):
        now = int(time.time())
        out = []
        for a, b in _windows_s(now, days):
            for i in range(pages):
                rows = self.req("GET", path, dict(params, **{"from": a, "to": b, "limit": 1000, "offset": i * 1000}), True)
                out += rows
                if len(rows) < 1000:
                    break
        return out

    def trades_hist(self, days):
        """Gate 체결에는 실현손익이 없어서, 평균단가로 직접 계산해 넣는다."""
        rows = sorted({r["id"]: r for r in self._range("/futures/usdt/my_trades_timerange", {"contract": self.contract}, days)}.values(),
                      key=lambda r: (float(r["create_time"]), r["id"]))
        m, net, avg, out = self.mult, D(0), D(0), []
        for r in rows:
            q, px = D(int(r["size"])) * m, D(r["price"])
            pnl = D(0)
            if net == 0 or (q > 0) == (net > 0):
                avg = (avg * abs(net) + px * abs(q)) / (abs(net) + abs(q))
            else:
                close_q = min(abs(q), abs(net))
                pnl = close_q * (px - avg) * (1 if net > 0 else -1)
                if abs(q) > abs(net):
                    avg = px
            net += q
            out.append(dict(id=int(r["id"]), time=int(float(r["create_time"]) * 1000), side="BUY" if q > 0 else "SELL",
                            qty=str(abs(q)), price=r["price"], realizedPnl=str(pnl), commission=str(D(str(r.get("fee") or 0)))))
        return out

    def income_hist(self, days):
        kinds = {"pnl": "REALIZED_PNL", "fee": "COMMISSION", "fund": "FUNDING_FEE", "dnw": "TRANSFER"}
        return [dict(time=int(float(r["time"]) * 1000), incomeType=kinds.get(r.get("type"), "OTHER"), income=str(r["change"]),
                     asset="USDT", tranId=r.get("id") or f"{r['time']}-{r.get('type')}-{r['change']}")
                for r in self._range("/futures/usdt/account_book", {}, days)]

    def orders_hist(self, limit):
        m = self.mult
        rows = self.req("GET", "/futures/usdt/orders", {"contract": self.contract, "status": "finished", "limit": min(limit, 100)}, True)
        return [dict(time=int(float(o["create_time"]) * 1000), side="BUY" if int(o["size"]) > 0 else "SELL",
                     type="MARKET" if D(str(o.get("price") or 0)) == 0 else "LIMIT",
                     status=(o.get("finish_as") or o.get("status") or "").upper(),
                     executedQty=str((abs(int(o["size"])) - abs(int(o.get("left") or 0))) * m), origQty=str(abs(int(o["size"])) * m),
                     avgPrice=o.get("fill_price") or "0", price=o.get("price") or "0", reduceOnly=bool(o.get("is_reduce_only")),
                     clientOrderId=o.get("text") or "") for o in rows]


def _windows_s(now_s, days, step=30):
    """초 단위 [now-days, now] 를 step 일 구간으로."""
    end = now_s
    while end > now_s - days * 86400:
        start = max(end - step * 86400 + 1, now_s - days * 86400)
        yield start, end
        end = start - 1
