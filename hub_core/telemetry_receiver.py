"""
Acquisizione telemetria live da Assetto Corsa via shared memory.

Avvio da terminale (dalla cartella del progetto):
    python -m hub_core.telemetry_receiver            # 60 Hz
    python -m hub_core.telemetry_receiver --hz 100

Stampa in tempo reale velocità, RPM, marcia e pedali. Si riaggancia da solo se AC
viene avviato dopo lo script o se si torna ai menu.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass

from hub_core.ac_shared_memory import (
    ACSharedMemory,
    ACSessionType,
    ACStatus,
    SharedMemoryNotAvailable,
    gear_label,
)

Quad = tuple[float, float, float, float]   # valori per ruota: FL, FR, RL, RR


@dataclass(frozen=True)
class TelemetrySample:
    """Un campione di telemetria, indipendente dalla sorgente (AC o simulatore)."""

    t: float                    # time.perf_counter() al momento della lettura
    packet_id: int
    status: ACStatus
    session_type: ACSessionType
    # guida
    speed_kmh: float
    rpm: int
    gear: int                   # convenzione AC: 0=R, 1=N, 2=1a
    gas: float                  # 0..1
    brake: float                # 0..1
    clutch: float               # 0..1 (1 = frizione rilasciata)
    steer_angle: float
    fuel: float                 # litri
    acc_g: tuple[float, float, float]   # laterale, verticale, longitudinale
    # gomme / freni / telaio
    tyre_core_temp: Quad        # °C
    tyre_pressure: Quad         # psi
    tyre_wear: Quad
    wheel_slip: Quad
    brake_temp: Quad            # °C
    suspension_travel: Quad     # m
    ride_height: tuple[float, float]    # anteriore, posteriore (m)
    tc: float
    abs: float
    drs: float
    kers_charge: float
    tyres_out: int
    air_temp: float
    road_temp: float
    # timing
    lap_time_ms: int
    last_lap_ms: int
    best_lap_ms: int
    completed_laps: int
    lap_position: float         # 0..1 lungo il giro
    sector_index: int
    last_sector_ms: int
    is_in_pit: bool
    position: int
    car_x: float
    car_z: float


def _quad(arr) -> Quad:
    return (arr[0], arr[1], arr[2], arr[3])


class TelemetryReceiver:
    """Legge la shared memory di AC e produce TelemetrySample."""

    name = "Assetto Corsa"

    def __init__(self):
        self._sm: ACSharedMemory | None = None

    def connect(self) -> bool:
        """Prova ad agganciarsi ad AC. Ritorna False se AC non è in esecuzione."""
        if self._sm is not None:
            return True
        try:
            self._sm = ACSharedMemory()
        except SharedMemoryNotAvailable:
            return False
        return True

    def disconnect(self) -> None:
        if self._sm is not None:
            self._sm.close()
            self._sm = None

    def car_and_track(self) -> tuple[str, str]:
        info = self.session_info()
        return info["car"], info["track"]

    def session_info(self) -> dict:
        st = self._sm.static()
        track = st.track + (f" ({st.trackConfiguration})" if st.trackConfiguration else "")
        return {
            "source": self.name,
            "car": st.carModel,
            "track": track,
            "track_length": float(st.trackSPlineLength),
            "max_rpm": int(st.maxRpm),
            "max_fuel": float(st.maxFuel),
            "sector_count": int(st.sectorCount),
            "player": f"{st.playerName} {st.playerSurname}".strip(),
        }

    def sample(self) -> TelemetrySample:
        phy = self._sm.physics()
        gfx = self._sm.graphics()
        try:
            status = ACStatus(gfx.status)
        except ValueError:
            status = ACStatus.OFF
        try:
            session_type = ACSessionType(gfx.session)
        except ValueError:
            session_type = ACSessionType.UNKNOWN
        return TelemetrySample(
            t=time.perf_counter(),
            packet_id=phy.packetId,
            status=status,
            session_type=session_type,
            speed_kmh=phy.speedKmh,
            rpm=phy.rpms,
            gear=phy.gear,
            gas=phy.gas,
            brake=phy.brake,
            clutch=phy.clutch,
            steer_angle=phy.steerAngle,
            fuel=phy.fuel,
            acc_g=(phy.accG[0], phy.accG[1], phy.accG[2]),
            tyre_core_temp=_quad(phy.tyreCoreTemperature),
            tyre_pressure=_quad(phy.wheelsPressure),
            tyre_wear=_quad(phy.tyreWear),
            wheel_slip=_quad(phy.wheelSlip),
            brake_temp=_quad(phy.brakeTemp),
            suspension_travel=_quad(phy.suspensionTravel),
            ride_height=(phy.rideHeight[0], phy.rideHeight[1]),
            tc=phy.tc,
            abs=phy.abs,
            drs=phy.drs,
            kers_charge=phy.kersCharge,
            tyres_out=phy.numberOfTyresOut,
            air_temp=phy.airTemp,
            road_temp=phy.roadTemp,
            lap_time_ms=gfx.iCurrentTime,
            last_lap_ms=gfx.iLastTime,
            best_lap_ms=gfx.iBestTime,
            completed_laps=gfx.completedLaps,
            lap_position=gfx.normalizedCarPosition,
            sector_index=gfx.currentSectorIndex,
            last_sector_ms=gfx.lastSectorTime,
            is_in_pit=bool(gfx.isInPit or gfx.isInPitLane),
            position=gfx.position,
            car_x=gfx.carCoordinates[0],
            car_z=gfx.carCoordinates[2],
        )


def _bar(value: float, width: int = 10) -> str:
    filled = round(max(0.0, min(1.0, value)) * width)
    return "#" * filled + "." * (width - filled)


def _format_line(s: TelemetrySample) -> str:
    return (
        f"{s.speed_kmh:6.1f} km/h | {s.rpm:5d} rpm | marcia {gear_label(s.gear):>2} | "
        f"GAS [{_bar(s.gas)}] FRENO [{_bar(s.brake)}] FRIZ [{_bar(1.0 - s.clutch)}] | "
        f"sterzo {s.steer_angle:+.2f} | giro {s.completed_laps + 1} {s.lap_time_ms / 1000:7.3f}s"
    )


def run_console(hz: float) -> None:
    period = 1.0 / hz
    rx = TelemetryReceiver()
    waiting_msg_shown = False

    try:
        while True:
            if not rx.connect():
                if not waiting_msg_shown:
                    print("In attesa di Assetto Corsa (avvia una sessione da Content Manager)...", flush=True)
                    waiting_msg_shown = True
                time.sleep(1.0)
                continue

            car, track = rx.car_and_track()
            print(f"Agganciato ad AC  ->  auto: {car or '?'}  |  pista: {track or '?'}", flush=True)
            waiting_msg_shown = False

            last_packet = None
            stale_since = time.perf_counter()
            next_tick = time.perf_counter()
            while True:
                s = rx.sample()

                if s.packet_id != last_packet:
                    last_packet = s.packet_id
                    stale_since = s.t
                elif s.t - stale_since > 5.0 and s.status == ACStatus.OFF:
                    # AC chiuso o tornato ai menu: la mapping resta ma non viene più aggiornata.
                    print("\nAC non sta più aggiornando i dati, riaggancio...")
                    rx.disconnect()
                    break

                if s.status == ACStatus.LIVE:
                    line = _format_line(s)
                else:
                    line = f"[{s.status.name}] in attesa di sessione di guida..."
                sys.stdout.write("\r" + line.ljust(140))
                sys.stdout.flush()

                next_tick += period
                delay = next_tick - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_tick = time.perf_counter()
    except KeyboardInterrupt:
        print("\nInterrotto.")
    finally:
        rx.disconnect()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Telemetria live da Assetto Corsa (shared memory)")
    parser.add_argument("--hz", type=float, default=60.0, help="frequenza di campionamento (default 60)")
    args = parser.parse_args(argv)
    run_console(args.hz)


if __name__ == "__main__":
    main()
