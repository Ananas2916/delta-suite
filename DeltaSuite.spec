# -*- mode: python ; coding: utf-8 -*-
# Build: .\build_exe.ps1  (or: pyinstaller DeltaSuite.spec)

from PyInstaller.utils.hooks import collect_all

# voice: kokoro-onnx + espeak-ng (pronunciation data) + phonemizer; transcription: faster-whisper
# (CTranslate2, silero VAD). The models are NOT bundled: Kokoro uses Tsukumo's (or a folder you pick),
# Whisper the Hugging Face cache (downloaded on first use if missing).
datas, binaries, hidden = [("ac_app/DeltaSuiteBridge", "ac_app/DeltaSuiteBridge"),
                           ("hub_core/remote/web", "hub_core/remote/web")], [], []
for pkg in ("kokoro_onnx", "espeakng_loader", "phonemizer", "onnxruntime", "language_tags", "segments", "csvw",
            "faster_whisper", "ctranslate2", "av", "tokenizers", "huggingface_hub"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    datas += d
    binaries += b
    hidden += h

a = Analysis(
    ["run_hub.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden + ["PyQt6.QtMultimedia"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "scipy", "pandas", "pyarrow", "matplotlib", "PyQt5", "PySide2", "PySide6",
              "IPython", "pytest", "OpenGL", "pyqtgraph.opengl"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DeltaSuite",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/deltasuite.ico",
)
