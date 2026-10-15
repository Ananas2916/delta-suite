"""Genera assets/miohub.ico dal logo disegnato in ui/theme.py."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from ui.theme import app_icon_pixmap  # noqa: E402

if __name__ == "__main__":
    app = QApplication(sys.argv)
    out = ROOT / "assets" / "miohub.ico"
    out.parent.mkdir(exist_ok=True)
    if not app_icon_pixmap(256).save(str(out), "ICO"):
        sys.exit("Impossibile salvare l'icona")
    print(f"Icona scritta in {out}")
