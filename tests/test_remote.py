"""Remote access: rotating code, attempt limits, tokens, and the web server end to end on localhost."""

import json
import urllib.error
import urllib.request

import pytest

from hub_core.remote import auth
from hub_core.remote.auth import PairError, Pairing, hotp
from hub_core.remote.server import RemoteServer


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_hotp_matches_rfc4226():
    secret = b"12345678901234567890"
    assert [hotp(secret, i) for i in range(3)] == ["755224", "287082", "359152"]


def test_code_changes_every_10_seconds_and_works_once():
    clk = Clock()
    p = Pairing(clock=clk)
    code, left = p.current_code()
    assert len(code) == 6 and 0 < left <= 10
    clk.t += 10
    assert p.current_code()[0] != code
    token = p.pair(code, "Tablet", "10.0.0.2")          # previous window still accepted
    assert p.check(token).name == "Tablet"
    with pytest.raises(PairError):
        p.pair(code, "Again", "10.0.0.2")                # used


def test_expired_code_is_refused():
    clk = Clock()
    p = Pairing(clock=clk)
    code = p.current_code()[0]
    clk.t += 25
    with pytest.raises(PairError):
        p.pair(code, "Late", "10.0.0.2")


def test_attempts_are_limited_per_address_and_overall():
    clk = Clock()
    p = Pairing(clock=clk)
    wrong = "000000" if p.current_code()[0] != "000000" else "111111"
    for _ in range(auth.IP_MAX_FAILS):
        with pytest.raises(PairError):
            p.pair(wrong, "x", "10.0.0.9")
    with pytest.raises(PairError) as e:
        p.pair(p.current_code()[0], "x", "10.0.0.9")      # even the right code: wait first
    assert e.value.retry_after > 0
    assert p.pair(p.current_code()[0], "ok", "10.0.0.10")  # another address is not blocked
    clk.t += auth.IP_WINDOW_S + 1
    p2 = Pairing(clock=clk)
    for i in range(auth.ALL_MAX_FAILS):
        with pytest.raises(PairError):
            p2.pair(wrong if hotp(p2.secret, p2._counter()) != wrong else "222222", "x", f"10.1.{i}.1")
    with pytest.raises(PairError) as e:
        p2.pair(p2.current_code()[0], "x", "10.2.0.1")
    assert e.value.retry_after > 0


def test_tokens_revoke_and_persist_only_hashes():
    p = Pairing(clock=Clock())
    token = p.pair(p.current_code()[0], "PC", "10.0.0.2")
    saved = p.export()
    assert token not in json.dumps(saved)
    q = Pairing()
    q.load(saved)
    assert q.check(token) is not None and q.check("nope") is None
    q.revoke(saved[0]["id"])
    assert q.check(token) is None


class FakeProvider:
    def __init__(self):
        self.actions = []

    def snapshot(self, since, laps_known):
        return {"live": {"on_track": True, "position": 3}, "since": since, "laps_known": laps_known}

    def action(self, device, kind, payload):
        self.actions.append((device, kind, payload.get("text")))
        return {"ok": True}


def call(url, path, body=None, token=None):
    req = urllib.request.Request(url + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def test_server_pairs_then_serves_state_and_actions():
    pairing, provider = Pairing(), FakeProvider()
    srv = RemoteServer(provider, pairing, port=18790, host="127.0.0.1")
    assert srv.start()
    url = f"http://127.0.0.1:{srv.port}"
    try:
        status, page, headers = call(url, "/")
        assert status == 200 and b"Delta Suite" in page and headers["X-Frame-Options"] == "DENY"
        assert call(url, "/api/state")[0] == 401
        assert call(url, "/api/pair", {"code": "000000" if pairing.current_code()[0] != "000000" else "1",
                                       "name": "x"})[0] == 403
        status, body, _ = call(url, "/api/pair", {"code": pairing.current_code()[0], "name": "Pit wall"})
        token = json.loads(body)["token"]
        status, body, _ = call(url, "/api/state?since=5&laps=2", token=token)
        assert status == 200 and json.loads(body) == {"live": {"on_track": True, "position": 3}, "since": 5,
                                                      "laps_known": 2}
        assert json.loads(call(url, "/api/action", {"kind": "say", "text": "Box this lap"}, token)[1])["ok"]
        assert provider.actions == [("Pit wall", "say", "Box this lap")]
        assert call(url, "/api/logout", {}, token)[0] == 200
        assert call(url, "/api/state", token=token)[0] == 401
    finally:
        srv.stop()
