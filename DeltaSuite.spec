# -*- mode: python ; coding: utf-8 -*-
# Build: .\build_exe.ps1  (or: pyinstaller DeltaSuite.spec)

import os

from PyInstaller.utils.hooks import collect_all

# voice: kokoro-onnx + espeak-ng (pronunciation data) + phonemizer; transcription: faster-whisper
# (CTranslate2, silero VAD). The models are NOT bundled: Kokoro uses Tsukumo's (or a folder you pick),
# Whisper the Hugging Face cache (downloaded on first use if missing).
PACKAGES = ("kokoro_onnx", "espeakng_loader", "phonemizer", "onnxruntime", "language_tags", "segments", "csvw",
            "faster_whisper", "ctranslate2", "av", "tokenizers", "huggingface_hub")

# espeak-ng pronunciation dictionaries for the radio languages only (ai_engine/lang.py: it, en, es, fr, pt);
# the other ~100 languages are ~17 MB the voice never loads. tests/test_build_spec.py keeps the two in sync.
ESPEAK_DICTS = ("en", "it", "es", "fr", "pt")

# never needed at run time: onnxruntime's model tools (quantization, transformers optimisers, sample models),
# converters, test suites, sources and headers (the code is already in the PYZ as bytecode)
SKIP_MODULES = ("onnxruntime.tools", "onnxruntime.transformers", "onnxruntime.quantization", "onnxruntime.datasets",
                "ctranslate2.converters", "tokenizers.tools")
SKIP_DIRS = ("onnxruntime/tools/", "onnxruntime/transformers/", "onnxruntime/quantization/", "onnxruntime/datasets/",
             "ctranslate2/converters/", "/tests/", "/test/")
SKIP_EXT = (".py", ".pyi", ".pyc", ".pyx", ".pxd", ".c", ".cpp", ".h", ".hpp", ".lib", ".pdb")
LIB_EXT = (".dll", ".pyd", ".so")


def _keep_module(name: str) -> bool:
    return not any(name == m or name.startswith(m + ".") for m in SKIP_MODULES) and ".tests" not in name


def _keep_data(src: str, dest: str) -> bool:
    path = (dest.replace("\\", "/") + "/" + os.path.basename(src)).lower()
    if src.lower().endswith(SKIP_EXT) or any(d in "/" + path for d in SKIP_DIRS):
        return False
    if "espeak-ng-data/" in path and path.endswith("_dict"):
        return os.path.basename(path)[:-5] in ESPEAK_DICTS
    return True


datas, binaries, hidden = [("ac_app/DeltaSuiteBridge", "ac_app/DeltaSuiteBridge"),
                           ("hub_core/remote/web", "hub_core/remote/web")], [], []
for pkg in PACKAGES:
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    lib_dests = {(dst.replace("\\", "/"), os.path.basename(src).lower()) for src, dst in b}
    # collect_all lists some DLLs both as data and as binaries (ctranslate2.dll 59 MB, onnxruntime.dll 19 MB):
    # keep the binary copy only
    datas += [(src, dst) for src, dst in d if _keep_data(src, dst)
              and not (src.lower().endswith(LIB_EXT)
                       and (dst.replace("\\", "/"), os.path.basename(src).lower()) in lib_dests)]
    binaries += [(src, dst) for src, dst in b if not any(s in "/" + dst.replace("\\", "/") + "/" for s in SKIP_DIRS)]
    hidden += [m for m in h if _keep_module(m)]

a = Analysis(
    ["run_hub.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden + ["PyQt6.QtMultimedia", "hub_core.locales.it"],   # catalogs are imported by name
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "scipy", "pandas", "pyarrow", "matplotlib", "PyQt5", "PySide2", "PySide6",
              "IPython", "pytest", "OpenGL", "pyqtgraph.opengl", "torch", "tensorflow", "transformers", "onnx",
              *SKIP_MODULES],
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
