import io

import pytest

from ai_engine import voice_models as vm


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_download_writes_both_files_and_reports_progress(tmp_path, monkeypatch):
    files = {"kokoro-v1.0.onnx": ("https://x/1", 3000), "voices-v1.0.bin": ("https://x/2", 1000)}
    monkeypatch.setattr(vm, "KOKORO_FILES", files)
    bodies = {"https://x/1": b"a" * 3000, "https://x/2": b"b" * 1000}
    monkeypatch.setattr(vm.urllib.request, "urlopen", lambda req, timeout: FakeResponse(bodies[req.full_url]))
    seen = []
    vm.download_kokoro(tmp_path, lambda done, total: seen.append((done, total)), chunk=500)
    assert vm.has_models(tmp_path) and (tmp_path / "voices-v1.0.bin").read_bytes() == b"b" * 1000
    assert seen[-1] == (4000, 4000) and not list(tmp_path.glob("*.part"))


def test_incomplete_download_is_discarded(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "KOKORO_FILES", {"kokoro-v1.0.onnx": ("https://x/u", 10)})
    monkeypatch.setattr(vm.urllib.request, "urlopen", lambda req, timeout: FakeResponse(b"short"))
    with pytest.raises(OSError):
        vm.download_kokoro(tmp_path)
    assert not list(tmp_path.iterdir())


def test_default_dir_prefers_a_complete_copy(tmp_path, monkeypatch):
    own, tsukumo = tmp_path / "own", tmp_path / "tsukumo"
    monkeypatch.setattr(vm, "DELTA_DIR", own)
    monkeypatch.setattr(vm, "TSUKUMO_DIR", tsukumo)
    assert vm.default_kokoro_dir() == own                  # nothing yet: where the download goes
    tsukumo.mkdir()
    for name in vm.KOKORO_FILES:
        (tsukumo / name).write_bytes(b"x")
    assert vm.default_kokoro_dir() == tsukumo
