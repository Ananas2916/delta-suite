"""
MCP server (Streamable HTTP, JSON responses only) exposing Delta Suite data to agents:
Claude Code, Codex, Antigravity or any MCP client.

It listens on 127.0.0.1 only and requires the token generated at every start (Authorization header),
so neither other programs nor web pages open in the browser can use it.
"""

from __future__ import annotations

import json
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

SERVER_NAME = "deltasuite"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


class DataProvider(Protocol):
    def live_state(self) -> dict: ...
    def session_laps(self, session_id: int | None) -> dict: ...
    def compare_laps(self, ref_lap: int, other_lap: int, session_id: int | None) -> dict: ...
    def current_setup(self) -> dict: ...
    def standings(self) -> dict: ...
    def sessions(self) -> list[dict]: ...
    def propose(self, kind: str, value: float, name: str, reason: str) -> dict: ...


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


TOOLS: list[dict] = [
    {
        "name": "live_state",
        "description": "Current state of the car on track: speed, gear, fuel, tyres (temperature °C, "
                       "pressure psi, wear % where 100 = new) and brakes per wheel [FL, FR, RL, RR], lap and "
                       "sector, track conditions, cockpit adjustments (brake bias, ABS, TC, engine brake), "
                       "car status (damage per zone, tyre dirt, suspension travel, alerts).",
        "inputSchema": _obj({}),
    },
    {
        "name": "session_laps",
        "description": "Session laps with times, sectors, validity, fuel use, tyre and brake averages, plus "
                       "strategy analysis: average fuel use, ideal lap, tyre degradation forecast. Without "
                       "session_id it uses the live session.",
        "inputSchema": _obj({"session_id": {"type": "integer", "description": "id from session_archive"}}),
    },
    {
        "name": "compare_laps",
        "description": "Corner-by-corner comparison of two laps (corners detected automatically): time "
                       "lost, braking point, minimum speed, throttle pick-up. Use it to tell the driver "
                       "where and why they lose time.",
        "inputSchema": _obj({
            "reference_lap": {"type": "integer", "description": "reference lap number"},
            "compared_lap": {"type": "integer", "description": "number of the lap to compare"},
            "session_id": {"type": "integer"},
        }, ["reference_lap", "compared_lap"]),
    },
    {
        "name": "current_setup",
        "description": "Current car setup: every item with internal name, value in clicks, value shown "
                       "in game, units, limits and step; says whether it can be edited now (pits only).",
        "inputSchema": _obj({}),
    },
    {
        "name": "standings",
        "description": "Live standings with gap to the leader and interval to the car ahead (needs the CSP app).",
        "inputSchema": _obj({}),
    },
    {
        "name": "session_archive",
        "description": "Sessions saved in the archive (id, car, track, laps, best lap).",
        "inputSchema": _obj({}),
    },
    {
        "name": "propose_change",
        "description": "Proposes a change to the driver: it is not applied until they confirm (wheel button "
                       "or hub button). kind: brake_bias (value 0-1, front share), abs, tc, "
                       "engine_brake (game integer values), setup (name = internal name of the "
                       "current_setup item, value = clicks). Setup changes only apply in the pits.",
        "inputSchema": _obj({
            "kind": {"type": "string", "enum": ["brake_bias", "abs", "tc", "engine_brake", "setup"]},
            "value": {"type": "number"},
            "name": {"type": "string", "description": "only for kind=setup"},
            "reason": {"type": "string", "description": "short explanation, read to the driver"},
        }, ["kind", "value", "reason"]),
    },
]


def _call_tool(provider: DataProvider, name: str, args: dict) -> Any:
    if name == "live_state":
        return provider.live_state()
    if name == "session_laps":
        return provider.session_laps(args.get("session_id"))
    if name == "compare_laps":
        return provider.compare_laps(int(args["reference_lap"]), int(args["compared_lap"]),
                                     args.get("session_id"))
    if name == "current_setup":
        return provider.current_setup()
    if name == "standings":
        return provider.standings()
    if name == "session_archive":
        return provider.sessions()
    if name == "propose_change":
        return provider.propose(str(args["kind"]), float(args["value"]), str(args.get("name") or ""),
                                str(args.get("reason") or ""))
    raise KeyError(name)


def handle_rpc(provider: DataProvider, msg: dict) -> dict | None:
    """Handle a JSON-RPC message; None for notifications (no reply)."""
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code, text):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}

    if method == "initialize":
        asked = (msg.get("params") or {}).get("protocolVersion")
        return ok({
            "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": "1.0"},
            "instructions": "Telemetry, strategy and setup data from Delta Suite (Assetto Corsa). "
                            "Changes are proposed with propose_change and the driver confirms them.",
        })
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name", "")
        try:
            data = _call_tool(provider, name, params.get("arguments") or {})
        except KeyError as exc:
            if str(exc).strip("'") == name:
                return err(-32602, f"unknown tool: {name}")
            return ok({"content": [{"type": "text", "text": f"Missing parameter: {exc}"}], "isError": True})
        except Exception as exc:
            return ok({"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}], "isError": True})
        text = json.dumps(data, ensure_ascii=False, default=str)
        return ok({"content": [{"type": "text", "text": text}], "isError": False})
    return err(-32601, f"unsupported method: {method}")


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # clients close keep-alive connections without notice: not an error
        if isinstance(sys.exc_info()[1], (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class MCPServer:
    def __init__(self, provider: DataProvider, port: int = 8787):
        self.provider = provider
        self.token = secrets.token_urlsafe(24)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port = port
        self.error: str | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    def start(self) -> bool:
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_):
                pass

            def _send(self, code: int, body: dict | list | None = None, extra: dict | None = None):
                data = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                if body is not None:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if data:
                    self.wfile.write(data)

            def _authorized(self) -> bool:
                origin = self.headers.get("Origin")
                if origin and not origin.startswith(("http://127.0.0.1", "http://localhost")):
                    return False
                return secrets.compare_digest(self.headers.get("Authorization", ""), f"Bearer {server.token}")

            def do_POST(self):
                if self.path.split("?")[0] != "/mcp":
                    return self._send(404, {"error": "not found"})
                if not self._authorized():
                    return self._send(401, {"error": "missing or wrong token"})
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    payload = json.loads(self.rfile.read(length) or b"null")
                except (ValueError, OSError):
                    return self._send(400, {"jsonrpc": "2.0", "id": None,
                                            "error": {"code": -32700, "message": "invalid JSON"}})
                msgs = payload if isinstance(payload, list) else [payload]
                replies = [r for m in msgs if isinstance(m, dict) for r in [handle_rpc(server.provider, m)] if r]
                headers = {}
                if any(isinstance(m, dict) and m.get("method") == "initialize" for m in msgs):
                    headers["Mcp-Session-Id"] = secrets.token_hex(8)
                if not replies:
                    return self._send(202, None, headers)
                self._send(200, replies if isinstance(payload, list) else replies[0], headers)

            def do_GET(self):
                self._send(405, {"error": "no SSE stream: use POST"}, {"Allow": "POST"})

            def do_DELETE(self):
                self._send(200, {})

        for port in range(self.port, self.port + 20):
            try:
                self._httpd = _QuietServer(("127.0.0.1", port), Handler)
                self.port = port
                break
            except OSError as exc:
                self.error = str(exc)
        if self._httpd is None:
            return False
        self.error = None
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="MCPServer")
        self._thread.start()
        return True

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def client_config(self) -> dict:
        """Configuration for Claude Code's --mcp-config (and the mcpServers format in general)."""
        return {"mcpServers": {SERVER_NAME: {"type": "http", "url": self.url,
                                             "headers": {"Authorization": f"Bearer {self.token}"}}}}
