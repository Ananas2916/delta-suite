"""
Remote access: a small web server on the local network, so that another PC, a tablet or a phone can follow the
session in a browser (nothing to install there) — live data, standings, laps, radio — and act as the engineer:
confirm or discard the proposals and write to the AI engineer.

Off by default; when it is on it listens on every network card of the sim PC (port 8790 or the next free one).
Every /api call except the pairing needs the device token (header Authorization: Bearer), obtained once with the
rotating code (hub_core.remote.auth). No cookies (so no CSRF) and no CORS headers (other sites cannot read it).
Plain HTTP: meant for the home network; to reach it from outside use a VPN such as Tailscale, not port forwarding.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlparse

from hub_core.remote.auth import PairError, Pairing

DEFAULT_PORT = 8790
MAX_BODY = 16 * 1024
WEB_DIR = Path(__file__).resolve().parent / "web"
SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                               "script-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'",
}


class RemoteProvider(Protocol):
    def snapshot(self, since: int, laps_known: int) -> dict: ...
    def action(self, device: str, kind: str, payload: dict) -> dict: ...


def local_addresses() -> list[str]:
    """IPv4 addresses of the sim PC on the local network (the one with the default route first)."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))       # no packet is sent: it only picks the outgoing card
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
    except OSError:
        pass
    return [ip for ip in found if not ip.startswith("127.")] or ["127.0.0.1"]


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False         # Windows: True would let two hubs share the port

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class RemoteServer:
    def __init__(self, provider: RemoteProvider, pairing: Pairing, port: int = DEFAULT_PORT, host: str = "0.0.0.0"):
        self.provider = provider
        self.pairing = pairing
        self.port = port
        self.host = host
        self.error: str | None = None
        self._httpd: ThreadingHTTPServer | None = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def urls(self) -> list[str]:
        return [f"http://{ip}:{self.port}" for ip in local_addresses()]

    def start(self) -> bool:
        if self._httpd is not None:
            return True
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "DeltaSuite"
            sys_version = ""

            def log_message(self, *_):
                pass

            def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in {**SECURITY_HEADERS, **(extra or {})}.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code: int, data, extra: dict | None = None):
                self._send(code, json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"),
                           "application/json; charset=utf-8", extra)

            def _body(self) -> dict:
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    raise ValueError("request too large")
                data = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(data, dict):
                    raise ValueError("JSON object expected")
                return data

            def _device(self):
                auth = self.headers.get("Authorization", "")
                token = auth[7:] if auth.startswith("Bearer ") else None
                return server.pairing.check(token, self.client_address[0])

            def do_GET(self):
                url = urlparse(self.path)
                if url.path in ("/", "/index.html"):
                    try:
                        page = (WEB_DIR / "index.html").read_bytes()
                    except OSError:
                        return self._json(500, {"error": "web page missing from the installation"})
                    return self._send(200, page, "text/html; charset=utf-8")
                if url.path == "/api/hello":
                    return self._json(200, {"app": "Delta Suite", "paired": self._device() is not None})
                if url.path == "/api/state":
                    dev = self._device()
                    if dev is None:
                        return self._json(401, {"error": "not paired"})
                    q = parse_qs(url.query)
                    try:
                        since = int(q.get("since", ["0"])[0])
                        laps = int(q.get("laps", ["-1"])[0])
                    except ValueError:
                        since, laps = 0, -1
                    try:
                        return self._json(200, server.provider.snapshot(since, laps))
                    except Exception as exc:          # a half-updated hub must not kill the page
                        return self._json(503, {"error": f"{type(exc).__name__}: {exc}"})
                self._json(404, {"error": "not found"})

            def do_POST(self):
                path = urlparse(self.path).path
                try:
                    body = self._body()
                except (ValueError, OSError):
                    return self._json(400, {"error": "invalid request"})
                if path == "/api/pair":
                    try:
                        token = server.pairing.pair(str(body.get("code", "")), str(body.get("name", "")),
                                                    self.client_address[0])
                    except PairError as exc:
                        extra = {"Retry-After": str(int(exc.retry_after) + 1)} if exc.retry_after else None
                        return self._json(429 if exc.retry_after else 403,
                                          {"error": str(exc), "retry_after": round(exc.retry_after)}, extra)
                    return self._json(200, {"token": token})
                dev = self._device()
                if dev is None:
                    return self._json(401, {"error": "not paired"})
                if path == "/api/logout":
                    server.pairing.revoke(dev.id)
                    return self._json(200, {"ok": True})
                if path == "/api/action":
                    try:
                        res = server.provider.action(dev.name, str(body.get("kind", "")), body)
                    except Exception as exc:
                        res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                    return self._json(200, res)
                self._json(404, {"error": "not found"})

        for port in range(self.port, self.port + 20):
            try:
                self._httpd = _QuietServer((self.host, port), Handler)
                self.port = port
                break
            except OSError as exc:
                self.error = str(exc)
        if self._httpd is None:
            return False
        self.error = None
        threading.Thread(target=self._httpd.serve_forever, daemon=True, name="RemoteServer").start()
        return True

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
