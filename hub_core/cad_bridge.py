"""
Bridge CAD/CFD: caricamento mesh .stl/.obj e mappe aerodinamiche esportate
da OpenFOAM/Ansys (CSV con coefficienti vs ride height).
"""

from __future__ import annotations

import csv
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np


# ------------------------------------------------------------------- mesh

@dataclass
class Mesh:
    vertices: np.ndarray    # (N, 3)
    faces: np.ndarray       # (M, 3) indici

    @property
    def triangles(self) -> np.ndarray:
        return self.vertices[self.faces]

    def bbox(self) -> tuple[np.ndarray, np.ndarray]:
        return self.vertices.min(axis=0), self.vertices.max(axis=0)

    def surface_area(self) -> float:
        tri = self.triangles
        return float(0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1).sum())

    def projected_areas(self) -> np.ndarray:
        """Area proiettata sui piani normali a X, Y, Z (mesh chiusa: metà della somma |n_i|)."""
        tri = self.triangles
        n = 0.5 * np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        return 0.5 * np.abs(n).sum(axis=0)


def load_stl(path: str | Path) -> Mesh:
    data = Path(path).read_bytes()
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        if 84 + count * 50 == len(data):
            rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]),
                                count=count, offset=84)
            return _from_triangles(rec["v"].astype(np.float64))
    verts = []
    for line in data.decode("utf-8", errors="ignore").splitlines():
        parts = line.strip().split()
        if parts and parts[0] == "vertex":
            verts.append([float(v) for v in parts[1:4]])
    if not verts:
        raise ValueError("STL non riconosciuto")
    return _from_triangles(np.asarray(verts).reshape(-1, 3, 3))


def _from_triangles(tri: np.ndarray) -> Mesh:
    flat = tri.reshape(-1, 3)
    verts, inv = np.unique(np.round(flat, 6), axis=0, return_inverse=True)
    return Mesh(verts, inv.reshape(-1, 3).astype(np.int32))


def load_obj(path: str | Path) -> Mesh:
    verts, faces = [], []
    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v":
            verts.append([float(v) for v in parts[1:4]])
        elif parts[0] == "f":
            idx = [int(p.split("/")[0]) for p in parts[1:]]
            idx = [i - 1 if i > 0 else len(verts) + i for i in idx]
            for k in range(1, len(idx) - 1):   # triangolazione a ventaglio
                faces.append([idx[0], idx[k], idx[k + 1]])
    if not faces:
        raise ValueError("OBJ senza facce")
    return Mesh(np.asarray(verts, dtype=np.float64), np.asarray(faces, dtype=np.int32))


def load_mesh(path: str | Path) -> Mesh:
    ext = Path(path).suffix.lower()
    if ext == ".stl":
        return load_stl(path)
    if ext == ".obj":
        return load_obj(path)
    raise ValueError(f"Formato non supportato: {ext}")


def demo_car_mesh() -> Mesh:
    """Sagoma low-poly di una vettura (m, X longitudinale, Y laterale, Z verticale)."""
    def box(x0, x1, y0, y1, z0, z1):
        v = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], float)
        f = [[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
             [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]]
        return v, np.array(f)

    parts = [
        box(0.0, 4.6, -0.98, 0.98, 0.10, 0.62),      # corpo
        box(1.6, 3.3, -0.72, 0.72, 0.62, 1.15),      # abitacolo
        box(-0.05, 0.35, -0.95, 0.95, 0.06, 0.12),   # splitter
        box(4.35, 4.75, -0.85, 0.85, 1.05, 1.12),    # ala posteriore
        box(4.45, 4.55, -0.70, -0.62, 0.62, 1.05),   # piloni
        box(4.45, 4.55, 0.62, 0.70, 0.62, 1.05),
    ]
    for cx in (0.95, 3.6):                           # ruote
        for side in (-1, 1):
            parts.append(box(cx - 0.34, cx + 0.34, side * 0.98 - 0.15, side * 0.98 + 0.15, 0.0, 0.68))
    verts, faces, off = [], [], 0
    for v, f in parts:
        verts.append(v)
        faces.append(f + off)
        off += len(v)
    return Mesh(np.vstack(verts), np.vstack(faces).astype(np.int32))


# ------------------------------------------------------------------ mappa aero

_ALIASES = {
    "rh_front": ("rh_front", "rhf", "front_rh", "ride_height_front", "frh"),
    "rh_rear": ("rh_rear", "rhr", "rear_rh", "ride_height_rear", "rrh"),
    "rh": ("rh", "ride_height", "height"),
    "cl": ("cl", "c_l", "lift", "cz"),
    "cd": ("cd", "c_d", "drag", "cx"),
    "cl_front": ("cl_front", "clf", "cl_f"),
}


@dataclass
class AeroMap:
    columns: dict[str, np.ndarray]

    @property
    def is_2d(self) -> bool:
        return "rh_front" in self.columns and "rh_rear" in self.columns

    def at(self, rh_front: float, rh_rear: float | None = None) -> dict[str, float]:
        """Coefficienti interpolati (1D lineare, 2D inverse-distance sui 4 punti più vicini)."""
        out = {}
        if self.is_2d:
            pts = np.column_stack([self.columns["rh_front"], self.columns["rh_rear"]])
            d = np.hypot(pts[:, 0] - rh_front, pts[:, 1] - (rh_rear if rh_rear is not None else rh_front))
            idx = np.argsort(d)[:4]
            if d[idx[0]] < 1e-9:
                w = np.zeros(len(idx))
                w[0] = 1.0
            else:
                w = 1.0 / d[idx] ** 2
            w /= w.sum()
            for k in ("cl", "cd", "cl_front"):
                if k in self.columns:
                    out[k] = float((self.columns[k][idx] * w).sum())
        else:
            rh = self.columns["rh"]
            order = np.argsort(rh)
            for k in ("cl", "cd", "cl_front"):
                if k in self.columns:
                    out[k] = float(np.interp(rh_front, rh[order], self.columns[k][order]))
        if "cl_front" in out and out.get("cl"):
            out["balance_f"] = out["cl_front"] / out["cl"]
        return out


def load_aero_map(path: str | Path) -> AeroMap:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        sample = fh.read(2048)
        fh.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        reader = csv.DictReader(fh, dialect=dialect)
        rows = list(reader)
    if not rows:
        raise ValueError("CSV vuoto")
    header = {h.strip().lower(): h for h in rows[0].keys()}
    cols: dict[str, np.ndarray] = {}
    for key, aliases in _ALIASES.items():
        src = next((header[a] for a in aliases if a in header), None)
        if src is not None:
            cols[key] = np.array([float(r[src].replace(",", ".")) for r in rows])
    if "cl" not in cols or ("rh" not in cols and not ("rh_front" in cols and "rh_rear" in cols)):
        raise ValueError("Servono colonne CL e ride height (rh oppure rh_front + rh_rear)")
    if "rh" not in cols and not ("rh_front" in cols and "rh_rear" in cols):
        cols["rh"] = cols.get("rh_front")
    return AeroMap(cols)


def demo_aero_map() -> AeroMap:
    """Mappa sintetica stile GT3: CL·A e CD·A vs ride height anteriore/posteriore (mm)."""
    f, r = np.meshgrid(np.arange(40, 101, 10.0), np.arange(60, 131, 10.0))
    f, r = f.ravel(), r.ravel()
    rake = r - f
    cl = 2.2 + 0.012 * rake - 0.00009 * rake ** 2 - 0.004 * (f - 60) - 0.00015 * (f - 55) ** 2
    cd = 0.82 + 0.0016 * rake + 0.0007 * (100 - f)
    cl_front = cl * (0.40 + 0.0018 * (70 - f) + 0.0008 * rake)
    return AeroMap({"rh_front": f, "rh_rear": r, "cl": cl, "cd": cd, "cl_front": cl_front})
