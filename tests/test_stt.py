import numpy as np
import pytest

from ai_engine.lang import LANGUAGES
from ai_engine.stt import WhisperSTT, model_cached
from ai_engine.voice import KokoroBackend

needs_models = pytest.mark.skipif(
    not model_cached("base") or not KokoroBackend().available()[0],
    reason="servono il modello Whisper base e Kokoro in locale")


@needs_models
@pytest.mark.parametrize("lang_key, voice, text, expect", [
    ("it", "im_nicola", "Quanti giri di carburante mi restano?", "carburante"),
    ("en-us", "am_michael", "Should I move the brake bias forward?", "brake bias"),
])
def test_whisper_understands_kokoro(lang_key, voice, text, expect):
    lg = LANGUAGES[lang_key]
    k = KokoroBackend(voice=voice, speed=1.0)
    samples, sr = k.synth(text)
    a = np.interp(np.linspace(0, len(samples) - 1, int(len(samples) * 16000 / sr)), np.arange(len(samples)), samples)
    pcm = (np.clip(a, -1, 1) * 32767).astype("<i2").tobytes()
    out = WhisperSTT("base").transcribe(pcm, lg)
    assert expect in out.lower()


def test_whisper_ignores_tiny_clips():
    assert WhisperSTT("base").transcribe(b"\0\0" * 800, LANGUAGES["it"]) == ""
