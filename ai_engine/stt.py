"""
Push-to-talk transcription: local Whisper (faster-whisper) or Tsukumo.

Whisper uses the models in the Hugging Face cache (%USERPROFILE%\\.cache\\huggingface\\hub), the same
as Tsukumo: if the chosen model is missing, it is downloaded once. The language is the radio voice's
and the initial prompt contains pit-wall jargon, so "bias", "box" and "TC" come out right.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np

from ai_engine.lang import Language
from ai_engine.voice import TSUKUMO_URL, transcribe_tsukumo

# faster-whisper model -> note
WHISPER_MODELS = {
    "base": "fast (~1 s), recommended",
    "small": "more accurate (~3 s), 480 MB download",
    "large-v3-turbo": "very accurate, slow without a GPU, 1.6 GB",
    "tiny": "fastest, less accurate",
    "large-v3": "best accuracy, ~10 s on CPU",
}
DEFAULT_MODEL = "base"


def hf_cache() -> Path:
    return Path(os.environ.get("HF_HUB_CACHE") or Path.home() / ".cache" / "huggingface" / "hub")


def model_cached(name: str) -> bool:
    repo = "mobiuslabsgmbh/faster-whisper-large-v3-turbo" if name == "large-v3-turbo" \
        else f"Systran/faster-whisper-{name}"
    d = hf_cache() / ("models--" + repo.replace("/", "--")) / "snapshots"
    return d.is_dir() and any(d.iterdir())


class STTEngine:
    name = "none"

    def available(self) -> tuple[bool, str]:
        return False, "no transcription engine"

    def preload(self) -> None:
        pass

    def transcribe(self, pcm16_mono_16k: bytes, lang: Language) -> str:
        raise RuntimeError("transcription disabled")


class WhisperSTT(STTEngine):
    name = "whisper"

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model_name = model
        self._model = None
        self._lock = threading.Lock()

    def available(self) -> tuple[bool, str]:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False, "faster-whisper package not installed"
        if model_cached(self.model_name):
            return True, f"model {self.model_name} ready"
        return True, f"model {self.model_name} not downloaded yet: it will be downloaded on first use"

    def _load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel
                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8",
                                           cpu_threads=max(2, (os.cpu_count() or 4) // 2),
                                           local_files_only=model_cached(self.model_name))
            return self._model

    def preload(self) -> None:
        """Call from a thread at startup, so the first radio question does not wait for loading."""
        self._load()

    def transcribe(self, pcm16_mono_16k: bytes, lang: Language) -> str:
        audio = np.frombuffer(pcm16_mono_16k, dtype="<i2").astype(np.float32) / 32768.0
        if audio.size < 1600:
            return ""
        model = self._load()
        segments, _ = model.transcribe(audio, language=lang.code, beam_size=1, vad_filter=True,
                                       initial_prompt=lang.phrases["stt_prompt"],
                                       condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()


class TsukumoSTT(STTEngine):
    name = "tsukumo"

    def __init__(self, url: str = TSUKUMO_URL):
        self.url = url

    def available(self) -> tuple[bool, str]:
        return True, "uses Tsukumo's listening engine (enable it there)"

    def transcribe(self, pcm16_mono_16k: bytes, lang: Language) -> str:
        return transcribe_tsukumo(pcm16_mono_16k, self.url)


def make_stt(engine: str, model: str = DEFAULT_MODEL, tsukumo_url: str = TSUKUMO_URL) -> STTEngine:
    if engine == "whisper":
        return WhisperSTT(model or DEFAULT_MODEL)
    if engine == "tsukumo":
        return TsukumoSTT(tsukumo_url)
    return STTEngine()
