"""
Dinamica veicolo: pneumatico Pacejka (Magic Formula), trasferimenti di carico,
cinematica sospensione a quadrilatero (vista frontale).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

G = 9.81


# ------------------------------------------------------------------- Pacejka

@dataclass
class PacejkaParams:
    """Magic Formula semplificata con sensibilità al carico.

    F = Fz * mu(Fz) * sin(C * atan(B*x - E*(B*x - atan(B*x))))
    mu(Fz) = mu0 * (1 + load_sens * (Fz - Fz0) / Fz0)   (load_sens < 0 => meno grip per kg)
    """

    B: float = 10.0
    C: float = 1.9
    mu0: float = 1.6
    E: float = 0.97
    load_sens: float = -0.12
    Fz0: float = 4000.0     # N, carico nominale

    def mu(self, fz):
        return self.mu0 * (1.0 + self.load_sens * (np.asarray(fz) - self.Fz0) / self.Fz0)


def magic_formula(x, fz, p: PacejkaParams):
    """Forza (N) in funzione dello slip x (angolo in rad oppure slip ratio)."""
    x = np.asarray(x, dtype=float)
    bx = p.B * x
    return fz * p.mu(fz) * np.sin(p.C * np.arctan(bx - p.E * (bx - np.arctan(bx))))


def peak_slip(fz: float, p: PacejkaParams, x_max: float = 0.5) -> tuple[float, float]:
    """Slip al picco di forza e forza di picco (ricerca numerica)."""
    x = np.linspace(0.0, x_max, 4001)
    f = magic_formula(x, fz, p)
    i = int(np.argmax(f))
    return float(x[i]), float(f[i])


def combined_forces(alpha, kappa, fz, p_lat: PacejkaParams, p_long: PacejkaParams):
    """Slip combinato con ellisse d'attrito sullo slip normalizzato (modello di Brach-like)."""
    a_pk, _ = peak_slip(fz, p_lat, 0.5)
    k_pk, _ = peak_slip(fz, p_long, 0.5)
    sa, sk = np.asarray(alpha) / a_pk, np.asarray(kappa) / k_pk
    rho = np.hypot(sa, sk)
    rho_safe = np.where(rho < 1e-9, 1e-9, rho)
    fy = magic_formula(rho * a_pk, fz, p_lat) * sa / rho_safe
    fx = magic_formula(rho * k_pk, fz, p_long) * sk / rho_safe
    return fx, fy


# ------------------------------------------------------- trasferimenti di carico

@dataclass
class VehicleParams:
    mass: float = 1300.0            # kg con pilota e carburante
    cg_height: float = 0.45         # m
    wheelbase: float = 2.65         # m
    track_f: float = 1.62           # m
    track_r: float = 1.58           # m
    weight_dist_f: float = 0.47     # frazione sull'anteriore
    roll_stiff_dist_f: float = 0.55 # frazione rigidezza a rollio anteriore
    rc_height_f: float = 0.04       # m, centro di rollio anteriore
    rc_height_r: float = 0.08       # m
    cl_a: float = 2.4               # m^2 (CL * area)
    cd_a: float = 0.85              # m^2
    aero_balance_f: float = 0.42
    air_density: float = 1.20


@dataclass
class WheelLoads:
    fl: float
    fr: float
    rl: float
    rr: float
    downforce: float
    drag: float
    lltd_f: float   # quota di trasferimento laterale sull'anteriore

    def as_list(self):
        return [self.fl, self.fr, self.rl, self.rr]


def wheel_loads(v: VehicleParams, ay_g: float, ax_g: float, speed_kmh: float) -> WheelLoads:
    """Carichi verticali stazionari. ay > 0 = curva a sinistra (carica le ruote destre)."""
    w = v.mass * G
    vms = speed_kmh / 3.6
    q = 0.5 * v.air_density * vms * vms
    df = q * v.cl_a
    drag = q * v.cd_a

    front = w * v.weight_dist_f + df * v.aero_balance_f
    rear = w * (1 - v.weight_dist_f) + df * (1 - v.aero_balance_f)

    d_long = v.mass * ax_g * G * v.cg_height / v.wheelbase   # ax > 0 = accelerazione
    front -= d_long
    rear += d_long

    a = v.wheelbase * (1 - v.weight_dist_f)                 # distanza CG dall'asse anteriore
    h_ra = v.rc_height_f + (v.rc_height_r - v.rc_height_f) * a / v.wheelbase
    fy = v.mass * ay_g * G
    roll_moment = fy * (v.cg_height - h_ra)
    m_f, m_r = v.weight_dist_f, 1 - v.weight_dist_f
    dlat_f = (fy * m_f * v.rc_height_f + roll_moment * v.roll_stiff_dist_f) / v.track_f
    dlat_r = (fy * m_r * v.rc_height_r + roll_moment * (1 - v.roll_stiff_dist_f)) / v.track_r
    total = abs(dlat_f) + abs(dlat_r)

    return WheelLoads(
        fl=max(0.0, front / 2 - dlat_f), fr=max(0.0, front / 2 + dlat_f),
        rl=max(0.0, rear / 2 - dlat_r), rr=max(0.0, rear / 2 + dlat_r),
        downforce=df, drag=drag,
        lltd_f=abs(dlat_f) / total if total > 1e-9 else v.roll_stiff_dist_f,
    )


# --------------------------------------------- cinematica quadrilatero (vista frontale)

@dataclass
class WishboneGeometry:
    """Punti in mm, vista frontale, lato destro: y laterale dall'asse vettura, z verticale da terra."""

    lower_in: tuple[float, float] = (230.0, 120.0)
    lower_out: tuple[float, float] = (720.0, 110.0)
    upper_in: tuple[float, float] = (300.0, 330.0)
    upper_out: tuple[float, float] = (690.0, 360.0)
    half_track: float = 810.0


@dataclass
class KinematicsResult:
    instant_center: tuple[float, float] | None
    roll_center_height: float | None    # mm
    fvsa_length: float | None           # mm, braccio oscillante virtuale
    camber_gain: float | None           # deg di camber per mm di scuotimento


def _line_intersection(p1, p2, p3, p4):
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-9:
        return None
    a = x1 * y2 - y1 * x2
    b = x3 * y4 - y3 * x4
    return ((a * (x3 - x4) - (x1 - x2) * b) / den, (a * (y3 - y4) - (y1 - y2) * b) / den)


def wishbone_kinematics(g: WishboneGeometry) -> KinematicsResult:
    ic = _line_intersection(g.lower_in, g.lower_out, g.upper_in, g.upper_out)
    if ic is None:  # bracci paralleli: IC all'infinito, nessun recupero di camber
        return KinematicsResult(None, None, None, 0.0)
    contact = (g.half_track, 0.0)
    rc = _line_intersection(contact, ic, (0.0, -1.0), (0.0, 1.0))
    fvsa = math.hypot(ic[0] - contact[0], ic[1] - contact[1])
    gain = math.degrees(1.0 / fvsa) if fvsa > 1e-6 else None
    return KinematicsResult(ic, rc[1] if rc else None, fvsa, gain)
