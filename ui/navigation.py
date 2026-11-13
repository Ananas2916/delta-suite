"""The views in the top bar: key, name and description (the tooltip). Settings has its own button."""

from __future__ import annotations

VIEWS = [
    ("home", "Home", "Ready to drive: what is connected, your last session and your personal bests."),
    ("race", "Race", "Everything at once, like on the pit wall: onboard, standings, track map, car status, "
     "radio and the engineer's proposals."),
    ("onboard", "Onboard", "Up to 4 onboards at once rendered by AC (rivals too) with TV graphics, standings, "
     "track map and car status."),
    ("telemetry", "Telemetry", "60–200 Hz acquisition from Assetto Corsa: live channels, recording and replay "
     "(replaces MoTeC i2 · ATLAS · WinDARAB)."),
    ("box", "Pit & Setup", "Live brake bias, ABS, TC and engine brake, setup from the pits, the engineer's "
     "proposals and standings with gaps."),
    ("strategy", "Strategy", "Fuel plan, pit window, tyre degradation forecast, optimal stop, sectors and ideal "
     "lap (replaces HH Timing · SBG RaceWatch)."),
    ("analysis", "Analysis", "Overlaid laps, Delta-T and corners, archive and export; vehicle dynamics "
     "(replaces MoTeC i2 · Pi Toolbox · ChassisSim)."),
    ("engineer", "Engineer", "Chat and headset radio with the AI engineer, stint summary, voice and radio "
     "settings."),
    ("ambient", "Ambient", "Full screen for a second monitor: delta in big numbers, green or red, yellow edge on "
     "a flag, blue when a rival is within a second."),
]

# views with the live strip on top (position, lap, gaps, fuel, battery)
LIVE_VIEWS = {"race", "onboard", "telemetry", "box", "strategy", "engineer"}
