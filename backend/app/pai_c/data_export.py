"""Owner-only student-visible data export. No private model interpretation."""
from datetime import datetime, timezone
import os
from sqlalchemy import select
from app.models import EventRecord, FileRecord, StudentJourney, CounselorMirrorFeedback
from app.pai_c.memory import MemoryService
from app.pai_c.possibilities import PossibilityService
from app.pai_c.roadmaps.service import RoadmapService
from app.pai_c.redaction import redact, _ENV_SECRET


def export_student_data(db, workspace_id):
    with db.no_autoflush:
        memory = MemoryService(db)
        events = db.scalars(select(EventRecord).where(EventRecord.network_id == workspace_id,
            EventRecord.type == 'workspace.message.posted').order_by(EventRecord.timestamp, EventRecord.id)).all()
        conversation = [{'id': e.id, 'timestamp': e.timestamp,
            'role': 'student' if (e.source or '').startswith('human:') else 'pai',
            'content': (e.payload or {}).get('content', ''),
            'message_type': (e.payload or {}).get('message_type', 'chat')}
            for e in events if ((e.source or '').startswith('human:') or e.source == 'openagents:pai')
            and (e.payload or {}).get('message_type', 'chat') in {'chat', 'counselor_mirror', 'operator_result'}]
        journeys = db.scalars(select(StudentJourney).where(StudentJourney.workspace_id == workspace_id)).all()
        files = db.scalars(select(FileRecord).where(FileRecord.workspace_id == workspace_id,
            FileRecord.status == 'active').order_by(FileRecord.created_at)).all()
        feedback = db.scalars(select(CounselorMirrorFeedback).where(CounselorMirrorFeedback.workspace_id == workspace_id)
            .order_by(CounselorMirrorFeedback.created_at)).all()
        service = PossibilityService(db)
        roadmaps = RoadmapService(db)
        result = {'exported_at': datetime.now(timezone.utc), 'workspace_id': workspace_id,
            'scope': 'Student-visible profile, conversation, paths, roadmaps, confirmed picture and ratings; document metadata. Download document bytes from Documents. Private model notes and credential data are excluded.',
            'profile': memory.profile_cards(workspace_id), 'personal': memory.personal_view(workspace_id),
            'sections': memory.profile_sections(workspace_id), 'capabilities': memory.capability_view(workspace_id), 'conversation': conversation,
            'paths': [service.serialize(row) for row in service.list(workspace_id)],
            'roadmaps': [*roadmaps.list(workspace_id), *roadmaps.list(workspace_id, 'dismissed')],
            'mirrors': [{'journey_id': row.id, 'version': row.counselor_summary_draft.get('version'),
                'mirror': row.counselor_summary_draft.get('mirror')}
                for row in journeys if (row.counselor_summary_draft or {}).get('status') == 'confirmed'],
            'ratings': [{'version': row.mirror_version, 'understood': row.understood,
                'certainty_before': row.certainty_before, 'certainty_after': row.certainty_after} for row in feedback],
            'documents': [{'id': row.id, 'filename': row.filename, 'content_type': row.content_type,
                'size': row.size, 'created_at': row.created_at} for row in files]}
        return redact(result, [v for k,v in os.environ.items() if _ENV_SECRET.search(k) and v])
