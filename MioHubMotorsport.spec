# -*- mode: python ; coding: utf-8 -*-
# Build: .\build_exe.ps1  (oppure: pyinstaller MioHubMotorsport.spec)

a = Analysis(
    ["run_hub.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        "OpenGL.platform.win32",
        "OpenGL.arrays.numpymodule",
        "OpenGL.arrays.ctypesarrays",
        "OpenGL.arrays.lists",
        "OpenGL.arrays.numbers",
        "OpenGL.arrays.strings",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "scipy", "pandas", "pyarrow", "matplotlib", "PyQt5", "PySide2", "PySide6",
              "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MioHubMotorsport",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/miohub.ico",
)
