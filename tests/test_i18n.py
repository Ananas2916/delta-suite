"""Every text wrapped in tr() has an Italian translation with the same {placeholders}."""

import ast
import string
from pathlib import Path

import pytest

from hub_core import i18n
from hub_core.locales import it

ROOT = Path(__file__).resolve().parents[1]
# texts translated where they are shown (tr(variable)): data tables defined elsewhere
DATA_KEYS = [
    ("hub_core/ac/onboard_feed.py", "CAMERAS"), ("hub_core/ac/onboard_feed.py", "CAMERA_GROUPS"),
    ("hub_core/ac/onboard_feed.py", "QUALITIES"), ("hub_core/analysis/car_status.py", "CORNERS"),
    ("hub_core/analysis/car_status.py", "DAMAGE_ZONES"), ("ui/navigation.py", "VIEWS"),
]


def tr_keys() -> dict[str, str]:
    """Literal first arguments of tr(...) in the code, with where they are."""
    keys = {}
    for folder in ("hub_core", "ui", "ai_engine"):
        for path in (ROOT / folder).rglob("*.py"):
            if "locales" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "tr" and node.args
                        and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                    keys.setdefault(node.args[0].value, f"{path.relative_to(ROOT)}:{node.lineno}")
    return keys


def fields(text: str) -> set[str]:
    return {name for _lit, name, _spec, _conv in string.Formatter().parse(text) if name}


def test_every_tr_text_is_translated():
    missing = [f"{where}: {key!r}" for key, where in tr_keys().items() if key not in it.CATALOG]
    assert missing == []


def test_placeholders_match():
    bad = [k for k, v in it.CATALOG.items() if fields(k) != fields(v)]
    assert bad == []


def test_data_tables_are_translated():
    from hub_core.ac import onboard_feed as ob
    from hub_core.analysis import car_status as cs
    from ui import navigation as nav
    texts = [n for _k, n in ob.CAMERAS] + [g for g, _ in ob.CAMERA_GROUPS] + [q[0] for q in ob.QUALITIES]
    texts += list(cs.CORNERS) + list(cs.DAMAGE_ZONES)
    for _key, name, desc in nav.VIEWS:
        texts += [name, desc]
    assert [t for t in texts if t not in it.CATALOG] == []


@pytest.fixture
def italian():
    i18n.set_language("it")
    yield
    i18n.set_language("en")


def test_alerts_follow_the_language(italian, sample):
    from hub_core.analysis import car_status as cs
    s = sample(tyre_pressure=(27.0, 11.0, 26.9, 27.2), fuel=3.0)
    texts = [a.text for a in cs.car_alerts(s, {"damage_rate": 1.0}, 2.5)]
    assert "Foratura? Gomma ant. dx a 11.0 psi" in texts and "Carburante per 1.2 giri" in texts


def test_unknown_language_falls_back_to_english():
    i18n.set_language("xx")
    assert i18n.language() == "en" and i18n.tr("Fuel for {n} laps", n=2) == "Fuel for 2 laps"
