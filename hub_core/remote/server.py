"""
Remote access: a small web server on the local network, so that another PC, a tablet or a phone can follow the
session in a browser (nothing to install there) — live data, standings, laps, radio — and act as the engineer:
confirm or discard the proposals and write to the AI engineer.

Off by default; when it is on it listens on every network card of the sim PC (port 8790 or the next free one).
Every /api call except the pairing needs the device token (header Authorization: Bearer), obtained once with the
rotating code (hub_core.remote.auth). No cookies (so no CSRF) and no CORS headers (other sites cannot read it).
Plain HTTP: meant for the home network; to reach it from outside use a VPN such as Tailscale, not port forwarding.
It listens on 0.0.0.0, so the same server answers on the LAN address (lowest latency) and on the Tailscale one
(100.64.0.0/10) with no extra setup.

The page is plain HTML/CSS/JS (web/), light enough for an old laptop. The onboard video is on demand: the page asks
for one JPEG frame at a time (/api/frame, long poll), only while it shows the video; the hub renders it in AC only
while those requests keep coming (see ui/remote_data.py).
"""

from __future__ import annotations

import ipaddress
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
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/index.html": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/app.css": ("app.css", "text/css; charset=utf-8")}
FRAME_WAIT_S = 1.0          # /api/frame waits at most this long for a new frame
TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")
SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                               "script-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; "
                               "connect-src 'self'; frame-ancestors 'none'",
}


class RemoteProvider(Protocol):
    def snapshot(self, since: int, laps_known: int) -> dict: ...
    def action(self, device: str, kind: str, payload: dict) -> dict: ...
    # optional (without them the endpoints answer 404): onboard frames, data on request, radio audio
    #   video_frame(camera, car, quality, after, wait_s) -> {"seq", "jpeg"} or {"status"}
    #   data(name) -> dict | None
    #   audio(seq) -> bytes | None


def _outgoing_ip(target: str) -> str | None:
    """Address of the card that would reach `target` (no packet is sent: it only picks the route)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((target, 1))
            return s.getsockname()[0]
    except OSError:
        return None


def address_kind(ip: str) -> str:
    """"tailscale" (100.64.0.0/10) or "lan" (any other card: home router, campus network, ...)."""
    try:
        return "tailscale" if ipaddress.ip_address(ip) in TAILSCALE_NET else "lan"
    except ValueError:
        return "lan"


def network_addresses() -> list[tuple[str, str]]:
    """(kind, IPv4) of the sim PC: LAN first (the default route first), then Tailscale."""
    found: list[str] = []
    for target in ("10.255.255.255", "100.100.100.100"):     # default route; Tailscale's own service address
        ip = _outgoing_ip(target)
        if ip and ip not in found:
            found.append(ip)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            if info[4][0] not in found:
                found.append(info[4][0])
    except OSError:
        pass
    out = [(address_kind(ip), ip) for ip in found if not ip.startswith(("127.", "169.254.", "0."))]
    return sorted(out, key=lambda kv: kv[0] != "lan") or [("lan", "127.0.0.1")]


def local_addresses() -> list[str]:
    """IPv4 addresses of the sim PC (LAN first, then Tailscale)."""
    return [ip for _kind, ip in network_addresses()]


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

    def labelled_urls(self) -> list[tuple[str, str]]:
        """(kind, url): kind "lan" or "tailscale"."""
        return [(kind, f"http://{ip}:{self.port}") for kind, ip in network_addresses()]

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
                if url.path in STATIC:
                    file, ctype = STATIC[url.path]
                    try:
                        page = (WEB_DIR / file).read_bytes()
                    except OSError:
                        return self._json(500, {"error": "web page missing from the installation"})
                    return self._send(200, page, ctype)
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
                if url.path.startswith("/api/"):
                    if self._device() is None:
                        return self._json(401, {"error": "not paired"})
                    q = {k: v[0] for k, v in parse_qs(url.query).items()}
                    try:
                        return self._get_api(url.path, q)
                    except (ValueError, KeyError) as exc:
                        return self._json(400, {"error": str(exc) or "invalid request"})
                    except Exception as exc:
                        return self._json(503, {"error": f"{type(exc).__name__}: {exc}"})
                self._json(404, {"error": "not found"})

            def _get_api(self, path: str, q: dict):
                if path == "/api/frame":
                    fn = getattr(server.provider, "video_frame", None)
                    if fn is None:
                        return self._json(404, {"error": "not available"})
                    res = fn(int(q.get("cam", 0)), int(q.get("car", -1)), int(q.get("q", 1)),
                             int(q.get("after", 0)), FRAME_WAIT_S)
                    if res.get("jpeg"):
                        return self._send(200, res["jpeg"], "image/jpeg", {"X-Frame-Seq": str(res["seq"])})
                    return self._json(200, {"status": res.get("status", "")})
                if path.startswith("/api/data/"):
                    fn = getattr(server.provider, "data", None)
                    out = fn(path[len("/api/data/"):]) if fn is not None else None
                    if out is None:
                        return self._json(404, {"error": "not available"})
                    return self._json(200, out)
                if path == "/api/audio":
                    fn = getattr(server.provider, "audio", None)
                    wav = fn(int(q.get("seq", 0))) if fn is not None else None
                    if not wav:
                        return self._json(404, {"error": "audio no longer available"})
                    return self._send(200, wav, "audio/wav")
                return self._json(404, {"error": "not found"})

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
