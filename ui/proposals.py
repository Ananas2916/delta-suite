"""The engineer's proposals: pending, confirmed (now or in the pits), sent to the CSP app, applied or failed."""

from __future__ import annotations

from ai_engine.voice import PRIO_HIGH, PRIO_NORMAL
from hub_core.ac.csp_bridge import BridgeState
from ui.hub_data import KIND_CMD, Proposal


class ProposalController:
    """Owned by HubState: it emits hub.proposals_changed and speaks through hub.radio."""

    def __init__(self, hub):
        self.hub = hub
        self.items: list[Proposal] = []
        hub.proposal_requested.connect(self.add)        # thread-safe: MCP threads emit, the UI thread adds

    def _say(self, text: str, priority: int, ttl_s: float = 30.0):
        if self.hub.radio_active:
            self.hub.radio.say(text, priority, ttl_s)

    def add(self, p: Proposal):
        self.items.append(p)
        self.hub.radio_log.emit("engineer", f"Proposal: {p.describe()} — {p.reason}")
        r = self.hub.radio
        self._say(r.phrase("proposal", what=p.spoken(r.lang), reason=p.reason), PRIO_HIGH, 60)
        self.hub.proposals_changed.emit()

    def pending(self) -> list[Proposal]:
        return [p for p in self.items if p.status == "pending"]

    def _find(self, pid: int) -> Proposal | None:
        return next((x for x in self.items if x.id == pid), None)

    def confirm_latest(self):
        pend = self.pending()
        if pend:
            self.apply(pend[-1].id)

    def discard_latest(self):
        pend = self.pending()
        if pend:
            self.discard(pend[-1].id)

    def apply(self, pid: int):
        p = self._find(pid)
        if p is None or p.status not in ("pending", "error"):
            return
        b = self.hub.bridge_state
        if p.kind == "setup" and not (b and b.setup_editable):
            p.status, p.result = "in pits", "confirmed: applied as soon as you enter the pits"
            self._say(self.hub.radio.phrase("at_box"), PRIO_NORMAL)
        else:
            self._send(p)
        self.hub.proposals_changed.emit()

    def _send(self, p: Proposal):
        seq = self.hub.send_command(KIND_CMD[p.kind], p.value, p.name)
        if seq is None:
            p.status, p.result = "error", "CSP app not connected"
        else:
            p.status, p.seq = "sent", seq
        self.hub.proposals_changed.emit()

    def discard(self, pid: int):
        p = self._find(pid)
        if p is not None and p.status in ("pending", "in pits", "error"):
            p.status = "discarded"
            self._say(self.hub.radio.phrase("discarded"), PRIO_NORMAL, 15)
            self.hub.proposals_changed.emit()

    def on_bridge(self, b: BridgeState, was_editable: bool):
        """Acks of the commands sent, and setup changes waiting for the pits once they become editable."""
        r = self.hub.radio
        for p in self.items:
            if p.status == "sent" and p.seq is not None and b.ack_seq == p.seq:
                p.status = "applied" if b.ack_ok else "error"
                p.result = b.ack_msg
                self._say(r.phrase("done", what=p.spoken(r.lang)) if b.ack_ok else
                          r.phrase("failed", msg=b.ack_msg), PRIO_HIGH, 20)
                self.hub.radio_log.emit("system", f"{p.describe()}: {b.ack_msg}")
                self.hub.proposals_changed.emit()
        if b.setup_editable and not was_editable:
            for p in self.items:
                if p.status == "in pits":
                    self._send(p)
