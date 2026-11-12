"""Session/lap/sample archive on DuckDB, with Parquet export."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np

from hub_core.analysis.lap_recorder import CHANNELS, LapData


def default_db_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DeltaSuite"
    base.mkdir(parents=True, exist_ok=True)
    return base / "telemetry.duckdb"


_SCHEMA = f"""
CREATE SEQUENCE IF NOT EXISTS session_seq START 1;
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY DEFAULT nextval('session_seq'),
    started TIMESTAMP,
    source VARCHAR,
    car VARCHAR,
    track VARCHAR,
    track_length DOUBLE,
    max_fuel DOUBLE
);
CREATE TABLE IF NOT EXISTS laps (
    session_id INTEGER,
    lap_no INTEGER,
    lap_time_ms INTEGER,
    valid BOOLEAN,
    sectors_ms INTEGER[],
    fuel_start DOUBLE,
    fuel_end DOUBLE,
    tyre_temp_avg DOUBLE[],
    tyre_press_avg DOUBLE[],
    tyre_wear_end DOUBLE[],
    brake_temp_max DOUBLE[],
    max_speed DOUBLE
);
CREATE TABLE IF NOT EXISTS samples (
    session_id INTEGER,
    lap_no INTEGER,
    {", ".join(f"{c} DOUBLE" for c in CHANNELS)}
);
"""


class TelemetryDB:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_db_path()
        self.con = duckdb.connect(str(self.path))
        self.con.execute(_SCHEMA)

    def close(self):
        self.con.close()

    def thread_view(self) -> "TelemetryDB":
        """Same API on a dedicated cursor, for threads other than the UI thread."""
        view = TelemetryDB.__new__(TelemetryDB)
        view.path = self.path
        view.con = self.con.cursor()
        return view

    def new_session(self, info: dict) -> int:
        row = self.con.execute(
            "INSERT INTO sessions (started, source, car, track, track_length, max_fuel) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
            [datetime.now(), info.get("source", ""), info.get("car", ""), info.get("track", ""),
             float(info.get("track_length", 0.0)), float(info.get("max_fuel", 0.0))],
        ).fetchone()
        return int(row[0])

    def save_lap(self, session_id: int, lap: LapData) -> None:
        self.con.execute(
            "INSERT INTO laps VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [session_id, lap.lap_no, lap.lap_time_ms, lap.valid, lap.sectors_ms, lap.fuel_start,
             lap.fuel_end, lap.tyre_temp_avg, lap.tyre_press_avg, lap.tyre_wear_end,
             lap.brake_temp_max, lap.max_speed],
        )
        n = len(lap.channels["t"])
        lap_frame = {"session_id": np.full(n, session_id, dtype=np.int32),
                     "lap_no": np.full(n, lap.lap_no, dtype=np.int32)}
        lap_frame.update({c: lap.channels[c] for c in CHANNELS})
        self.con.register("lap_frame", lap_frame)
        try:
            self.con.execute("INSERT INTO samples SELECT * FROM lap_frame")
        finally:
            self.con.unregister("lap_frame")

    def sessions(self) -> list[dict]:
        rows = self.con.execute(
            """SELECT s.id, s.started, s.source, s.car, s.track, s.track_length, s.max_fuel, count(l.lap_no),
                      min(l.lap_time_ms) FILTER (WHERE l.valid)
               FROM sessions s LEFT JOIN laps l ON l.session_id = s.id
               GROUP BY ALL ORDER BY s.id DESC"""
        ).fetchall()
        keys = ("id", "started", "source", "car", "track", "track_length", "max_fuel", "laps", "best_ms")
        return [dict(zip(keys, r)) for r in rows]

    def laps(self, session_id: int) -> list[LapData]:
        rows = self.con.execute(
            "SELECT * EXCLUDE (session_id) FROM laps WHERE session_id = ? ORDER BY lap_no", [session_id]
        ).fetchall()
        return [LapData(*r) for r in rows]

    def lap_channels(self, session_id: int, lap_no: int) -> dict[str, np.ndarray]:
        res = self.con.execute(
            f"SELECT {', '.join(CHANNELS)} FROM samples WHERE session_id = ? AND lap_no = ? ORDER BY t",
            [session_id, lap_no],
        ).fetchnumpy()
        return {c: np.asarray(res[c], dtype=np.float64) for c in CHANNELS}

    def best_laps(self, car: str, track: str, limit: int = 10, exclude_session: int | None = None) -> list[dict]:
        """Fastest valid laps ever driven with this car on this track (all sessions), fastest first."""
        rows = self.con.execute(
            """SELECT l.session_id, l.lap_no, l.lap_time_ms, s.started
               FROM laps l JOIN sessions s ON s.id = l.session_id
               WHERE s.car = ? AND s.track = ? AND l.valid AND l.lap_time_ms > 0 AND s.id IS DISTINCT FROM ?
               ORDER BY l.lap_time_ms LIMIT ?""",
            [car, track, exclude_session, limit],
        ).fetchall()
        return [dict(zip(("session_id", "lap_no", "lap_time_ms", "started"), r)) for r in rows]

    def delete_session(self, session_id: int) -> None:
        for table, col in (("samples", "session_id"), ("laps", "session_id"), ("sessions", "id")):
            self.con.execute(f"DELETE FROM {table} WHERE {col} = ?", [session_id])

    def export_parquet(self, session_id: int, path: str | Path) -> None:
        target = str(path).replace("'", "''")
        self.con.execute(
            f"COPY (SELECT * FROM samples WHERE session_id = {int(session_id)} ORDER BY lap_no, t) "
            f"TO '{target}' (FORMAT PARQUET)"
        )
