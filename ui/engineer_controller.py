"""The AI engineer: one agent (Claude Code, API or custom command) for the written chat and the radio."""

from __future__ import annotations

from ai_engine.agent_cli import BACKENDS, APIAgent, CLIAgent
from ai_engine.voice import PRIO_HIGH, PRIO_NORMAL
from ui.workers import Job


class EngineerController:
    """Owned by HubState: it emits hub.engineer_started/_text/_done/_failed."""

    def __init__(self, hub):
        self.hub = hub
        self.agent = None
        self._job: Job | None = None
        self._job_mode = "ANALYSIS"

    def _make_agent(self):
        h = self.hub
        backend = h.setting("engineer/backend", "claude")
        if backend not in BACKENDS:     # e.g. "codex"/"antigravity", removed in 0.6.0
            backend = "claude"
        if backend == "api":
            from ai_engine.race_engineer_agent import RaceEngineer, build_stint_summary
            key = h.setting("api_key", "") or None
            return APIAgent(RaceEngineer(key), lambda: build_stint_summary(
                h.session_info, h.laps, h.last_sample.fuel if h.last_sample else None))
        return CLIAgent(backend, h.mcp.client_config(), h.setting("engineer/custom_cmd", ""),
                        h.setting("engineer/model", ""))

    @property
    def busy(self) -> bool:
        return self._job is not None and self._job.isRunning()

    def written_language(self) -> str:
        """The written analysis follows the interface language; the radio follows the voice."""
        return self.hub.ui_language_name

    def ask(self, question: str, mode: str = "ANALYSIS") -> bool:
        question = question.strip()
        if not question or self.busy:
            return False
        h = self.hub
        if self.agent is None:
            try:
                self.agent = self._make_agent()
            except Exception as exc:
                h.engineer_failed.emit(str(exc))
                return False
        agent = self.agent
        timeout = 120.0 if mode == "RADIO" else 600.0
        lang_name = h.radio.lang.name if mode == "RADIO" else self.written_language()
        self._job = Job(lambda emit: agent.ask(question, mode, emit, timeout, lang_name))
        self._job.text.connect(h.engineer_text)
        self._job.done.connect(lambda ans, m=mode: self._on_done(ans, m))
        self._job.failed.connect(self._on_failed)
        self._job_mode = mode
        h.engineer_started.emit(question, mode)
        self._job.start()
        return True

    def _on_done(self, answer: str, mode: str):
        self.hub.engineer_done.emit(answer)
        if mode == "RADIO" and answer:
            self.hub.radio.say(answer, PRIO_HIGH, 60)      # ends up in the radio log once spoken

    def _on_failed(self, err: str):
        h = self.hub
        h.engineer_failed.emit(err)
        h.radio_log.emit("system", f"Engineer: {err}")
        if self._job_mode == "RADIO":
            h.radio.say(h.radio.phrase("agent_error"), PRIO_NORMAL, 15)

    def new_conversation(self):
        if self.agent is not None:
            self.agent.reset()

    def reset(self):
        if self.agent is not None:
            self.agent.cancel()
        self.agent = None

    def shutdown(self):
        if self.agent is not None:
            self.agent.cancel()
