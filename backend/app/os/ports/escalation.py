"""The EscalationSink port (Slice 8 spec §2.2, S8-D12; promised by Slice 7 S7-D10). Every support case is opened
through it: the standalone adapter always writes the case, and the Counsellor adapter (Task 7) may also tell the
Counsellor."""

from typing import Protocol


class EscalationSink(Protocol):
    def escalate(self, plan_id: int, event_ids: list[int], reason: str, proposal_id: int | None = None) -> int:
        """Opens (or reuses) the support case for these events and returns its id."""
        ...
