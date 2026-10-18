"""
Server MCP (Streamable HTTP, solo risposte JSON) che espone i dati di Delta Suite agli agenti:
Claude Code, Codex, Antigravity o qualunque client MCP.

Ascolta solo su 127.0.0.1 e richiede il token generato a ogni avvio (header Authorization),
così né altri programmi né pagine web aperte nel browser possono usarlo.
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
        "name": "stato_live",
        "description": "Stato attuale della vettura in pista: velocità, marcia, carburante, gomme (temperatura "
                       "°C, pressione psi, usura % dove 100 = nuova) e freni per ruota [AS, AD, PS, PD], giro e "
                       "settore, condizioni pista, regolazioni di abitacolo (bias freni, ABS, TC, freno motore), "
                       "stato vettura (danni per zona, sporco gomme, corsa sospensioni, avvisi).",
        "inputSchema": _obj({}),
    },
    {
        "name": "giri_sessione",
        "description": "Giri della sessione con tempi, settori, validità, consumo, medie gomme e freni, più "
                       "analisi di strategia: consumo medio, giro ideale, previsione degrado gomme. Senza "
                       "session_id usa la sessione live.",
        "inputSchema": _obj({"session_id": {"type": "integer", "description": "id da archivio_sessioni"}}),
    },
    {
        "name": "confronta_giri",
        "description": "Confronto curva per curva tra due giri (curve riconosciute automaticamente): tempo "
                       "perso, punto di frenata, velocità minima, ripresa del gas. Usalo per dire al pilota "
                       "dove e perché perde tempo.",
        "inputSchema": _obj({
            "giro_riferimento": {"type": "integer", "description": "numero del giro di riferimento"},
            "giro_confronto": {"type": "integer", "description": "numero del giro da confrontare"},
            "session_id": {"type": "integer"},
        }, ["giro_riferimento", "giro_confronto"]),
    },
    {
        "name": "setup_attuale",
        "description": "Setup attuale della vettura: ogni voce con nome interno, valore in click, valore "
                       "mostrato in gioco, unità, limiti e passo; indica se ora è modificabile (solo ai box).",
        "inputSchema": _obj({}),
    },
    {
        "name": "classifica",
        "description": "Classifica live con gap dal leader e interval dall'auto davanti (richiede l'app CSP).",
        "inputSchema": _obj({}),
    },
    {
        "name": "archivio_sessioni",
        "description": "Sessioni salvate in archivio (id, auto, pista, giri, miglior giro).",
        "inputSchema": _obj({}),
    },
    {
        "name": "proponi_modifica",
        "description": "Propone al pilota una modifica: non viene applicata finché lui non conferma (tasto al "
                       "volante o pulsante nell'hub). tipo: bias_freni (valore 0-1, quota anteriore), abs, tc, "
                       "freno_motore (valori interi del gioco), setup (nome = nome interno della voce di "
                       "setup_attuale, valore = click). Le modifiche di setup si applicano solo ai box.",
        "inputSchema": _obj({
            "tipo": {"type": "string", "enum": ["bias_freni", "abs", "tc", "freno_motore", "setup"]},
            "valore": {"type": "number"},
            "nome": {"type": "string", "description": "solo per tipo=setup"},
            "motivo": {"type": "string", "description": "spiegazione breve, letta al pilota"},
        }, ["tipo", "valore", "motivo"]),
    },
]


def _call_tool(provider: DataProvider, name: str, args: dict) -> Any:
    if name == "stato_live":
        return provider.live_state()
    if name == "giri_sessione":
        return provider.session_laps(args.get("session_id"))
    if name == "confronta_giri":
        return provider.compare_laps(int(args["giro_riferimento"]), int(args["giro_confronto"]),
                                     args.get("session_id"))
    if name == "setup_attuale":
        return provider.current_setup()
    if name == "classifica":
        return provider.standings()
    if name == "archivio_sessioni":
        return provider.sessions()
    if name == "proponi_modifica":
        return provider.propose(str(args["tipo"]), float(args["valore"]), str(args.get("nome") or ""),
                                str(args.get("motivo") or ""))
    raise KeyError(name)


def handle_rpc(provider: DataProvider, msg: dict) -> dict | None:
    """Gestisce un messaggio JSON-RPC; None per le notifiche (nessuna risposta)."""
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
            "instructions": "Dati di telemetria, strategia e setup di Delta Suite (Assetto Corsa). "
                            "Le modifiche si propongono con proponi_modifica e le conferma il pilota.",
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
                return err(-32602, f"strumento sconosciuto: {name}")
            return ok({"content": [{"type": "text", "text": f"Parametro mancante: {exc}"}], "isError": True})
        except Exception as exc:
            return ok({"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}], "isError": True})
        text = json.dumps(data, ensure_ascii=False, default=str)
        return ok({"content": [{"type": "text", "text": text}], "isError": False})
    return err(-32601, f"metodo non supportato: {method}")


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # i client chiudono le connessioni keep-alive senza preavviso: non è un errore
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
                    return self._send(401, {"error": "token mancante o errato"})
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    payload = json.loads(self.rfile.read(length) or b"null")
                except (ValueError, OSError):
                    return self._send(400, {"jsonrpc": "2.0", "id": None,
                                            "error": {"code": -32700, "message": "JSON non valido"}})
                msgs = payload if isinstance(payload, list) else [payload]
                replies = [r for m in msgs if isinstance(m, dict) for r in [handle_rpc(server.provider, m)] if r]
                headers = {}
                if any(isinstance(m, dict) and m.get("method") == "initialize" for m in msgs):
                    headers["Mcp-Session-Id"] = secrets.token_hex(8)
                if not replies:
                    return self._send(202, None, headers)
                self._send(200, replies if isinstance(payload, list) else replies[0], headers)

            def do_GET(self):
                self._send(405, {"error": "nessuno stream SSE: usare POST"}, {"Allow": "POST"})

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
        """Configurazione per --mcp-config di Claude Code (e formato mcpServers in generale)."""
        return {"mcpServers": {SERVER_NAME: {"type": "http", "url": self.url,
                                             "headers": {"Authorization": f"Bearer {self.token}"}}}}
