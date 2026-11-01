"""pai-merge hand test: a workspace made while no PAI key was set had no PAI Counselor and no counsellor channel, so
the student's messages went to no one and the chat waited forever. Fictional data only."""
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select

from app.config import config
from app.database import Base
from app.eventing.events import Event
from app.eventing.handlers.messages import _handle_message_posted
from app.eventing.mods import PipelineContext
from app.models import Channel, ChannelMember, User, Workspace, WorkspaceMember
from app.security.access import get_or_create_owned_workspace
from app.services.pai import PAI_AGENT_NAME, PAI_PRIMARY_CHANNEL
from scripts.counselor_eval_support import StudentSession


def _bare(db, workspace_id):
    """The state a keyless workspace is left in: no PAI member, no counsellor channel."""
    db.execute(delete(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id))
    db.commit()


@pytest.mark.asyncio
async def test_a_message_to_the_counsellor_channel_reaches_pai_without_a_channel_row():
    with StudentSession() as student, student.factory() as db:
        Base.metadata.create_all(student.engine, tables=[Channel.__table__, ChannelMember.__table__])
        _bare(db, student.workspace_id)
        workspace = db.get(Workspace, student.workspace_id)
        event = Event(type="workspace.message.posted", source=f"human:{student.user_id}",
                      target=f"channel/{PAI_PRIMARY_CHANNEL}", payload={"content": "Hello"}, metadata={},
                      network=student.workspace_id)
        ctx = PipelineContext(network_id=student.workspace_id, agent_address=event.source, db=db, workspace=workspace)
        routed = await _handle_message_posted(event, ctx)
        assert routed.metadata["target_agents"] == [PAI_AGENT_NAME]


def test_opening_the_workspace_adds_pai_once_a_key_is_set(monkeypatch):
    with StudentSession() as student, student.factory() as db:
        Base.metadata.create_all(student.engine, tables=[Channel.__table__, ChannelMember.__table__])
        _bare(db, student.workspace_id)
        user = db.get(User, student.user_id)
        monkeypatch.setattr(config, "PAI_ENABLED", True)
        monkeypatch.setattr(config, "PAI_API_KEY", "")
        get_or_create_owned_workspace(db, user)
        assert db.scalar(select(WorkspaceMember.agent_name).where(WorkspaceMember.workspace_id == student.workspace_id)) is None
        monkeypatch.setattr(config, "PAI_API_KEY", "offline-test-key")
        get_or_create_owned_workspace(db, user)
        db.commit()
        member = db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == student.workspace_id,
                                                         WorkspaceMember.agent_name == PAI_AGENT_NAME))
        channel = db.scalar(select(Channel).where(Channel.workspace_id == student.workspace_id,
                                                  Channel.name == PAI_PRIMARY_CHANNEL))
        assert member is not None and channel is not None
