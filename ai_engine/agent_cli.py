"""
Race engineer through command-line agents (subscription instead of an API key).

Claude Code is the main backend: -p mode with stream-json output, session resumed with
--resume, no built-in tools (no commands or files), only Delta Suite's MCP tools.
Codex and Antigravity use the same idea with their non-interactive commands.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

ENGINEER_PROMPT = """You are the race engineer of a driver racing in Assetto Corsa (a simulator with realistic \
physics). You work like on the pit wall of a GT/WEC team: dry, precise.

Data: you read it ONLY from the "deltasuite" MCP tools (live_state, session_laps, compare_laps, \
current_setup, standings, session_archive). Never make numbers up: if a piece of data is missing, say so. \
Wheel order: front left, front right, rear left, rear right. \
Hot pressures in psi, temperatures in degrees, wear in % (100 = new tyre).

Changes: you never change anything directly. You use propose_change (brake bias, ABS, TC, engine brake, \
setup items with their internal name and value in clicks); the driver confirms with a wheel button. \
Setup items only apply in the pits: propose them anyway if needed.

The message starts with the mode and the language, e.g. "[RADIO] [English]": ALWAYS reply in that language (it is the language of the voice the driver chose), even if the question is written in another one.
Modes:
[RADIO] the driver is driving and hears you in the headset: two short spoken sentences at most, no \
lists, symbols, markdown or abbreviations (write "degrees", "psi", "tenths"). Rounded numbers. \
The most useful piece of information right now first.
[ANALYSIS] the driver is stopped and reading: a complete markdown answer, quote the data behind \
every recommendation, finish with the actions in order of priority."""

BACKENDS = {
    "claude": "Claude Code (subscription)",
    "codex": "Codex CLI (untested)",
    "antigravity": "Antigravity CLI (untested)",
    "custom": "Custom command",
    "api": "Anthropic API (key)",
}

CREATE_NO_WINDOW = 0x08000000


def engineer_workdir() -> Path:
    d = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DeltaSuite" / "engineer"
    d.mkdir(parents=True, exist_ok=True)
    # instructions also as project files, for the agents that read them (Codex, Antigravity)
    for name in ("AGENTS.md", "GEMINI.md"):
        p = d / name
        if not p.is_file() or p.read_text(encoding="utf-8") != ENGINEER_PROMPT:
            p.write_text(ENGINEER_PROMPT, encoding="utf-8")
    return d


def find_executable(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for cand in (Path.home() / ".local" / "bin" / f"{name}.exe",
                 Path(os.environ.get("APPDATA", "")) / "npm" / f"{name}.cmd"):
        if cand.is_file():
            return str(cand)
    return None


class AgentError(RuntimeError):
    pass


class CLIAgent:
    """A conversation with the chosen agent; ask() blocks (call it from a thread)."""

    def __init__(self, backend: str, mcp_config: dict, custom_command: str = "", model: str = ""):
        self.backend = backend
        self.mcp_config = mcp_config
        self.custom_command = custom_command
        self.model = model
        self.session_id: str | None = None
        self._proc: subprocess.Popen | None = None
        self.workdir = engineer_workdir()

    def reset(self) -> None:
        self.session_id = None

    def cancel(self) -> None:
        p = self._proc
        if p is not None and p.poll() is None:
            p.kill()

    # ------------------------------------------------------------ commands
    def _mcp_file(self) -> Path:
        p = self.workdir / "mcp.json"
        p.write_text(json.dumps(self.mcp_config, indent=2), encoding="utf-8")
        return p

    def command(self) -> tuple[list[str], bool, dict]:
        """(argv, prompt_via_stdin, extra env)."""
        server = self.mcp_config["mcpServers"]["deltasuite"]
        token = server["headers"]["Authorization"].split(" ", 1)[1]
        if self.backend == "claude":
            exe = find_executable("claude")
            if not exe:
                raise AgentError("Claude Code not found: install it and log in with `claude`")
            cmd = [exe, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                   "--mcp-config", str(self._mcp_file()), "--strict-mcp-config",
                   "--tools", "", "--allowedTools", "mcp__deltasuite",
                   "--permission-mode", "dontAsk", "--append-system-prompt", ENGINEER_PROMPT]
            if self.model:
                cmd += ["--model", self.model]
            if self.session_id:
                cmd += ["--resume", self.session_id]
            return cmd, True, {}
        if self.backend == "codex":
            exe = find_executable("codex")
            if not exe:
                raise AgentError("Codex CLI not found")
            cmd = [exe, "exec", "--skip-git-repo-check",
                   "-c", f'mcp_servers.deltasuite.url="{server["url"]}"',
                   "-c", 'mcp_servers.deltasuite.bearer_token_env_var="DELTASUITE_MCP_TOKEN"']
            if self.model:
                cmd += ["-m", self.model]
            return cmd + ["-"], True, {"DELTASUITE_MCP_TOKEN": token}
        if self.backend == "antigravity":
            exe = find_executable("agy") or find_executable("antigravity")
            if not exe:
                raise AgentError("Antigravity CLI (agy) not found")
            # the MCP must be configured in ~/.gemini/config/mcp_config.json ("Copy MCP configuration" button)
            return [exe, "-p", "{prompt}"], False, {}
        if self.backend == "custom":
            if not self.custom_command.strip():
                raise AgentError("Custom command is empty")
            parts = shlex.split(self.custom_command, posix=False)
            return parts, "{prompt}" not in parts, {"DELTASUITE_MCP_URL": server["url"], "DELTASUITE_MCP_TOKEN": token}
        raise AgentError(f"unknown backend: {self.backend}")

    # --------------------------------------------------------------- call
    def ask(self, text: str, mode: str = "ANALYSIS", on_text: Callable[[str], None] | None = None,
            timeout_s: float = 600.0, language: str = "English") -> str:
        prompt = f"[{mode}] [{language}] {text}"
        cmd, via_stdin, extra_env = self.command()
        if not via_stdin:
            cmd = [prompt if a == "{prompt}" else a for a in cmd]
        env = {**os.environ, **extra_env}
        env.pop("CLAUDECODE", None)     # if the hub is launched from inside Claude Code
        self._proc = proc = subprocess.Popen(
            cmd, cwd=self.workdir, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
        timer = threading.Timer(timeout_s, proc.kill)
        timer.start()
        err_chunks: list[bytes] = []
        threading.Thread(target=lambda: err_chunks.append(proc.stderr.read()), daemon=True).start()
        try:
            if via_stdin:
                proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.close()
            if self.backend == "claude":
                result = self._read_claude(proc, on_text)
            else:
                out = proc.stdout.read().decode("utf-8", errors="replace").strip()
                if on_text and out:
                    on_text(out)
                result = out
            proc.wait()
        finally:
            timer.cancel()
            self._proc = None
        if proc.returncode not in (0, None) and not result:
            err = b"".join(err_chunks).decode("utf-8", errors="replace").strip()
            raise AgentError(err[-800:] or f"the agent exited with code {proc.returncode}")
        return result

    def _read_claude(self, proc: subprocess.Popen, on_text) -> str:
        result, streamed = "", False
        for raw in proc.stdout:
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            kind = ev.get("type")
            if kind == "system" and ev.get("subtype") == "init":
                self.session_id = ev.get("session_id") or self.session_id
            elif kind == "stream_event":
                e = ev.get("event") or {}
                d = e.get("delta") or {}
                if e.get("type") == "content_block_delta" and d.get("type") == "text_delta" and on_text:
                    on_text(d.get("text", ""))
                    streamed = True
                elif e.get("type") == "message_start" and streamed and on_text:
                    on_text("\n\n")      # new message after a tool call
            elif kind == "result":
                self.session_id = ev.get("session_id") or self.session_id
                if ev.get("is_error"):
                    raise AgentError(str(ev.get("result") or ev.get("subtype") or "agent error"))
                result = ev.get("result") or ""
        return result


class APIAgent:
    """Adapter of the API RaceEngineer to the same interface (uses the stint summary)."""

    def __init__(self, engineer, summary_provider: Callable[[], str]):
        self.engineer = engineer
        self.summary_provider = summary_provider
        self._sent = False

    def reset(self):
        self.engineer.reset()
        self._sent = False

    def cancel(self):
        pass

    def ask(self, text: str, mode: str = "ANALYSIS", on_text=None, timeout_s: float = 600.0,
            language: str = "English") -> str:
        summary = None if self._sent else self.summary_provider()
        self._sent = True
        return self.engineer.ask(f"[{mode}] [{language}] {text}", summary, on_text=on_text)
