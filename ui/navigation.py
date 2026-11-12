"""Hub modules in the sidebar: sections, names and descriptions (used as tooltips)."""

from __future__ import annotations

# the first entry, outside the sections: the pit-wall overview
GENERAL = ("general", "Overview", "Everything at once, like on the pit wall: onboard, standings, GPS, car status, "
           "fuel and battery, radio and the engineer's proposals.")

# modules grouped as in the sidebar: (page key, name, description, replaces)
SECTIONS = [
    ("On track", [
        ("telemetry", "Live telemetry", "60–100 Hz acquisition from Assetto Corsa's shared memory, "
         "session recording and replay.", "MoTeC i2 · ATLAS · WinDARAB"),
        ("onboard", "Live onboard", "Up to 4 onboards at once rendered by AC (rivals too) with TV graphics, "
         "standings, track GPS and car status: damage, tyres, brakes, suspension, battery.",
         "Pit-wall onboard feeds"),
        ("engineer", "Race engineer", "Analysis chat and headset radio with the same agent (Claude Code or "
         "another): push-to-talk from the wheel, automatic radio on lap, fuel, tyres and flags, setup "
         "proposals to confirm.", "Team engineer and radio"),
        ("box", "Pit & Setup", "Live brake bias, ABS, TC and engine brake, setup from the pits, the engineer's "
         "proposals and standings with gaps.", "Pit wall"),
    ]),
    ("Analysis & strategy", [
        ("analysis", "Lap analysis", "Overlaid laps by distance, Delta-T, racing line, synced cursor, "
         "DuckDB archive and Parquet export.", "MoTeC i2 · Pi Toolbox"),
        ("strategy", "Strategy & Timing", "Average fuel use, pit window, tyre degradation forecast, optimal stop, "
         "sectors and ideal lap.", "HH Timing · SBG RaceWatch"),
        ("dynamics", "Vehicle dynamics", "Pacejka tyre, friction ellipse, load transfer with aero, "
         "double-wishbone kinematics and roll centre.", "ChassisSim · OptimumG · Adams"),
    ]),
]

