"""Moduli dell'hub in barra laterale: sezioni, nomi e descrizioni (usate come suggerimento)."""

from __future__ import annotations

# la prima voce, fuori dalle sezioni: la panoramica da muretto
GENERAL = ("general", "Generale", "Tutto insieme, come al muretto: onboard, classifica, GPS, stato vettura, "
           "carburante e batteria, radio e proposte dell'ingegnere.")

# moduli raggruppati come nella barra laterale: (chiave pagina, nome, descrizione, al posto di)
SECTIONS = [
    ("In pista", [
        ("telemetry", "Telemetria live", "Acquisizione 60–100 Hz dalla shared memory di Assetto Corsa, "
         "registrazione delle sessioni e replay.", "MoTeC i2 · ATLAS · WinDARAB"),
        ("onboard", "Onboard live", "Fino a 4 onboard insieme resi da AC (anche sugli avversari) con grafica TV, "
         "classifica, GPS della pista e stato vettura: danni, gomme, freni, sospensioni, batteria.",
         "Feed onboard del muretto"),
        ("engineer", "Ingegnere di pista", "Chat di analisi e radio in cuffia con lo stesso agente (Claude Code o "
         "altro): push-to-talk dal volante, radio automatica su giro, carburante, gomme e bandiere, proposte di "
         "setup da confermare.", "Ingegnere e radio di squadra"),
        ("box", "Box & Assetto", "Bias freni, ABS, TC e freno motore in diretta, setup dai box, proposte "
         "dell'ingegnere e classifica con distacchi.", "Muretto box"),
    ]),
    ("Analisi e strategia", [
        ("analysis", "Analisi giri", "Giri sovrapposti su distanza, Delta-T, traiettoria, cursore sincronizzato, "
         "archivio DuckDB ed esportazione Parquet.", "MoTeC i2 · Pi Toolbox"),
        ("strategy", "Strategia & Timing", "Consumo medio, finestra pit, previsione degrado gomme, sosta ottimale, "
         "settori e giro ideale.", "HH Timing · SBG RaceWatch"),
        ("dynamics", "Dinamica veicolo", "Pneumatico Pacejka, ellisse d'attrito, trasferimenti di carico con aero, "
         "cinematica del quadrilatero e centro di rollio.", "ChassisSim · OptimumG · Adams"),
    ]),
]

