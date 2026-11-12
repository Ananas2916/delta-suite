import io
import json
import urllib.error
import urllib.request

import pytest

from ai_engine.agent_cli import CLIAgent
from ai_engine.mcp_server import MCPServer, handle_rpc


class FakeProvider:
    def live_state(self): return {"fuel_l": 24.1}
    def session_laps(self, sid): return {"laps": [], "sid": sid}
    def compare_laps(self, a, b, sid): return {"a": a, "b": b}
    def current_setup(self): return {"items": []}
    def standings(self): return {}
    def sessions(self): return []
    def propose(self, kind, value, name, reason): return {"accepted": True, "kind": kind, "value": value}


def rpc(method, params=None, mid=1):
    return {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}


def test_handshake_and_tools():
    p = FakeProvider()
    init = handle_rpc(p, rpc("initialize", {"protocolVersion": "2025-06-18"}))
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert handle_rpc(p, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = [t["name"] for t in handle_rpc(p, rpc("tools/list"))["result"]["tools"]]
    assert {"live_state", "session_laps", "compare_laps", "current_setup", "propose_change"} <= set(names)
    res = handle_rpc(p, rpc("tools/call", {"name": "compare_laps",
                                           "arguments": {"reference_lap": 3, "compared_lap": 5}}))
    assert json.loads(res["result"]["content"][0]["text"]) == {"a": 3, "b": 5}
    missing = handle_rpc(p, rpc("tools/call", {"name": "compare_laps", "arguments": {}}))
    assert missing["result"]["isError"]
    assert handle_rpc(p, rpc("tools/call", {"name": "nope"}))["error"]["code"] == -32602


def _post(url, body, token=None, origin=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(url, json.dumps(body).encode(), headers, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.read()


def test_http_requires_token_and_local_origin():
    srv = MCPServer(FakeProvider(), 18787)
    assert srv.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            _post(srv.url, rpc("tools/list"))
        assert e.value.code == 401
        with pytest.raises(urllib.error.HTTPError) as e:
            _post(srv.url, rpc("tools/list"), srv.token, origin="https://evil-site.example")
        assert e.value.code == 401
        code, body = _post(srv.url, rpc("tools/call", {"name": "live_state"}), srv.token)
        assert code == 200
        assert json.loads(json.loads(body)["result"]["content"][0]["text"]) == {"fuel_l": 24.1}
        code, body = _post(srv.url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, srv.token)
        assert code == 202 and body == b""
        cfg = srv.client_config()["mcpServers"]["deltasuite"]
        assert cfg["url"] == srv.url and cfg["headers"]["Authorization"] == f"Bearer {srv.token}"
    finally:
        srv.stop()


def test_claude_command_has_no_builtin_tools(monkeypatch):
    monkeypatch.setattr("ai_engine.agent_cli.find_executable", lambda n: f"C:/bin/{n}.exe")
    cfg = {"mcpServers": {"deltasuite": {"type": "http", "url": "http://127.0.0.1:1/mcp",
                                         "headers": {"Authorization": "Bearer abc"}}}}
    a = CLIAgent("claude", cfg)
    cmd, stdin, _ = a.command()
    assert stdin
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--allowedTools") + 1] == "mcp__deltasuite"
    assert "--strict-mcp-config" in cmd and "--resume" not in cmd
    a.session_id = "s1"
    cmd, _, _ = a.command()
    assert cmd[cmd.index("--resume") + 1] == "s1"
    custom_cmd, stdin, env = CLIAgent("custom", cfg, "my_agent.exe --ask {prompt}").command()
    assert env["DELTASUITE_MCP_TOKEN"] == "abc" and env["DELTASUITE_MCP_URL"].endswith("/mcp")
    assert custom_cmd == ["my_agent.exe", "--ask", "{prompt}"] and not stdin


def test_claude_stream_parsing():
    lines = [
        {"type": "system", "subtype": "init", "session_id": "abc"},
        {"type": "stream_event", "event": {"type": "message_start"}},
        {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Eight "}}},
        {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "laps."}}},
        {"type": "result", "subtype": "success", "is_error": False, "result": "Eight laps.", "session_id": "abc"},
    ]

    class P:
        stdout = io.BytesIO("\n".join(json.dumps(x) for x in lines).encode())

    a = CLIAgent.__new__(CLIAgent)
    a.session_id = None
    chunks = []
    assert a._read_claude(P, chunks.append) == "Eight laps."
    assert "".join(chunks) == "Eight laps."
    assert a.session_id == "abc"
