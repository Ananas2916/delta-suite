"""
Memory-mapped layouts shared by the CSP Lua app and Delta Suite: the Lua struct declarations and the ctypes
structures must match byte for byte (names, types, order, offsets, total size, 4-byte alignment) and the mapping
names must agree, version suffix included. A layout that changes without a new version would make an old app
and a new Delta Suite (or the other way round) read garbage: the fingerprints below catch that.
"""

from __future__ import annotations

import ctypes
import hashlib
import re

import pytest

from hub_core.ac import csp_bridge as cb
from hub_core.ac import onboard_feed as ob

BUMP = ("if you changed the layout on purpose, change it the same way in both files AND bump the version in the "
        "mapping name on both sides (Lua string and Python constant), then update LAYOUT_FINGERPRINTS here")

# (Lua file, Lua layout variable, Python structure, Python mapping tag, Python version, Lua version constant)
LAYOUTS = [
    ("DeltaSuiteBridge.lua", "OUT_LAYOUT", cb.BridgeOut, cb.OUT_TAG, cb.VERSION, "VERSION"),
    ("DeltaSuiteBridge.lua", "IN_LAYOUT", cb.BridgeIn, cb.IN_TAG, cb.VERSION, "VERSION"),
    ("DeltaSuiteOnboard.lua", "ONBOARD_LAYOUT", ob.OnboardShared, ob.ONBOARD_TAG, ob.ONBOARD_VERSION,
     "ONBOARD_VERSION"),
]

# sha256 (first 16 hex) of the normalised Lua layout, per mapping name: a new layout needs a new name
LAYOUT_FINGERPRINTS = {
    "DeltaSuite_Bridge_Out_v1": "d23ab06a916758d5",
    "DeltaSuite_Bridge_In_v1": "b3f23efdd0bb0195",
    "DeltaSuite_Onboard_v6": "98d2cea3bcfd2f33",
}

LUA_TYPES = {"int": (ctypes.c_int, 4), "unsigned int": (ctypes.c_uint, 4), "float": (ctypes.c_float, 4),
             "char": (ctypes.c_char, 1)}
FIELD_RE = re.compile(r"^\s*(unsigned int|int|float|char)\s+(\w+)((?:\[\d+\])*)\s*;\s*$")


def _lua(name: str) -> str:
    return (cb.bundled_app_dir() / name).read_text(encoding="utf-8")


def lua_fields(lua: str, var: str) -> list[tuple[str, str, list[int]]]:
    """(name, type, dimensions) of each field of `local VAR = [[ ... ]]`."""
    m = re.search(rf"local {var} = \[\[(.*?)\]\]", lua, re.S)
    assert m, f"{var} not found in the Lua app"
    out = []
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        f = FIELD_RE.match(line)
        assert f, f"{var}: unsupported declaration {line.strip()!r} (only int, unsigned int, float, char arrays)"
        out.append((f.group(2), f.group(1), [int(d) for d in re.findall(r"\[(\d+)\]", f.group(3))]))
    return out


def ctype_base(t) -> tuple[type, int]:
    """Element type and element count of a (possibly nested) ctypes array."""
    count = 1
    while hasattr(t, "_length_"):
        count *= t._length_
        t = t._type_
    return t, count


def fingerprint(fields) -> str:
    text = ";".join(f"{typ} {name}" + "".join(f"[{d}]" for d in dims) for name, typ, dims in fields)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def lua_mappings(lua: str) -> dict[str, str]:
    """Lua layout variable → mapping name it is opened with."""
    return {var: name for name, var in re.findall(r"ac\.writeMemoryMappedFile\('([^']+)',\s*(\w+)\)", lua)}


@pytest.mark.parametrize("lua_file,var,struct,tag,version,lua_version", LAYOUTS, ids=[l[1] for l in LAYOUTS])
def test_layout_matches_byte_for_byte(lua_file, var, struct, tag, version, lua_version):
    fields = lua_fields(_lua(lua_file), var)
    py = struct._fields_
    assert [n for n, *_ in fields] == [n for n, _ in py], f"{var} / {struct.__name__}: field names or order differ"
    offset = 0
    for (name, typ, dims), (_pname, ptype) in zip(fields, py):
        want_type, elem = LUA_TYPES[typ]
        count = 1
        for d in dims:
            count *= d
        base, pcount = ctype_base(ptype)
        assert base is want_type, f"{struct.__name__}.{name}: Lua {typ}, Python {base.__name__}"
        assert pcount == count, f"{struct.__name__}.{name}: Lua {count} elements, Python {pcount}"
        assert getattr(struct, name).offset == offset, (
            f"{struct.__name__}.{name}: offset {getattr(struct, name).offset} in Python, {offset} in Lua")
        assert offset % 4 == 0, f"{name} starts at offset {offset}, not 4-byte aligned: LuaJIT and ctypes may pad"
        offset += elem * count
    assert offset % 4 == 0, f"{var}: total size {offset} is not a multiple of 4"
    assert ctypes.sizeof(struct) == offset, f"{struct.__name__}: {ctypes.sizeof(struct)} bytes in Python, {offset} in Lua"
    assert fields[0][0] == "version" and fields[-1][0] == "endMarker", f"{var}: must start with version, end with endMarker"


@pytest.mark.parametrize("lua_file,var,struct,tag,version,lua_version", LAYOUTS, ids=[l[1] for l in LAYOUTS])
def test_mapping_name_and_version_match(lua_file, var, struct, tag, version, lua_version):
    lua = _lua(lua_file)
    name = lua_mappings(lua).get(var)
    assert name is not None, f"{lua_file} does not open a mapping with {var}"
    assert tag == f"Local\\{name}", (f"mapping name differs: Python {tag!r}, Lua 'Local\\{name}'. Both sides must "
                                     f"use the same name, version suffix included")
    assert name.endswith(f"_v{version}"), f"{name}: suffix does not match the Python version {version}"
    m = re.search(rf"\b{lua_version}\b[^=\n]*=\s*([^\n-]+)", lua)
    assert m, f"{lua_version} not declared in {lua_file}"
    names = [n.strip() for n in m.group(0).split("=")[0].replace("local", "").split(",")]
    values = [v.strip() for v in m.group(1).split(",")]
    assert values[names.index(lua_version)] == str(version), (
        f"{lua_file}: {lua_version} = {values[names.index(lua_version)]}, Python {version}")


@pytest.mark.parametrize("lua_file,var,struct,tag,version,lua_version", LAYOUTS, ids=[l[1] for l in LAYOUTS])
def test_layout_change_needs_a_new_version(lua_file, var, struct, tag, version, lua_version):
    name = tag.split("\\", 1)[1]
    got = fingerprint(lua_fields(_lua(lua_file), var))
    want = LAYOUT_FINGERPRINTS.get(name)
    assert want is not None, f"new mapping {name}: add it to LAYOUT_FINGERPRINTS with fingerprint {got!r}"
    assert got == want, f"the {name} layout changed (fingerprint {got}, expected {want}): {BUMP}"


def test_checker_catches_a_mismatch():
    class Wrong(ctypes.Structure):
        _fields_ = [("version", ctypes.c_int), ("x", ctypes.c_float), ("endMarker", ctypes.c_int)]

    lua = "local L = [[\n  int version;\n  int x;\n  int endMarker;\n]]"
    fields = lua_fields(lua, "L")
    assert [f[1] for f in fields] == ["int", "int", "int"]
    assert ctype_base(Wrong._fields_[1][1])[0] is not LUA_TYPES[fields[1][1]][0]
    assert fingerprint(fields) != fingerprint(lua_fields(lua.replace("int x", "float x"), "L"))
