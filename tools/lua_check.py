"""Rough check: calls to functions that are neither defined in the file nor known globals."""
import re
import sys

KNOWN = set("""print pairs ipairs type tostring tonumber pcall error math string table os io ffi ac ui physics render vec2
vec3 vec4 rgb rgbm require setTimeout setInterval clearTimeout clearInterval script select next unpack rawget rawset
setmetatable getmetatable assert collectgarbage loadstring load dofile xpcall bit""".split())
SKIP = {"function", "if", "elseif", "while", "return", "and", "or", "not", "until", "local", "in"}
bad = 0
for path in sys.argv[1:]:
    src = open(path, encoding="utf-8").read()
    code = re.sub(r"--\[\[.*?\]\]", "", src, flags=re.S)
    code = re.sub(r"\[\[.*?\]\]", "''", code, flags=re.S)
    code = re.sub(r"--[^\n]*", "", code)
    code = re.sub(r"'(?:\\.|[^'\\\n])*'", "''", code)
    code = re.sub(r'"(?:\\.|[^"\\\n])*"', "''", code)
    defined = set(re.findall(r"\bfunction\s+([A-Za-z_]\w*)\s*\(", code))
    defined |= set(re.findall(r"\blocal\s+function\s+([A-Za-z_]\w*)", code))
    for m in re.finditer(r"\blocal\s+([A-Za-z_][\w\s,]*?)\s*(?:=|\n)", code):
        defined |= {n.strip() for n in m.group(1).split(",")}
    for m in re.finditer(r"function\s*[\w.:]*\s*\(([^)]*)\)", code):
        defined |= {n.strip() for n in m.group(1).split(",") if n.strip()}
    for m in re.finditer(r"(?<![\w.:])([A-Za-z_]\w*)\s*\(", code):
        name = m.group(1)
        if name in SKIP or name in defined or name in KNOWN:
            continue
        print(f"{path}:{code.count(chr(10), 0, m.start()) + 1}: call to undefined '{name}'")
        bad += 1
    # a local function used above the line that defines it is a nil global there
    for d in re.finditer(r"\blocal\s+function\s+([A-Za-z_]\w*)", code):
        name = d.group(1)
        first = re.search(rf"(?<![\w.:]){name}\s*\(", code)
        if first and first.start() < d.start():
            print(f"{path}:{code.count(chr(10), 0, first.start()) + 1}: '{name}' used before its local definition")
            bad += 1
sys.exit(1 if bad else 0)
