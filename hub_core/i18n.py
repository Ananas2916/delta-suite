"""
Interface language. Texts are written in English in the code and wrapped in tr(); each other language has a
catalog in hub_core/locales/<code>.py mapping the English text to its translation.

    tr("Fuel for {n} laps", n=2.5)      # placeholders are filled after the lookup

The language is chosen once at startup (setting "ui/language"); changing it needs a restart. The radio
phrases are separate: they follow the chosen voice (ai_engine/lang.py).
"""

from __future__ import annotations

import importlib

LANGUAGES = {"en": "English", "it": "Italiano"}
# how the AI agent is told which language to write the analysis in
_AGENT_NAMES = {"en": "English", "it": "italiano"}

_lang = "en"
_catalog: dict[str, str] = {}


def set_language(code: str) -> None:
    global _lang, _catalog
    code = code if code in LANGUAGES else "en"
    _lang = code
    _catalog = {} if code == "en" else importlib.import_module(f"hub_core.locales.{code}").CATALOG


def language() -> str:
    return _lang


def language_name(code: str | None = None) -> str:
    return _AGENT_NAMES.get(code or _lang, "English")


def tr(text: str, **kw) -> str:
    """Translation of `text` in the interface language (the text itself if missing), with {placeholders} filled."""
    out = _catalog.get(text, text)
    return out.format(**kw) if kw else out
