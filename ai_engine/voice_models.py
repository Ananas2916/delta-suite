"""
Kokoro voice models: where they are and how to download them.

Delta Suite uses the same two files as kokoro-onnx (the int8 model, ~92 MB, and the 34 voices, ~28 MB).
They are looked for in Tsukumo's folder (if installed) and then in %LOCALAPPDATA%\\DeltaSuite\\models\\kokoro,
where "Download voice" puts them.
"""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from typing import Callable

_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
# local name -> (download URL, exact size in bytes)
KOKORO_FILES = {
    "kokoro-v1.0.onnx": (_BASE + "kokoro-v1.0.int8.onnx", 92_361_271),
    "voices-v1.0.bin": (_BASE + "voices-v1.0.bin", 28_214_398),
}
DOWNLOAD_MB = round(sum(size for _url, size in KOKORO_FILES.values()) / 1e6)

_LOCAL = Path(os.environ.get("LOCALAPPDATA", Path.home()))
TSUKUMO_DIR = _LOCAL / "Programs" / "Tsukumo" / "resources" / "tsukumo" / "models"
DELTA_DIR = _LOCAL / "DeltaSuite" / "models" / "kokoro"


def has_models(folder: Path) -> bool:
    return all((folder / name).is_file() for name in KOKORO_FILES)


def default_kokoro_dir() -> Path:
    """Delta Suite's own copy if downloaded, otherwise Tsukumo's, otherwise where a download would go."""
    for folder in (DELTA_DIR, TSUKUMO_DIR):
        if has_models(folder):
            return folder
    return DELTA_DIR


def download_kokoro(target: Path = DELTA_DIR, progress: Callable[[int, int], None] | None = None,
                    chunk: int = 1 << 20) -> Path:
    """Download the missing model files into `target` (resumable per file: .part then rename).
    `progress(done_bytes, total_bytes)` is called as data arrives. Raises OSError on failure."""
    target.mkdir(parents=True, exist_ok=True)
    total = sum(size for _url, size in KOKORO_FILES.values())
    done = sum(size for name, (_url, size) in KOKORO_FILES.items() if (target / name).is_file())
    for name, (url, size) in KOKORO_FILES.items():
        final = target / name
        if final.is_file():
            continue
        part = final.with_suffix(final.suffix + ".part")
        req = urllib.request.Request(url, headers={"User-Agent": "DeltaSuite"})
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
            while data := r.read(chunk):
                f.write(data)
                done += len(data)
                if progress:
                    progress(done, total)
        if part.stat().st_size != size:
            part.unlink(missing_ok=True)
            raise OSError(f"{name}: incomplete download, try again")
        part.replace(final)
    return target
