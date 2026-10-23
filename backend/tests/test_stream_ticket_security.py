"""Security invariants for short-lived, owner-scoped stream tickets."""

import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.security import stream_ticket


class StreamTicketSecurityTests(unittest.TestCase):
    def setUp(self):
        self.workspace = SimpleNamespace(
            id="workspace-a", owner_user_id="user-a", password_hash="test-only-secret"
        )
        self.user = SimpleNamespace(id="user-a", firebase_uid="uid-a")
        self.db = SimpleNamespace(get=lambda model, user_id: self.user if user_id == "user-a" else None)

    def mint(self, *args, **kwargs):
        return stream_ticket.mint(*args, subject="uid-a", **kwargs)

    def verify(self, workspace, ticket, scope):
        return stream_ticket.verify(workspace, ticket, scope, db=self.db)

    def test_owner_ticket_is_valid_only_for_its_workspace_and_scope(self):
        ticket = self.mint(self.workspace, "user-a", scopes=[stream_ticket.EVENTS_SCOPE])
        self.assertTrue(self.verify(self.workspace, ticket, stream_ticket.EVENTS_SCOPE))
        self.assertFalse(self.verify(self.workspace, ticket, stream_ticket.FILES_SCOPE))
        other = SimpleNamespace(id="workspace-b", owner_user_id="user-a", password_hash="test-only-secret")
        self.assertFalse(self.verify(other, ticket, stream_ticket.EVENTS_SCOPE))

    def test_nonowner_cannot_mint_or_reuse_a_ticket(self):
        self.assertIsNone(self.mint(self.workspace, "user-b"))
        ticket = self.mint(self.workspace, "user-a")
        self.workspace.owner_user_id = "user-b"
        self.assertFalse(self.verify(self.workspace, ticket, stream_ticket.EVENTS_SCOPE))

    def test_expired_or_tampered_ticket_is_rejected(self):
        with patch.object(stream_ticket.time, "time", return_value=100):
            ticket = self.mint(self.workspace, "user-a", ttl_seconds=1)
        with patch.object(stream_ticket.time, "time", return_value=102):
            self.assertFalse(self.verify(self.workspace, ticket, stream_ticket.EVENTS_SCOPE))
        self.assertFalse(self.verify(self.workspace, ticket + "x", stream_ticket.EVENTS_SCOPE))

    def test_relinked_identity_invalidates_ticket(self):
        ticket = self.mint(self.workspace, "user-a")
        self.assertTrue(self.verify(self.workspace, ticket, stream_ticket.EVENTS_SCOPE))
        self.user.firebase_uid = "uid-b"
        self.assertFalse(self.verify(self.workspace, ticket, stream_ticket.EVENTS_SCOPE))

    def test_no_ticket_without_a_firebase_identity(self):
        self.assertIsNone(stream_ticket.mint(self.workspace, "user-a", subject=None))

    def test_ticket_lifetime_is_clamped(self):
        now = int(time.time())
        ticket = self.mint(self.workspace, "user-a", ttl_seconds=86400)
        payload = stream_ticket._unb64(ticket.split(".")[0]).decode()
        expires = int(payload.split(":")[3])
        self.assertLessEqual(expires, now + stream_ticket.TICKET_TTL_SECONDS + 1)


if __name__ == "__main__":
    unittest.main()
