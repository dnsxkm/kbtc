from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN


class BinanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class BinanceClient:
    MAIN_URL = "https://api.binance.com"
    TESTNET_URL = "https://testnet.binance.vision"

    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = self.TESTNET_URL if testnet else self.MAIN_URL
        self._time_offset = 0

    def _request(self, method: str, path: str, params: dict | None = None, signed: bool = False):
        params = dict(params or {})
        if signed:
            if not self.api_key or not self.api_secret:
                raise BinanceError("바이낸스 API 키가 설정되지 않았습니다.")
            params["timestamp"] = int(time.time() * 1000) + self._time_offset
            params["recvWindow"] = 5000
            query = urllib.parse.urlencode(params)
            params["signature"] = hmac.new(
                self.api_secret.encode(), query.encode(), hashlib.sha256
            ).hexdigest()
        query = urllib.parse.urlencode(params)
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        headers = {"User-Agent": "QuantFloor/0.1"}
        if self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key
        req = urllib.request.Request(url, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=12) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                message = json.loads(body).get("msg", body)
            except json.JSONDecodeError:
                message = body
            raise BinanceError(f"Binance HTTP {exc.code}: {message}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise BinanceError(f"바이낸스 연결 실패: {exc}") from exc

    def sync_time(self) -> None:
        data = self._request("GET", "/api/v3/time")
        self._time_offset = int(data["serverTime"]) - int(time.time() * 1000)

    def candles(self, symbol: str, interval: str, limit: int = 200) -> list[Candle]:
        rows = self._request("GET", "/api/v3/klines", {
            "symbol": symbol.upper(), "interval": interval, "limit": limit
        })
        return [Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in rows]

    def price(self, symbol: str) -> float:
        return float(self._request("GET", "/api/v3/ticker/price", {"symbol": symbol.upper()})["price"])

    def account(self) -> dict:
        return self._request("GET", "/api/v3/account", signed=True)

    def market_order(self, symbol: str, side: str, quantity: float) -> dict:
        return self._request("POST", "/api/v3/order", {
            "symbol": symbol.upper(), "side": side.upper(), "type": "MARKET",
            "quantity": self.format_quantity(symbol, quantity),
        }, signed=True)

    def format_quantity(self, symbol: str, quantity: float) -> str:
        info = self._request("GET", "/api/v3/exchangeInfo", {"symbol": symbol.upper()})
        filters = info["symbols"][0]["filters"]
        lot = next(item for item in filters if item["filterType"] == "LOT_SIZE")
        step = Decimal(lot["stepSize"])
        value = Decimal(str(quantity)).quantize(step, rounding=ROUND_DOWN)
        if value < Decimal(lot["minQty"]):
            raise BinanceError("주문 수량이 Binance 최소 주문 수량보다 작습니다.")
        return format(value, "f")
