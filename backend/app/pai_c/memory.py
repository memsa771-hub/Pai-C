"""PAI C facade; shared memory never depends on the Counselor."""

from app.memory.student_snapshot import StudentSnapshotService
from app.memory.episodic import EpisodicMemoryService
from app.memory.permissions import capabilities_for_agent
from app.pai_c.deep.notebook import NotebookService
from app.pai_c.deep.turn_input import shared_history


class MemoryService:
    def __init__(self, db):
        self.db = db

    def recent_turns(self, turn, owner_id, *, limit=24):
        return shared_history(self.db, turn, owner_id, limit=limit)

    def profile(self, workspace_id):
        return StudentSnapshotService(self.db).build(workspace_id)

    def truth_map(self, workspace_id):
        return NotebookService(self.db).get(workspace_id)

    def latest_episode(self, workspace_id, *, limit=1):
        return EpisodicMemoryService(self.db).recent(workspace_id, limit=limit)

    def agent_capabilities(self, agent_name):
        return capabilities_for_agent(agent_name)

    def apply_truth_map(self, workspace_id, new_notebook, source_event_id, *, expected_version=None):
        return NotebookService(self.db).apply(
            workspace_id, new_notebook, source_event_id, expected_version=expected_version)

    def enqueue_turn_extraction(self, **kwargs):
        # Preserve the existing validated candidate/reconciliation write path.
        from app.memory.turn_hook import enqueue_turn_extraction
        return enqueue_turn_extraction(db=self.db, **kwargs)
