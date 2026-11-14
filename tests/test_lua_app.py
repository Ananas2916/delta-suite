"""The CSP app's Lua files call only functions they define (above the call) or CSP/Lua globals.

A function lost in an edit (seen live: `unseen` removed, race control erroring every frame and the safety car never
leaving the pits) is a runtime error in AC, invisible to a syntax check: tools/lua_check.py finds it statically.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_lua_app_calls_only_defined_functions():
    files = sorted(str(p) for p in (ROOT / "ac_app" / "DeltaSuiteBridge").glob("*.lua"))
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "lua_check.py"), *files], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_lua_check_catches_a_missing_function(tmp_path):
    bad = tmp_path / "bad.lua"
    bad.write_text("local function a() return b() end\nlocal function c() return d() end\n"
                   "local function d() return 1 end\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "lua_check.py"), str(bad)], capture_output=True, text=True)
    assert r.returncode == 1 and "'b'" in r.stdout and "'d' used before" in r.stdout
