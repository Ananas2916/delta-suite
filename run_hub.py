"""Hub launcher: python run_hub.py (also the executable's entry point)."""

import ctypes
import sys

from ui.main_dashboard import main

if __name__ == "__main__":
    if sys.platform == "win32":
        # own taskbar icon instead of python.exe's
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DeltaSuite.App")
    main()
