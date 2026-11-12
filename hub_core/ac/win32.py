"""
kernel32 for file mappings (AC shared memory and CSP app), loaded only on first use.

This way the rest of hub_core can be imported outside Windows too (tests, offline analysis): there
opening a mapping raises FileNotFoundError, as if AC were not running.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from functools import lru_cache

FILE_MAP_WRITE, FILE_MAP_READ = 0x0002, 0x0004


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


@lru_cache(maxsize=1)
def kernel32():
    if not hasattr(ctypes, "WinDLL"):
        raise FileNotFoundError("file mappings are only available on Windows")   # same as AC not running
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k.OpenFileMappingW.restype = wintypes.HANDLE
    k.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    k.MapViewOfFile.restype = ctypes.c_void_p
    k.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    k.UnmapViewOfFile.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    k.VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
    k.VirtualQuery.restype = ctypes.c_size_t
    return k


class MappedView:
    """View of a mapping created by another process (AC or the CSP app): nothing is ever created here.

    If we created it while AC was not running yet, AC would attach to ours, with our size.
    FileNotFoundError if the mapping does not exist.
    """

    def __init__(self, tag: str, struct_type, access: int = FILE_MAP_READ, size: int | None = None):
        k = kernel32()
        self.handle = k.OpenFileMappingW(access, False, tag)
        if not self.handle:
            raise FileNotFoundError(f"{tag} not found (error {ctypes.get_last_error()})")
        self.ptr = k.MapViewOfFile(self.handle, access, 0, 0, ctypes.sizeof(struct_type) if size is None else size)
        if not self.ptr:
            err = ctypes.get_last_error()
            k.CloseHandle(self.handle)
            self.handle = None
            raise OSError(err, f"MapViewOfFile failed on {tag}")
        self.struct = struct_type.from_address(self.ptr)

    def region_size(self) -> int:
        """Bytes actually mapped: never read past them (AC pages can be shorter)."""
        mbi = MEMORY_BASIC_INFORMATION()
        kernel32().VirtualQuery(self.ptr, ctypes.byref(mbi), ctypes.sizeof(mbi))
        return mbi.RegionSize

    def close(self) -> None:
        if self.ptr:
            kernel32().UnmapViewOfFile(self.ptr)
            self.ptr = None
        if self.handle:
            kernel32().CloseHandle(self.handle)
            self.handle = None
