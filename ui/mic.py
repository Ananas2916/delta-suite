"""Registrazione dal microfono per il push-to-talk (Qt Multimedia, nessuna libreria extra)."""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QObject
from PyQt6.QtMultimedia import QAudioDevice, QAudioFormat, QAudioSource, QMediaDevices

TARGET_SR = 16000


def input_devices() -> list[QAudioDevice]:
    return list(QMediaDevices.audioInputs())


def to_pcm16_mono_16k(raw: bytes, fmt: QAudioFormat) -> bytes:
    """Converte quello che dà il dispositivo in PCM 16 bit, mono, 16 kHz (formato di Tsukumo)."""
    sf = fmt.sampleFormat()
    if sf == QAudioFormat.SampleFormat.Int16:
        a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sf == QAudioFormat.SampleFormat.Int32:
        a = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    elif sf == QAudioFormat.SampleFormat.Float:
        a = np.frombuffer(raw, dtype="<f4").astype(np.float32)
    else:   # UInt8
        a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    ch = max(1, fmt.channelCount())
    a = a[: len(a) - len(a) % ch].reshape(-1, ch).mean(axis=1)
    sr = fmt.sampleRate() or TARGET_SR
    if sr != TARGET_SR and len(a) > 1:
        n = int(len(a) * TARGET_SR / sr)
        a = np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a)
    return (np.clip(a, -1.0, 1.0) * 32767).astype("<i2").tobytes()


class MicRecorder(QObject):
    def __init__(self, device_id: bytes | None = None, parent=None):
        super().__init__(parent)
        self.device_id = device_id
        self._source: QAudioSource | None = None
        self._io = None
        self._buf = bytearray()
        self._fmt: QAudioFormat | None = None

    def _device(self) -> QAudioDevice:
        for d in input_devices():
            if self.device_id and bytes(d.id()) == self.device_id:
                return d
        return QMediaDevices.defaultAudioInput()

    @property
    def recording(self) -> bool:
        return self._source is not None

    def start(self) -> bool:
        if self._source is not None:
            return True
        dev = self._device()
        if dev.isNull():
            return False
        fmt = QAudioFormat()
        fmt.setSampleRate(TARGET_SR)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not dev.isFormatSupported(fmt):
            fmt = dev.preferredFormat()
        self._fmt = fmt
        self._buf = bytearray()
        self._source = QAudioSource(dev, fmt, self)
        self._io = self._source.start()
        if self._io is None:
            self._source = None
            return False
        self._io.readyRead.connect(self._read)
        return True

    def _read(self):
        if self._io is not None:
            self._buf += bytes(self._io.readAll())

    def stop(self) -> bytes:
        """Ferma e ritorna l'audio come PCM 16 bit mono 16 kHz."""
        if self._source is None:
            return b""
        self._read()
        self._source.stop()
        self._source.deleteLater()
        self._source, self._io = None, None
        return to_pcm16_mono_16k(bytes(self._buf), self._fmt)
