from hub_core.ac import csp_bridge
from ui import first_run as fr


class FakeSTT:
    def available(self):
        return True, ""


class FakeHub:
    def __init__(self, **settings):
        self.settings_map = {"voice/engine": "none", **settings}
        self.bridge_state = None
        self.stt = FakeSTT()

    def setting(self, key, default, typ=str):
        return self.settings_map.get(key, default)


def keys(items, state):
    return {i.key for i in items if i.state == state}


def test_without_ac_and_without_agent(monkeypatch):
    monkeypatch.setattr(fr, "find_executable", lambda name: None)
    items = fr.checklist(FakeHub(), None)
    assert keys(items, fr.TODO) == {"ac", "agent"} and not fr.all_done(items)
    agent = next(i for i in items if i.key == "agent")
    assert agent.action_key == "open_engineer"


def test_csp_app_states(tmp_path, monkeypatch):
    monkeypatch.setattr(fr, "find_executable", lambda name: "claude.exe")
    hub = FakeHub()
    items = fr.checklist(hub, tmp_path)                        # AC found, app missing
    assert next(i for i in items if i.key == "csp").action_key == "install_csp"
    csp_bridge.install_app(tmp_path)
    items = fr.checklist(hub, tmp_path)
    assert next(i for i in items if i.key == "csp").state == fr.WAIT      # installed, waits for AC
    hub.bridge_state = object()
    hub.settings_map["checklist/wheel_used"] = True
    assert fr.all_done(fr.checklist(hub, tmp_path))
