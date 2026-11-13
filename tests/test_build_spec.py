"""The PyInstaller spec trims what collect_all brings in: check that the trimming keeps what the app needs."""

import ast
from pathlib import Path

from ai_engine.lang import LANGUAGES

ROOT = Path(__file__).resolve().parents[1]


def _spec_constant(name: str):
    tree = ast.parse((ROOT / "DeltaSuite.spec").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} missing from DeltaSuite.spec")


def test_espeak_dictionaries_cover_every_radio_language():
    kept = set(_spec_constant("ESPEAK_DICTS"))
    needed = {lang.kokoro.split("-")[0] for lang in LANGUAGES.values()}
    assert needed <= kept, f"add {sorted(needed - kept)} to ESPEAK_DICTS in DeltaSuite.spec (the voice needs them)"


def test_runtime_packages_are_not_skipped():
    skipped = _spec_constant("SKIP_MODULES")
    for needed in ("onnxruntime", "onnxruntime.capi", "ctranslate2", "faster_whisper", "kokoro_onnx", "av"):
        assert not any(needed == m or needed.startswith(m + ".") for m in skipped), needed
    spec = (ROOT / "DeltaSuite.spec").read_text(encoding="utf-8")
    assert '"hub_core/remote/web"' in spec and '"ac_app/DeltaSuiteBridge"' in spec
