"""
kernel32 per le file mapping (shared memory di AC e app CSP), caricato solo al primo uso.

Così il resto di hub_core si importa anche fuori da Windows (test, analisi offline): lì aprire una
mapping dà FileNotFoundError, come se AC non fosse avviato.
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
        raise FileNotFoundError("file mapping disponibili solo su Windows")   # come AC non avviato
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
    """Vista su una mapping creata da un altro processo (AC o l'app CSP): qui non si crea mai nulla.

    Se la si creasse e AC non fosse ancora avviato, AC si aggancerebbe alla nostra, con la nostra
    dimensione. FileNotFoundError se la mapping non c'è.
    """

    def __init__(self, tag: str, struct_type, access: int = FILE_MAP_READ, size: int | None = None):
        k = kernel32()
        self.handle = k.OpenFileMappingW(access, False, tag)
        if not self.handle:
            raise FileNotFoundError(f"{tag} non trovata (errore {ctypes.get_last_error()})")
        self.ptr = k.MapViewOfFile(self.handle, access, 0, 0, ctypes.sizeof(struct_type) if size is None else size)
        if not self.ptr:
            err = ctypes.get_last_error()
            k.CloseHandle(self.handle)
            self.handle = None
            raise OSError(err, f"MapViewOfFile fallita su {tag}")
        self.struct = struct_type.from_address(self.ptr)

    def region_size(self) -> int:
        """Byte davvero mappati: non si legge mai oltre (le pagine di AC possono essere più corte)."""
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
