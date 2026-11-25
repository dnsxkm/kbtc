"""여러 사람이 각자 바이낸스/OKX/Gate Demo API 키로 쓰는 사용자 저장소.

- 사용자 ID = API Key 의 SHA-256 앞 16자리 (OKX/Gate 는 "거래소:키"). 키 자체는 파일 이름에 안 남김
- OKX 는 Passphrase 도 필요 (같이 암호화 저장)
- 키는 서버 비밀값으로 만든 HMAC 키스트림으로 암호화해 /data/users/<id>/keys.json 에 저장
- 매매 기록은 /data/users/<id>/state.json
- 서버 주인(환경변수 BINANCE_API_KEY)의 키로 접속하면 기존 /data/state.json 을 그대로 쓰는 'owner'
- 공유 사용자는 안전을 위해 Demo 계좌만 허용
"""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import secrets
import shutil
import threading
import time

import kbtc_bot as bot

BASE = os.getenv("STATE_DIR", bot.HERE)
UDIR = os.path.join(BASE, "users")
_lock = threading.Lock()


def server_secret() -> bytes:
    p = os.path.join(BASE, "server_secret")
    if not os.path.exists(p):
        os.makedirs(BASE, exist_ok=True)
        with open(p, "w") as f:
            f.write(secrets.token_hex(32))
        os.chmod(p, 0o600)
    return open(p).read().strip().encode()


SECRET = server_secret()


def _stream(nonce: bytes, n: int) -> bytes:
    out, i = b"", 0
    while len(out) < n:
        out += hmac.new(SECRET, nonce + i.to_bytes(4, "big"), hashlib.sha256).digest()
        i += 1
    return out[:n]


def encrypt(text: str) -> str:
    nonce = secrets.token_bytes(16)
    raw = text.encode()
    ct = bytes(a ^ b for a, b in zip(raw, _stream(nonce, len(raw))))
    tag = hmac.new(SECRET, nonce + ct, hashlib.sha256).digest()[:16]
    return base64.b64encode(nonce + tag + ct).decode()


def decrypt(blob: str) -> str:
    data = base64.b64decode(blob)
    nonce, tag, ct = data[:16], data[16:32], data[32:]
    if not hmac.compare_digest(tag, hmac.new(SECRET, nonce + ct, hashlib.sha256).digest()[:16]):
        raise ValueError("키 파일이 손상되었습니다.")
    return bytes(a ^ b for a, b in zip(ct, _stream(nonce, len(ct)))).decode()


EXCHANGES = {"binance": "Binance", "okx": "OKX", "gate": "Gate"}
KEY_HELP = {
    "binance": "키가 맞지 않거나 Futures 권한이 꺼져 있어요. Demo Trading API 에서 만든 키인지, Enable Futures 가 켜져 있는지 확인하세요.",
    "okx": "키·Secret·Passphrase 가 맞지 않거나 모의거래(Demo trading)용 키가 아니에요. OKX 모의거래 화면에서 만든 API 키인지, 권한에 Trade 가 있는지 확인하세요.",
    "gate": "키가 맞지 않거나 TestNet 키가 아니에요. Gate TestNet 에서 만든 키인지, Perpetual Futures 읽기·쓰기 권한이 있는지 확인하세요.",
}


def uid_for(key: str, exchange: str = "binance") -> str:
    raw = key if exchange == "binance" else f"{exchange}:{key}"  # 바이낸스는 기존 ID 그대로
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def sign(uid: str) -> str:
    return uid + "." + hmac.new(SECRET, b"session:" + uid.encode(), hashlib.sha256).hexdigest()[:32]


def verify(token: str) -> str | None:
    uid, _, sig = (token or "").partition(".")
    return uid if uid and hmac.compare_digest(sign(uid), token) else None


class Ctx:
    """한 사람 몫: 설정·거래소 클라이언트·알림·상태."""

    def __init__(self, uid, cfg, st, tg, owner=False):
        self.uid, self.cfg, self.st, self.owner = uid, cfg, st, owner
        self.ex = bot.make_ex(cfg)
        self.tg = tg
        self.acct_cache, self.acct_at = None, 0.0
        self.last_err, self.err_at = None, 0.0


class Store:
    def __init__(self, base_cfg, owner_st, owner_tg):
        self.base = base_cfg
        self.owner_uid = uid_for(base_cfg["key"]) if base_cfg["key"] else "owner"
        owner = Ctx(self.owner_uid, base_cfg, owner_st, owner_tg, owner=True)
        self.ctxs = {self.owner_uid: owner}
        os.makedirs(UDIR, exist_ok=True)
        for uid in os.listdir(UDIR):
            try:
                self._load(uid)
            except Exception as e:
                bot.log(f"사용자 {uid} 불러오기 실패: {e}")

    def _cfg_for(self, key, secret, exchange="binance", passphrase=""):
        cfg = copy.copy(self.base)
        cfg.update(key=key, secret=secret, mode="demo", tg_token="", tg_chat="", exchange=exchange, passphrase=passphrase,
                   weight=bot.D("30"), leverage=10, persona="에겐")
        return cfg

    def _load(self, uid):
        d = os.path.join(UDIR, uid)
        keys = json.load(open(os.path.join(d, "keys.json")))
        cfg = self._cfg_for(decrypt(keys["key"]), decrypt(keys["secret"]), keys.get("exchange", "binance"),
                            decrypt(keys["passphrase"]) if keys.get("passphrase") else "")
        st = bot.load_state(os.path.join(d, "state.json"))
        st["__path"] = os.path.join(d, "state.json")
        bot.apply_overrides(cfg, st)
        self.ctxs[uid] = Ctx(uid, cfg, st, bot.Telegram(cfg, st))
        return self.ctxs[uid]

    def all(self):
        return list(self.ctxs.values())

    def get(self, uid):
        return self.ctxs.get(uid)

    def connect(self, key: str, secret: str, exchange: str = "binance", passphrase: str = "") -> Ctx:
        """키를 검증(Demo 선물 계좌 조회)하고 사용자로 등록."""
        key, secret, passphrase = key.strip(), secret.strip(), passphrase.strip()
        if exchange not in EXCHANGES:
            raise ValueError("거래소는 Binance / OKX / Gate 중에서 골라 주세요.")
        if len(key) < 20 or len(secret) < 20:
            raise ValueError("API Key / Secret Key 를 정확히 붙여 넣어 주세요.")
        if exchange == "okx" and not passphrase:
            raise ValueError("OKX 는 API 키 만들 때 정한 Passphrase 도 넣어 주세요.")
        uid = uid_for(key, exchange)
        if uid == self.owner_uid:
            if not hmac.compare_digest(secret, self.base["secret"]):
                raise ValueError("Secret Key 가 맞지 않습니다.")
            return self.ctxs[uid]
        cfg = self._cfg_for(key, secret, exchange, passphrase)
        ex = bot.make_ex(cfg)
        try:
            ex.sync()
            ex.position()
            ex.account()
        except Exception as e:
            msg = str(e)
            if any(c in msg for c in ("-2015", "-2014", "401", "50111", "50113", "50119", "50101", "INVALID_KEY", "INVALID_SIGNATURE", "FORBIDDEN")):
                msg = KEY_HELP[exchange]
            raise ValueError(msg)
        with _lock:
            d = os.path.join(UDIR, uid)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "keys.json"), "w") as f:
                json.dump({"key": encrypt(key), "secret": encrypt(secret), "exchange": exchange,
                           "passphrase": encrypt(passphrase) if passphrase else "", "at": time.time()}, f)
            os.chmod(os.path.join(d, "keys.json"), 0o600)
            if uid in self.ctxs:  # 같은 키 다시 연결 → 시크릿 갱신
                self.ctxs[uid].cfg.update(key=key, secret=secret, passphrase=passphrase)
                self.ctxs[uid].ex = bot.make_ex(self.ctxs[uid].cfg)
                return self.ctxs[uid]
            ctx = self._load(uid)
            if not ctx.st.get("events"):
                ctx.st["paused"] = True          # 새 사용자는 [퀀트 트레이딩 시작]을 눌러야 시작
                ctx.tg.send(f"[KBTC] API 연결 완료 · {EXCHANGES[exchange]} Demo 계좌", notify=False)
                bot.save_state(ctx.st)
            bot.log(f"사용자 연결 {uid} (총 {len(self.ctxs)}명)")
            return ctx

    def remove(self, uid):
        if uid == self.owner_uid:
            raise ValueError("서버 주인 키는 여기서 삭제할 수 없습니다.")
        with _lock:
            self.ctxs.pop(uid, None)
            shutil.rmtree(os.path.join(UDIR, uid), ignore_errors=True)
        bot.log(f"사용자 삭제 {uid}")
