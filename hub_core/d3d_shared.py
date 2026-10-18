"""
Lettura di una texture D3D11 condivisa da un altro processo (il canvas dell'app CSP, vedi onboard_feed).

L'app pubblica l'handle "legacy" della texture; qui si crea un device D3D11 sulla stessa GPU di AC,
la si apre con OpenSharedResource e a ogni fotogramma la si copia in una texture di staging da cui
la CPU legge i pixel. Così la lettura dalla GPU la paga Delta Suite e non AC.

Un handle legacy si apre solo da un device sulla stessa scheda video che l'ha creato: sui portatili
con due GPU (es. Intel + NVIDIA) si provano tutte finché una riesce.

Solo ctypes, niente dipendenze: le chiamate COM passano dalla vtable con gli indici di d3d11.h/dxgi.h.
"""

from __future__ import annotations

import ctypes
import uuid
from ctypes import wintypes

HRESULT = ctypes.c_long
DXGI_ERROR_NOT_FOUND = -2005270526          # 0x887A0002
D3D_DRIVER_TYPE_UNKNOWN = 0
D3D11_SDK_VERSION = 7
D3D11_USAGE_STAGING = 3
D3D11_CPU_ACCESS_READ = 0x20000
D3D11_MAP_READ = 1

# indici nelle vtable (IUnknown 0-2)
_RELEASE = 2
_FACTORY1_ENUM_ADAPTERS1 = 12
_DEVICE_CREATE_TEXTURE2D = 5
_DEVICE_OPEN_SHARED_RESOURCE = 28
_CONTEXT_MAP, _CONTEXT_UNMAP, _CONTEXT_COPY_RESOURCE = 14, 15, 47
_TEXTURE2D_GET_DESC = 10

FORMATS = {28: "rgba", 29: "rgba", 87: "bgra", 88: "bgra", 91: "bgra"}   # DXGI_FORMAT a 8 bit per canale


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]


def _guid(s: str) -> GUID:
    return GUID.from_buffer_copy(uuid.UUID(s).bytes_le)


IID_IDXGIFactory1 = _guid("770aae78-f26f-4dba-a829-253c83d1b387")
IID_ID3D11Texture2D = _guid("6f15aaf2-d208-4e89-9ab4-489535d34f9c")


class D3D11_TEXTURE2D_DESC(ctypes.Structure):
    _fields_ = [("Width", ctypes.c_uint), ("Height", ctypes.c_uint), ("MipLevels", ctypes.c_uint),
                ("ArraySize", ctypes.c_uint), ("Format", ctypes.c_uint), ("SampleCount", ctypes.c_uint),
                ("SampleQuality", ctypes.c_uint), ("Usage", ctypes.c_uint), ("BindFlags", ctypes.c_uint),
                ("CPUAccessFlags", ctypes.c_uint), ("MiscFlags", ctypes.c_uint)]


class D3D11_MAPPED_SUBRESOURCE(ctypes.Structure):
    _fields_ = [("pData", ctypes.c_void_p), ("RowPitch", ctypes.c_uint), ("DepthPitch", ctypes.c_uint)]


def _call(obj, index: int, restype, argtypes, *args):
    """Chiama il metodo `index` della vtable dell'oggetto COM `obj` (puntatore come int)."""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])
    return fn(obj, *args)


def _release(obj) -> None:
    if obj:
        _call(obj, _RELEASE, ctypes.c_ulong, [])


def _check(hr: int, what: str) -> None:
    if hr < 0:
        raise OSError(f"{what}: HRESULT {hr & 0xFFFFFFFF:#010x}")


class SharedTextureReader:
    """Apre la texture condivisa con un handle e ne legge i pixel. Da usare sempre dallo stesso thread."""

    def __init__(self):
        self._d3d = ctypes.WinDLL("d3d11")
        self._dxgi = ctypes.WinDLL("dxgi")
        self._d3d.D3D11CreateDevice.restype = HRESULT
        self._d3d.D3D11CreateDevice.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint,
            ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_void_p)]
        self._dxgi.CreateDXGIFactory1.restype = HRESULT
        self._dxgi.CreateDXGIFactory1.argtypes = [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
        self.handle = 0
        self.device = self.context = self.texture = self.staging = None
        self.width = self.height = 0
        self.kind = ""
        self.adapter_index = -1

    # ------------------------------------------------------------------ apertura
    def _devices(self):
        """(indice adattatore, device, context) per ogni scheda video; il chiamante rilascia quelli che scarta."""
        factory = ctypes.c_void_p()
        _check(self._dxgi.CreateDXGIFactory1(ctypes.byref(IID_IDXGIFactory1), ctypes.byref(factory)),
               "CreateDXGIFactory1")
        try:
            i = 0
            while True:
                adapter = ctypes.c_void_p()
                hr = _call(factory.value, _FACTORY1_ENUM_ADAPTERS1, HRESULT,
                           [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)], i, ctypes.byref(adapter))
                if hr == DXGI_ERROR_NOT_FOUND:
                    return
                _check(hr, "EnumAdapters1")
                dev, ctx, level = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_int()
                hr = self._d3d.D3D11CreateDevice(adapter, D3D_DRIVER_TYPE_UNKNOWN, None, 0, None, 0,
                                                 D3D11_SDK_VERSION, ctypes.byref(dev), ctypes.byref(level),
                                                 ctypes.byref(ctx))
                _release(adapter.value)
                if hr >= 0:
                    yield i, dev.value, ctx.value
                i += 1
        finally:
            _release(factory.value)

    def open(self, handle: int) -> None:
        """Apre la texture; OSError se nessuna scheda video ci riesce o il formato non è gestito."""
        self.close()
        errors = []
        for i, dev, ctx in self._devices():
            tex = ctypes.c_void_p()
            hr = _call(dev, _DEVICE_OPEN_SHARED_RESOURCE, HRESULT,
                       [wintypes.HANDLE, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)],
                       handle, ctypes.byref(IID_ID3D11Texture2D), ctypes.byref(tex))
            if hr < 0:
                errors.append(f"GPU {i}: {hr & 0xFFFFFFFF:#010x}")
                _release(ctx)
                _release(dev)
                continue
            self.device, self.context, self.texture, self.adapter_index = dev, ctx, tex.value, i
            break
        if self.texture is None:
            raise OSError("OpenSharedResource non riuscita su nessuna scheda video (" + ", ".join(errors) + ")")
        desc = D3D11_TEXTURE2D_DESC()
        _call(self.texture, _TEXTURE2D_GET_DESC, None, [ctypes.POINTER(D3D11_TEXTURE2D_DESC)], ctypes.byref(desc))
        if desc.Format not in FORMATS:
            fmt = desc.Format
            self.close()
            raise OSError(f"formato DXGI {fmt} della texture condivisa non gestito")
        self.width, self.height, self.kind = desc.Width, desc.Height, FORMATS[desc.Format]
        staging = D3D11_TEXTURE2D_DESC(desc.Width, desc.Height, 1, 1, desc.Format, 1, 0, D3D11_USAGE_STAGING, 0,
                                       D3D11_CPU_ACCESS_READ, 0)
        out = ctypes.c_void_p()
        hr = _call(self.device, _DEVICE_CREATE_TEXTURE2D, HRESULT,
                   [ctypes.POINTER(D3D11_TEXTURE2D_DESC), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
                   ctypes.byref(staging), None, ctypes.byref(out))
        if hr < 0:
            self.close()
            _check(hr, "CreateTexture2D (staging)")
        self.staging = out.value
        self.handle = handle

    # ------------------------------------------------------------------ lettura
    def read(self) -> tuple[bytes, int]:
        """(pixel, byte per riga) del contenuto attuale della texture."""
        _call(self.context, _CONTEXT_COPY_RESOURCE, None, [ctypes.c_void_p, ctypes.c_void_p],
              self.staging, self.texture)
        mapped = D3D11_MAPPED_SUBRESOURCE()
        _check(_call(self.context, _CONTEXT_MAP, HRESULT,
                     [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_uint,
                      ctypes.POINTER(D3D11_MAPPED_SUBRESOURCE)],
                     self.staging, 0, D3D11_MAP_READ, 0, ctypes.byref(mapped)), "Map")
        try:
            data = ctypes.string_at(mapped.pData, mapped.RowPitch * self.height)
        finally:
            _call(self.context, _CONTEXT_UNMAP, None, [ctypes.c_void_p, ctypes.c_uint], self.staging, 0)
        return data, mapped.RowPitch

    def close(self) -> None:
        for name in ("staging", "texture", "context", "device"):
            _release(getattr(self, name))
            setattr(self, name, None)
        self.handle = 0
