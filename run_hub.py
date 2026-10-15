"""Avvio dell'hub: python run_hub.py (è anche l'entry point dell'eseguibile)."""

import ctypes
import sys

from ui.main_dashboard import main

if __name__ == "__main__":
    if sys.platform == "win32":
        # icona propria nella barra delle applicazioni invece di quella di python.exe
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DeltaSuite.App")
    main()
