"""
First-run checklist: what is ready and what still needs doing, shown on the Overview until everything is green
(or the driver hides it). Each item says how to fix it; the action keys are handled by MainWindow.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_engine.agent_cli import find_executable
from ai_engine.voice import make_backend
from hub_core.ac import csp_bridge

DONE, TODO, WAIT = "done", "todo", "wait"     # WAIT: fine, it turns green by itself (e.g. once AC runs)


@dataclass(frozen=True)
class Item:
    key: str
    text: str
    state: str
    action: str = ""            # button text ("" = no button)
    action_key: str = ""        # what the button does (see MainWindow._on_checklist)


def _ac_items(hub, ac_root) -> list[Item]:
    if ac_root is None:
        return [Item("ac", "Assetto Corsa not found (Steam library)", TODO)]
    items = [Item("ac", "Assetto Corsa found", DONE)]
    installed = csp_bridge.installed_app_dir(ac_root)
    if installed is None or not installed.is_dir():
        items.append(Item("csp", "CSP app not installed: rivals, setup, onboard video and wheel buttons need it",
                          TODO, "Install", "install_csp"))
    elif csp_bridge.app_needs_update(ac_root):
        items.append(Item("csp", "CSP app outdated", TODO, "Update", "install_csp"))
    elif hub.bridge_state is not None:
        items.append(Item("csp", "CSP app connected", DONE))
    else:
        items.append(Item("csp", "CSP app installed: it connects once you drive in AC with the acquisition on",
                          WAIT, "Start", "open_telemetry"))
    if hub.setting("checklist/wheel_used", False, bool):
        items.append(Item("wheel", "Wheel buttons bound", DONE))
    else:
        items.append(Item("wheel", "Bind the wheel buttons in the Delta Suite Bridge window in game "
                          "(engineer radio, confirm, discard)", WAIT))
    return items


def _engineer_items(hub) -> list[Item]:
    backend = hub.setting("engineer/backend", "claude")
    if backend == "claude":
        agent_ok = find_executable("claude") is not None
        text = "AI engineer: Claude Code found" if agent_ok else "AI engineer: install Claude Code and log in"
    elif backend == "api":
        agent_ok = bool(hub.setting("api_key", ""))
        text = "AI engineer: API key set" if agent_ok else "AI engineer: enter your Anthropic API key"
    else:
        agent_ok = bool(hub.setting("engineer/custom_cmd", "").strip())
        text = "AI engineer: custom command set" if agent_ok else "AI engineer: set the custom command"
    items = [Item("agent", text, DONE if agent_ok else TODO, "" if agent_ok else "Settings", "open_engineer")]

    engine = hub.setting("voice/engine", "kokoro")
    voice_ok, _why = make_backend(engine, hub.setting("voice/voice", ""), 1.0,
                                  hub.setting("voice/model_dir", "") or None).available()
    if engine == "none":
        items.append(Item("voice", "Engineer voice switched off", DONE))
    elif voice_ok:
        items.append(Item("voice", "Engineer voice ready", DONE))
    elif engine == "kokoro":
        items.append(Item("voice", "Engineer voice: the voice model is not downloaded", TODO, "Download",
                          "download_voice"))
    else:
        items.append(Item("voice", "Engineer voice: Tsukumo is not answering", TODO, "Settings", "open_engineer"))

    stt_ok = hub.stt is not None and hub.stt.available()[0]
    items.append(Item("stt", "Push-to-talk transcription ready" if stt_ok else
                      "Push-to-talk: transcription not available", DONE if stt_ok else TODO,
                      "" if stt_ok else "Settings", "open_engineer"))
    return items


def checklist(hub, ac_root) -> list[Item]:
    """The items in order. `ac_root` is passed in because finding it reads the registry (cache it)."""
    return _ac_items(hub, ac_root) + _engineer_items(hub)


def all_done(items: list[Item]) -> bool:
    return all(i.state == DONE for i in items)
