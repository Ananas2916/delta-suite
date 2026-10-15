"""
Ingegnere di pista tramite agenti a riga di comando (abbonamento invece di chiave API).

Claude Code è il backend principale: modalità -p con output stream-json, sessione ripresa con
--resume, nessuno strumento integrato (niente comandi o file), solo gli strumenti MCP di Delta Suite.
Codex e Antigravity usano la stessa idea con i loro comandi non interattivi.
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

ENGINEER_PROMPT = """Sei l'ingegnere di pista di un pilota che corre in Assetto Corsa (simulatore con fisica \
realistica). Lavori come al muretto di un team GT/WEC: asciutto, preciso, in italiano.

Dati: li leggi SOLO dagli strumenti MCP "deltasuite" (stato_live, giri_sessione, confronta_giri, \
setup_attuale, classifica, archivio_sessioni). Non inventare numeri: se un dato non c'è, dillo. \
Ordine ruote: anteriore sinistra, anteriore destra, posteriore sinistra, posteriore destra. \
Pressioni in psi a caldo, temperature in gradi, usura in % (100 = gomma nuova).

Modifiche: non cambi nulla direttamente. Usi proponi_modifica (bias freni, ABS, TC, freno motore, \
voci di setup con il loro nome interno e valore in click); il pilota conferma con un tasto al volante. \
Le voci di setup si applicano solo ai box: proponile comunque se servono.

Il messaggio inizia con la modalità e la lingua, es. "[RADIO] [English]": rispondi SEMPRE in quella lingua (è la lingua della voce che il pilota ha scelto), anche se la domanda è scritta in un'altra.
Modalità:
[RADIO] il pilota sta guidando e ti sente in cuffia: al massimo due frasi brevi, parlate, senza \
elenchi, simboli, markdown o abbreviazioni (scrivi "gradi", "psi", "decimi"). Numeri arrotondati. \
Prima il dato più utile adesso.
[ANALISI] il pilota è fermo e legge: risposta completa in markdown, cita i dati che giustificano \
ogni raccomandazione, chiudi con le azioni in ordine di priorità."""

BACKENDS = {
    "claude": "Claude Code (abbonamento)",
    "codex": "Codex CLI (non verificato)",
    "antigravity": "Antigravity CLI (non verificato)",
    "custom": "Comando personalizzato",
    "api": "API Anthropic (chiave)",
}

CREATE_NO_WINDOW = 0x08000000


def engineer_workdir() -> Path:
    d = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DeltaSuite" / "engineer"
    d.mkdir(parents=True, exist_ok=True)
    # istruzioni anche come file di progetto, per gli agenti che li leggono (Codex, Antigravity)
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
    """Una conversazione con l'agente scelto; ask() è bloccante (chiamarla da un thread)."""

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

    # ------------------------------------------------------------ comandi
    def _mcp_file(self) -> Path:
        p = self.workdir / "mcp.json"
        p.write_text(json.dumps(self.mcp_config, indent=2), encoding="utf-8")
        return p

    def command(self) -> tuple[list[str], bool, dict]:
        """(argv, prompt_da_stdin, env aggiuntive)."""
        server = self.mcp_config["mcpServers"]["deltasuite"]
        token = server["headers"]["Authorization"].split(" ", 1)[1]
        if self.backend == "claude":
            exe = find_executable("claude")
            if not exe:
                raise AgentError("Claude Code non trovato: installalo e fai il login con `claude`")
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
                raise AgentError("Codex CLI non trovato")
            cmd = [exe, "exec", "--skip-git-repo-check",
                   "-c", f'mcp_servers.deltasuite.url="{server["url"]}"',
                   "-c", 'mcp_servers.deltasuite.bearer_token_env_var="DELTASUITE_MCP_TOKEN"']
            if self.model:
                cmd += ["-m", self.model]
            return cmd + ["-"], True, {"DELTASUITE_MCP_TOKEN": token}
        if self.backend == "antigravity":
            exe = find_executable("agy") or find_executable("antigravity")
            if not exe:
                raise AgentError("Antigravity CLI (agy) non trovato")
            # l'MCP va configurato in ~/.gemini/config/mcp_config.json (pulsante "Copia configurazione MCP")
            return [exe, "-p", "{prompt}"], False, {}
        if self.backend == "custom":
            if not self.custom_command.strip():
                raise AgentError("Comando personalizzato vuoto")
            parts = shlex.split(self.custom_command, posix=False)
            return parts, "{prompt}" not in parts, {"DELTASUITE_MCP_URL": server["url"], "DELTASUITE_MCP_TOKEN": token}
        raise AgentError(f"backend sconosciuto: {self.backend}")

    # --------------------------------------------------------------- chiamata
    def ask(self, text: str, mode: str = "ANALISI", on_text: Callable[[str], None] | None = None,
            timeout_s: float = 600.0, language: str = "italiano") -> str:
        prompt = f"[{mode}] [{language}] {text}"
        cmd, via_stdin, extra_env = self.command()
        if not via_stdin:
            cmd = [prompt if a == "{prompt}" else a for a in cmd]
        env = {**os.environ, **extra_env}
        env.pop("CLAUDECODE", None)     # se l'hub è lanciato da dentro Claude Code
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
            raise AgentError(err[-800:] or f"l'agente è uscito con codice {proc.returncode}")
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
                    on_text("\n\n")      # nuovo messaggio dopo una chiamata a strumento
            elif kind == "result":
                self.session_id = ev.get("session_id") or self.session_id
                if ev.get("is_error"):
                    raise AgentError(str(ev.get("result") or ev.get("subtype") or "errore dell'agente"))
                result = ev.get("result") or ""
        return result


class APIAgent:
    """Adattatore del RaceEngineer via API alla stessa interfaccia (usa il riepilogo dello stint)."""

    def __init__(self, engineer, summary_provider: Callable[[], str]):
        self.engineer = engineer
        self.summary_provider = summary_provider
        self._sent = False

    def reset(self):
        self.engineer.reset()
        self._sent = False

    def cancel(self):
        pass

    def ask(self, text: str, mode: str = "ANALISI", on_text=None, timeout_s: float = 600.0,
            language: str = "italiano") -> str:
        summary = None if self._sent else self.summary_provider()
        self._sent = True
        return self.engineer.ask(f"[{mode}] [{language}] {text}", summary, on_text=on_text)
