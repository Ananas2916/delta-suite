"""
Voce dell'ingegnere: sintesi (Kokoro locale o Tsukumo) e trascrizione (Tsukumo).

RadioVoice è un thread con coda a priorità: i messaggi hanno una scadenza (un delta di un giro
fa non serve più), quelli urgenti passano avanti e si parla solo quando `is_safe()` lo permette
(non in staccata o a metà curva), con un'attesa massima.
"""

from __future__ import annotations

import io
import itertools
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
import wave
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from ai_engine.lang import language_of

try:
    import winsound
except ImportError:   # pragma: no cover - solo Windows
    winsound = None

TSUKUMO_URL = "http://127.0.0.1:8770"
DEFAULT_KOKORO_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tsukumo" / "resources" / "tsukumo" / "models"

PRIO_URGENT, PRIO_HIGH, PRIO_NORMAL, PRIO_LOW = 0, 1, 2, 3


# --------------------------------------------------------------------- motori

class TTSBackend:
    name = "nessuna"
    plays_itself = False

    def available(self) -> tuple[bool, str]:
        return True, ""

    def synth(self, text: str) -> tuple[np.ndarray, int] | None:
        return None


class KokoroBackend(TTSBackend):
    """kokoro-onnx in processo, con i file del modello già scaricati da Tsukumo (o altra cartella)."""

    name = "kokoro"

    def __init__(self, model_dir: str | Path | None = None, voice: str = "im_nicola", speed: float = 1.1):
        self.model_dir = Path(model_dir) if model_dir else DEFAULT_KOKORO_DIR
        self.voice, self.speed = voice, speed
        self._kokoro = None
        self._lock = threading.Lock()

    def files(self) -> tuple[Path, Path]:
        return self.model_dir / "kokoro-v1.0.onnx", self.model_dir / "voices-v1.0.bin"

    def available(self) -> tuple[bool, str]:
        try:
            import kokoro_onnx  # noqa: F401
        except ImportError:
            return False, "pacchetto kokoro-onnx non installato"
        missing = [p.name for p in self.files() if not p.is_file()]
        if missing:
            return False, f"mancano {', '.join(missing)} in {self.model_dir}"
        return True, ""

    def synth(self, text: str) -> tuple[np.ndarray, int] | None:
        with self._lock:
            if self._kokoro is None:
                from kokoro_onnx import Kokoro
                model, voices = self.files()
                self._kokoro = Kokoro(str(model), str(voices))
            lang = language_of(self.voice).kokoro
            samples, sr = self._kokoro.create(text, voice=self.voice, speed=self.speed, lang=lang)
        return np.asarray(samples, dtype=np.float32).reshape(-1), int(sr)


class TsukumoBackend(TTSBackend):
    """Fa parlare Tsukumo (/api/say): l'audio lo riproduce la sua finestra."""

    name = "tsukumo"
    plays_itself = True

    def __init__(self, url: str = TSUKUMO_URL, voice: str = "im_nicola", speed: float = 1.1):
        self.url, self.voice, self.speed = url.rstrip("/"), voice, speed

    def available(self) -> tuple[bool, str]:
        try:
            urllib.request.urlopen(self.url + "/api/voices", timeout=1.5).close()
            return True, ""
        except OSError as exc:
            return False, f"Tsukumo non risponde su {self.url} ({exc})"

    def synth(self, text: str):
        body = json.dumps({"text": text, "voice": self.voice, "speed": self.speed}).encode()
        req = urllib.request.Request(self.url + "/api/say", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).close()
        return None


def make_backend(engine: str, voice: str, speed: float, model_dir: str | None = None) -> TTSBackend:
    if engine == "kokoro":
        return KokoroBackend(model_dir or None, voice, speed)
    if engine == "tsukumo":
        return TsukumoBackend(voice=voice, speed=speed)
    return TTSBackend()


# ------------------------------------------------------------------ audio

def radio_click(sr: int, ms: float = 45.0, level: float = 0.06) -> np.ndarray:
    """Breve fruscio da radio di squadra prima e dopo il messaggio."""
    n = int(sr * ms / 1000)
    rng = np.random.default_rng(7)
    env = np.linspace(1.0, 0.0, n) ** 2
    return (rng.standard_normal(n) * level * env).astype(np.float32)


def to_wav(samples: np.ndarray, sr: int) -> bytes:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def play_wav(data: bytes) -> None:
    """Riproduzione bloccante sul dispositivo predefinito (chiamare dal thread della voce)."""
    if winsound is not None:
        winsound.PlaySound(data, winsound.SND_MEMORY)


def stop_playback() -> None:
    if winsound is not None:
        winsound.PlaySound(None, 0)   # interrompe il suono in corso


# --------------------------------------------------------------- trascrizione

def transcribe_tsukumo(pcm16_mono_16k: bytes, url: str = TSUKUMO_URL) -> str:
    """Testo dall'audio del push-to-talk (Tsukumo: Motori → Ascolto deve essere attivo)."""
    req = urllib.request.Request(url.rstrip("/") + "/api/transcribe", data=pcm16_mono_16k, method="POST",
                                 headers={"Content-Type": "application/octet-stream"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return (json.loads(r.read()).get("text") or "").strip()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except ValueError:
            pass
        raise RuntimeError(f"Tsukumo: {detail}") from exc


# -------------------------------------------------------------------- coda

@dataclass(order=True)
class _Item:
    priority: int
    seq: int
    text: str = field(compare=False)
    expires: float = field(compare=False)
    key: str | None = field(compare=False, default=None)


class RadioVoice(threading.Thread):
    """Thread che pronuncia i messaggi in ordine di priorità."""

    def __init__(self, backend: TTSBackend, is_safe: Callable[[], bool] | None = None,
                 on_spoken: Callable[[str], None] | None = None, on_error: Callable[[str], None] | None = None):
        super().__init__(daemon=True, name="RadioVoice")
        self.backend = backend
        self.is_safe = is_safe or (lambda: True)
        self.on_spoken = on_spoken
        self.on_error = on_error
        self.max_wait_s = 6.0
        self.click = True
        self._q: queue.PriorityQueue[_Item] = queue.PriorityQueue()
        self._seq = itertools.count()
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._stop = threading.Event()
        self._keys: dict[str, int] = {}

    def set_backend(self, backend: TTSBackend) -> None:
        self.backend = backend
        self._cache.clear()

    def say(self, text: str, priority: int = PRIO_NORMAL, ttl_s: float = 20.0, key: str | None = None) -> None:
        """Accoda un messaggio. Con `key`, un messaggio nuovo con la stessa chiave rimpiazza quello vecchio."""
        text = text.strip()
        if not text:
            return
        seq = next(self._seq)
        if key:
            self._keys[key] = seq
        self._q.put(_Item(priority, seq, text, time.monotonic() + ttl_s, key))

    def interrupt(self) -> None:
        """Svuota la coda e tronca il messaggio in corso (es. il pilota preme la radio)."""
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        stop_playback()

    def shutdown(self) -> None:
        self._stop.set()
        self._q.put(_Item(-1, -1, "", 0.0))

    def _audio(self, text: str) -> bytes | None:
        if text in self._cache:
            self._cache.move_to_end(text)
            return self._cache[text]
        res = self.backend.synth(text)
        if res is None:
            return None
        samples, sr = res
        if self.click:
            c = radio_click(sr)
            samples = np.concatenate([c, np.zeros(int(sr * 0.04), np.float32), samples, c[::-1] * 0.7])
        data = to_wav(samples, sr)
        self._cache[text] = data
        if len(self._cache) > 48:
            self._cache.popitem(last=False)
        return data

    def run(self) -> None:
        while not self._stop.is_set():
            item = self._q.get()
            if self._stop.is_set():
                break
            if item.key and self._keys.get(item.key) != item.seq:
                continue          # superato da un messaggio più recente con la stessa chiave
            if time.monotonic() > item.expires:
                continue
            waited = 0.0
            while item.priority > PRIO_URGENT and not self.is_safe() and waited < self.max_wait_s:
                time.sleep(0.1)
                waited += 0.1
            try:
                data = self._audio(item.text)
                if data is not None:
                    play_wav(data)
                if self.on_spoken:
                    self.on_spoken(item.text)
            except Exception as exc:   # la radio non deve mai far cadere l'hub
                if self.on_error:
                    self.on_error(f"{type(exc).__name__}: {exc}")
