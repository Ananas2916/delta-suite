"""
Trascrizione del push-to-talk: Whisper locale (faster-whisper) oppure Tsukumo.

Whisper usa i modelli nella cache di Hugging Face (%USERPROFILE%\\.cache\\huggingface\\hub), gli stessi
di Tsukumo: se il modello scelto non c'è, lo scarica una volta. La lingua è quella della voce della
radio e il prompt iniziale contiene il gergo da muretto, così "bias", "box" e "TC" escono giusti.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np

from ai_engine.lang import Language
from ai_engine.voice import TSUKUMO_URL, transcribe_tsukumo

# nome mostrato -> (modello faster-whisper, nota)
WHISPER_MODELS = {
    "base": "veloce (~1 s), consigliato",
    "small": "più preciso (~3 s), 480 MB da scaricare",
    "large-v3-turbo": "molto preciso, lento senza GPU, 1,6 GB",
    "tiny": "velocissimo, meno preciso",
    "large-v3": "massima precisione, ~10 s su CPU",
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
    name = "nessuna"

    def available(self) -> tuple[bool, str]:
        return False, "nessun motore di trascrizione"

    def preload(self) -> None:
        pass

    def transcribe(self, pcm16_mono_16k: bytes, lang: Language) -> str:
        raise RuntimeError("trascrizione disattivata")


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
            return False, "pacchetto faster-whisper non installato"
        if model_cached(self.model_name):
            return True, f"modello {self.model_name} pronto"
        return True, f"modello {self.model_name} non ancora scaricato: lo scarico al primo uso"

    def _load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel
                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8",
                                           cpu_threads=max(2, (os.cpu_count() or 4) // 2),
                                           local_files_only=model_cached(self.model_name))
            return self._model

    def preload(self) -> None:
        """Da chiamare in un thread all'avvio: così la prima domanda alla radio non aspetta il caricamento."""
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
        return True, "usa il motore Ascolto di Tsukumo (va attivato lì)"

    def transcribe(self, pcm16_mono_16k: bytes, lang: Language) -> str:
        return transcribe_tsukumo(pcm16_mono_16k, self.url)


def make_stt(engine: str, model: str = DEFAULT_MODEL, tsukumo_url: str = TSUKUMO_URL) -> STTEngine:
    if engine == "whisper":
        return WhisperSTT(model or DEFAULT_MODEL)
    if engine == "tsukumo":
        return TsukumoSTT(tsukumo_url)
    return STTEngine()
