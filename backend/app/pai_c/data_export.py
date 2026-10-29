"""Owner-only student-visible data export. No private model interpretation."""
from datetime import datetime, timezone
import os
from sqlalchemy import select
from app.models import EventRecord, FileRecord, RouteDecision
from app.pai_c.memory import MemoryService
from app.pai_c.possibilities import PossibilityService
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
        files = db.scalars(select(FileRecord).where(FileRecord.workspace_id == workspace_id,
            FileRecord.status == 'active').order_by(FileRecord.created_at)).all()
        from app.pai_c.mirror import MirrorEngine
        card = MirrorEngine(db).build(workspace_id)
        service = PossibilityService(db)
        decisions = db.scalars(select(RouteDecision).where(RouteDecision.workspace_id == workspace_id)
            .order_by(RouteDecision.chosen_at, RouteDecision.id)).all()
        result = {'exported_at': datetime.now(timezone.utc), 'workspace_id': workspace_id,
            'scope': 'Student-visible profile, conversation, paths, chosen routes, the Mirror; document metadata. Download document bytes from Documents. Private model notes and credential data are excluded.',
            'profile': memory.profile_cards(workspace_id), 'personal': memory.personal_view(workspace_id),
            'sections': memory.profile_sections(workspace_id), 'capabilities': memory.capability_view(workspace_id), 'conversation': conversation,
            'paths': [service.serialize(row) for row in service.list(workspace_id)],
            'route_decisions': [{'id': row.id, 'field_key': row.field_key, 'possibility_id': row.possibility_id,
                'title': row.title, 'chosen_at': row.chosen_at, 'withdrawn_at': row.withdrawn_at,
                'steps': row.steps, 'steps_done': row.steps_done, 'route': row.route} for row in decisions],
            # The Mirror as the student sees it: the education line, what is
            # still unknown and the text (FOUR_FEATURES_SPEC 2.3).
            'mirror': {'header': card['header'], 'unknowns': card['unknowns'], 'text': card['text'],
                'ready': card['ready'], 'version': card['version']},
            'documents': [{'id': row.id, 'filename': row.filename, 'content_type': row.content_type,
                'size': row.size, 'created_at': row.created_at} for row in files]}
        return redact(result, [v for k,v in os.environ.items() if _ENV_SECRET.search(k) and v])
