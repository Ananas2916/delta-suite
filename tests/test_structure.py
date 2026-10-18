"""Confini tra i pacchetti: chi può importare chi (vedi ARCHITECTURE.md)."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def imported_modules(path: Path) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def violations(folder: str, forbidden: tuple[str, ...]) -> list[str]:
    bad = []
    base = ROOT / folder
    for path in [base] if base.is_file() else sorted(base.rglob("*.py")):
        for mod in imported_modules(path):
            if any(mod == f or mod.startswith(f + ".") for f in forbidden):
                bad.append(f"{path.relative_to(ROOT).as_posix()} importa {mod}")
    return bad


def test_hub_core_has_no_ui():
    assert violations("hub_core", ("PyQt6", "pyqtgraph", "ui", "ai_engine")) == []


def test_analysis_does_not_touch_ac():
    # i calcoli girano uguali su dati veri, demo e replay: niente shared memory né app CSP
    assert violations("hub_core/analysis", ("hub_core.ac", "ctypes")) == []


def test_model_is_plain_data():
    assert violations("hub_core/model.py", ("hub_core", "ctypes")) == []


def test_ai_engine_has_no_ui():
    assert violations("ai_engine", ("PyQt6", "pyqtgraph", "ui")) == []


def test_widgets_do_not_know_pages():
    # i widget (classifica, GPS, schema dell'auto...) li usano più pagine: non dipendono da nessuna
    assert violations("ui/widgets", ("ui.pages", "ui.hub_state", "ui.main_dashboard")) == []


def test_pages_do_not_import_each_other():
    bad = []
    pages = ROOT / "ui" / "pages"
    for path in sorted(pages.rglob("*.py")):
        rel = path.relative_to(pages)
        own = f"ui.pages.{rel.parts[0].removesuffix('.py')}"
        for mod in imported_modules(path):
            if mod.startswith("ui.pages.") and not (mod == own or mod.startswith(own + ".")):
                bad.append(f"{rel.as_posix()} importa {mod}")
    assert bad == []
