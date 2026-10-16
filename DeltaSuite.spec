# -*- mode: python ; coding: utf-8 -*-
# Build: .\build_exe.ps1  (oppure: pyinstaller DeltaSuite.spec)

from PyInstaller.utils.hooks import collect_all

# voce: kokoro-onnx + espeak-ng (dati di pronuncia) + phonemizer; trascrizione: faster-whisper
# (CTranslate2, VAD silero). I modelli NON sono inclusi: Kokoro usa quelli di Tsukumo, Whisper la
# cache di Hugging Face (scaricati al primo uso se mancano).
datas, binaries, hidden = [("ac_app/DeltaSuiteBridge", "ac_app/DeltaSuiteBridge")], [], []
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
