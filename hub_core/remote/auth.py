"""
Pairing of another PC (or a tablet, or a phone) with a code that changes every 10 seconds, like an authenticator
app: Delta Suite shows the code on the sim PC, the other device types it once and gets its own token.

- The code is an HOTP (RFC 4226, HMAC-SHA1, 6 digits) of a random secret created at every start of Delta Suite and
  of the 10-second window: it cannot be guessed from the previous ones. Each code works once; the previous window
  is still accepted so that it can be typed calmly (at most ~20 s of validity).
- Wrong attempts are limited per address and overall: 6 digits with these limits cannot be brute-forced.
- A paired device keeps a random token (the device stores it, Delta Suite only its SHA-256). It stays valid
  until it is revoked, also across restarts if the hub saves the list (`export()` / `load()`).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import struct
import threading
import time
from dataclasses import dataclass, field

STEP_S = 10
DIGITS = 6
IP_MAX_FAILS, IP_WINDOW_S = 5, 300.0      # per address: 5 wrong codes in 5 minutes -> wait
ALL_MAX_FAILS, ALL_LOCK_S = 30, 60.0      # overall: 30 wrong codes in 5 minutes -> pairing paused for a minute
NAME_MAX = 40


def hotp(secret: bytes, counter: int, digits: int = DIGITS) -> str:
    mac = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** digits).zfill(digits)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class PairError(Exception):
    def __init__(self, message: str, retry_after: float = 0.0):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class Device:
    id: str                     # short public id (to revoke it), not the token
    name: str
    token_hash: str
    created: float
    last_seen: float = 0.0
    address: str = ""

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "created": self.created, "last_seen": self.last_seen,
                "address": self.address}


@dataclass
class Pairing:
    step_s: int = STEP_S
    clock: object = time.time
    secret: bytes = field(default_factory=lambda: secrets.token_bytes(20))

    def __post_init__(self):
        self._lock = threading.Lock()
        self._used: set[int] = set()
        self._fails: dict[str, list[float]] = {}
        self._all_fails: list[float] = []
        self._locked_until = 0.0
        self.devices: dict[str, Device] = {}
        self.on_change = None           # called (without arguments) when devices are added or revoked

    # -------------------------------------------------------------- the code shown on the sim PC
    def _counter(self, now: float | None = None) -> int:
        return int((self.clock() if now is None else now) // self.step_s)

    def current_code(self) -> tuple[str, float]:
        """(code, seconds before it changes)."""
        now = self.clock()
        return hotp(self.secret, self._counter(now)), self.step_s - (now % self.step_s)

    # -------------------------------------------------------------- pairing from the other device
    def pair(self, code: str, name: str, address: str) -> str:
        """Checks the code and returns the new device's token; PairError if wrong or too many attempts."""
        now = self.clock()
        code = "".join(ch for ch in str(code) if ch.isdigit())
        with self._lock:
            if now < self._locked_until:
                raise PairError("too many wrong codes: pairing paused", self._locked_until - now)
            fails = [t for t in self._fails.get(address, []) if now - t < IP_WINDOW_S]
            self._fails[address] = fails
            if len(fails) >= IP_MAX_FAILS:
                raise PairError("too many wrong codes from this device", fails[0] + IP_WINDOW_S - now)
            counter = self._counter(now)
            match = next((c for c in (counter, counter - 1)
                          if c not in self._used and hmac.compare_digest(hotp(self.secret, c), code)), None)
            if match is None:
                fails.append(now)
                self._all_fails = [t for t in self._all_fails if now - t < IP_WINDOW_S] + [now]
                if len(self._all_fails) >= ALL_MAX_FAILS:
                    self._locked_until = now + ALL_LOCK_S
                    self._all_fails.clear()
                raise PairError("wrong or expired code")
            self._used = {c for c in self._used if c >= counter - 1} | {match}
            self._fails.pop(address, None)
            token = secrets.token_urlsafe(32)
            dev = Device(secrets.token_hex(4), (name or "Device").strip()[:NAME_MAX] or "Device", _hash(token),
                         now, now, address)
            self.devices[dev.id] = dev
        self._changed()
        return token

    def check(self, token: str | None, address: str = "") -> Device | None:
        if not token:
            return None
        h = _hash(token)
        with self._lock:
            dev = next((d for d in self.devices.values() if hmac.compare_digest(d.token_hash, h)), None)
            if dev is not None:
                dev.last_seen = self.clock()
                dev.address = address or dev.address
            return dev

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            found = self.devices.pop(device_id, None) is not None
        if found:
            self._changed()
        return found

    def revoke_all(self) -> None:
        with self._lock:
            self.devices.clear()
        self._changed()

    def device_list(self) -> list[Device]:
        with self._lock:
            return sorted(self.devices.values(), key=lambda d: d.created)

    # -------------------------------------------------------------- saving the paired devices
    def export(self) -> list[dict]:
        with self._lock:
            return [{"id": d.id, "name": d.name, "token_hash": d.token_hash, "created": d.created}
                    for d in self.devices.values()]

    def load(self, saved: list[dict]) -> None:
        with self._lock:
            for d in saved or []:
                try:
                    self.devices[str(d["id"])] = Device(str(d["id"]), str(d["name"])[:NAME_MAX],
                                                        str(d["token_hash"]), float(d["created"]))
                except (KeyError, TypeError, ValueError):
                    continue

    def _changed(self):
        if self.on_change is not None:
            try:
                self.on_change()
            except Exception:
                pass
