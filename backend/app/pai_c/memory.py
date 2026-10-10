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

    def understanding_summary(self, workspace_id):
        notebook = self.truth_map(workspace_id).notebook.model_dump(mode="json")
        return {key: notebook[key] for key in ("said", "source", "pressures", "self", "sure")}

    def foundation_ready(self, truth_map):
        from app.pai_c.deep.coverage import foundation_ready
        return foundation_ready(truth_map)

    def delete_for_workspace(self, workspace_id):
        return NotebookService(self.db).delete_for_workspace(workspace_id)

    def export_truth_map(self, workspace_id):
        from sqlalchemy import select
        from app.models import CounselorNotebook, CounselorNotebookHistory
        from app.pai_c.deep.notebook_schema import CounselorNotebookData
        def export_row(row):
            data = {column.key: getattr(row, column.key) for column in row.__table__.columns}
            data["notebook"] = CounselorNotebookData.model_validate(row.notebook).export_data()
            return data
        latest = self.db.scalar(select(CounselorNotebook).where(CounselorNotebook.workspace_id == workspace_id))
        history = self.db.scalars(select(CounselorNotebookHistory).where(CounselorNotebookHistory.workspace_id == workspace_id).order_by(CounselorNotebookHistory.version)).all()
        return {"latest": export_row(latest) if latest else None, "history": [export_row(row) for row in history]}
