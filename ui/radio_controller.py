"""Radio and push-to-talk: automatic radio rules, the engineer's voice, microphone and transcription."""

from __future__ import annotations

import os
import threading

from ai_engine.lang import DEFAULT_VOICE, Language, language_of
from ai_engine.radio import Msg, RadioConfig, RadioRules
from ai_engine.stt import DEFAULT_MODEL, make_stt
from ai_engine.voice import PRIO_NORMAL, PRIO_URGENT, RadioVoice, make_backend
from hub_core.model import ACStatus
from ui.mic import MicRecorder
from ui.workers import Job
from hub_core.i18n import tr

RADIO_FLAGS = ("lap_times", "fuel", "tyres", "gaps", "flags", "hybrid", "positions", "rivals", "car")
RADIO_LIMITS = ("tyre_temp_lo", "tyre_temp_hi", "tyre_press_lo", "tyre_press_hi")
RADIO_LEVELS = ("chatter", "ai_comment_laps")       # how talkative the engineer is; AI comment every N laps


def _quiet(fn):
    try:
        fn()
    except Exception:
        pass        # the error resurfaces, with its message, at the first transcription


class RadioController:
    """Owned by HubState; talks to the pages through the hub's signals (radio_log, voice_error, ptt_changed)."""

    def __init__(self, hub):
        self.hub = hub
        self.rules = RadioRules(self.load_config(), self.lang)
        self.voice = RadioVoice(self._make_tts(), is_safe=self._safe_to_talk,
                                on_spoken=lambda t: hub.radio_log.emit("radio", t),
                                on_error=hub.voice_error.emit)
        self.voice.start()
        self.mic = MicRecorder(self._mic_id(), hub)
        self.stt = None
        self.reload_stt()
        self._ptt = False
        self._stt_job: Job | None = None

    # ----------------------------------------------------------- settings
    def load_config(self) -> RadioConfig:
        c = RadioConfig()
        for f in RADIO_FLAGS:
            setattr(c, f, self.hub.setting(f"radio/{f}", True, bool))
        for f in RADIO_LIMITS:
            setattr(c, f, self.hub.setting(f"radio/{f}", getattr(c, f), float))
        for f in RADIO_LEVELS:
            setattr(c, f, self.hub.setting(f"radio/{f}", getattr(c, f), int))
        return c

    def save_config(self, c: RadioConfig):
        for k, v in c.__dict__.items():
            self.hub.settings.setValue(f"radio/{k}", v)
        self.rules.cfg = c

    @property
    def lang(self) -> Language:
        return language_of(self.hub.setting("voice/voice", DEFAULT_VOICE))

    def phrase(self, key: str, **kw) -> str:
        return self.lang.phrases[key].format(**kw)

    def _make_tts(self):
        if os.environ.get("DELTA_MUTE") or os.environ.get("DELTA_SELFTEST"):
            return make_backend("none", "", 1.0)      # tests and self-test: no audio
        h = self.hub
        return make_backend(h.setting("voice/engine", "kokoro"), h.setting("voice/voice", DEFAULT_VOICE),
                            h.setting("voice/speed", 1.1, float), h.setting("voice/model_dir", "") or None)

    def reload_voice(self):
        self.voice.set_backend(self._make_tts())
        self.rules.lang = self.lang

    def reload_stt(self):
        h = self.hub
        self.stt = make_stt(h.setting("stt/engine", "whisper"), h.setting("stt/model", DEFAULT_MODEL),
                            h.setting("voice/tsukumo_url", "http://127.0.0.1:8770"))
        if self.stt.available()[0] and not os.environ.get("DELTA_SELFTEST") and not os.environ.get("DELTA_MUTE"):
            stt = self.stt
            threading.Thread(target=lambda: _quiet(stt.preload), daemon=True, name="STTPreload").start()

    def _mic_id(self) -> bytes | None:
        v = self.hub.settings.value("voice/mic", b"")
        return bytes(v) if v else None

    def reload_mic(self):
        self.mic.device_id = self._mic_id()

    # ------------------------------------------------------------- speaking
    def _safe_to_talk(self) -> bool:
        """Not under braking or mid-corner."""
        s = self.hub.last_sample
        if s is None or s.status != ACStatus.LIVE:
            return True
        return s.brake < 0.05 and abs(s.steer_angle) < 0.15 and abs(s.acc_g[0]) < 1.2

    def say_msg(self, m: Msg):
        self.voice.say(m.text, m.priority, m.ttl_s, m.key)

    def say(self, text: str, priority: int = PRIO_NORMAL, ttl_s: float = 30.0):
        self.voice.say(text, priority, ttl_s)

    # ------------------------------------------------------- push-to-talk
    def set_ptt(self, down: bool):
        """Radio pressed: stop the voice and record; released: transcription → engineer."""
        if down == self._ptt:
            return
        self._ptt = down
        self.hub.ptt_changed.emit(down)
        if down:
            self.voice.interrupt()
            if not self.mic.start():
                self.hub.radio_log.emit("system", tr("Microphone not available"))
            return
        pcm = self.mic.stop()
        if len(pcm) < 16000 * 2 * 0.4:          # under 0.4 s: accidental press
            return
        stt, lang = self.stt, self.lang
        self._stt_job = Job(lambda _emit: stt.transcribe(pcm, lang))
        self._stt_job.done.connect(self._on_transcript)
        self._stt_job.failed.connect(self._on_transcript_failed)
        self._stt_job.start()

    @property
    def ptt_down(self) -> bool:
        return self._ptt

    def _on_transcript(self, text: str):
        if not text:
            self.say(self.phrase("stt_error"), PRIO_URGENT, 10)
            return
        self.hub.radio_log.emit("driver", text)
        if not self.hub.engineer.ask(text, "RADIO"):
            self.say(self.phrase("busy"), PRIO_NORMAL, 10)

    def _on_transcript_failed(self, err: str):
        self.hub.radio_log.emit("system", tr("Transcription: {err}", err=err))
        self.say(self.phrase("stt_error"), PRIO_URGENT, 10)

    def shutdown(self):
        self.voice.shutdown()
