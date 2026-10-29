"""Student-selected family preparation, using only existing quoted evidence."""
import json
import hashlib
from pathlib import Path
from sqlalchemy import select
from app.models import PaiPossibility, ExecutionRun, CounselorTurnDecision, EventRecord
from app.pai_c.memory import MemoryService


def policy():
    return json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))


def prepare(db, workspace_id):
    rules = policy()
    latest = db.scalar(select(CounselorTurnDecision).where(CounselorTurnDecision.workspace_id == workspace_id)
        .order_by(CounselorTurnDecision.source_timestamp.desc()).limit(1))
    if latest and (latest.decision or {}).get('action') == 'care':
        return {'ready': False, 'message': rules['care'], 'family': [], 'evidence': []}
    path = db.scalar(select(PaiPossibility).where(PaiPossibility.workspace_id == workspace_id,
        PaiPossibility.status == 'chosen').order_by(PaiPossibility.updated_at.desc()).limit(1))
    runs = db.scalars(select(ExecutionRun).where(ExecutionRun.workspace_id == workspace_id,
        ExecutionRun.task_type == 'program_search', ExecutionRun.status == 'completed')).all()
    # Legacy choices without H proof do not open an institution-bearing script.
    if not path or not any((run.constraints or {}).get('possibility_id') == path.id for run in runs):
        return {'ready': False, 'message': rules['not_ready'], 'family': [], 'evidence': []}
    people = MemoryService(db).personal_view(workspace_id)['world']['people']
    family = [{key: person.get(key, '') for key in ('id', 'role', 'wish', 'worry', 'evidence')}
              for person in people if person.get('evidence')]
    # The student chooses the connection; code never claims a quote answers a worry.
    evidence = [{'id': hashlib.sha256(row['text'].encode()).hexdigest(), 'quote': row['text']} for row in path.evidence or []
                if isinstance(row, dict) and isinstance(row.get('text'), str) and row['text'].strip()
                and not row.get('source_url')]  # a field-note fact is the world's, not the student's words
    evidence = list({row['id']: row for row in evidence}.values())
    return {'ready': bool(family and evidence), 'path_id': path.id, 'path': path.title,
        'family': family, 'evidence': evidence,
        'message': rules['intro'] if family and evidence else rules['missing_family'] if not family else rules['missing_evidence']}


async def deliver(db, workspace_id, body):
    from app.pai_c.deep.analysis import _workspace_lock
    from app.pai_c.posting import send_to_student
    from app.services.pai import PAI_AGENT_NAME, PAI_PRIMARY_CHANNEL
    from app.pai_c.deep.polish import contains_blocked_script
    from app.config import config
    async with _workspace_lock(db, workspace_id):
        key = 'family-talk:' + str(body.submission_id)
        existing = db.scalar(select(EventRecord).where(EventRecord.network_id == workspace_id,
            EventRecord.metadata_['family_talk_key'].as_string() == key))
        if existing:
            if (existing.metadata_ or {}).get('family_talk_input') != body.model_dump(mode='json'):
                raise ValueError('Submission already used for another preparation')
            return {'event_id': existing.id, 'script': existing.payload['content']}
        guide = prepare(db, workspace_id)
        if not guide['ready'] or guide['path_id'] != body.path_id:
            raise ValueError(guide['message'])
        person = next((person for person in guide['family'] if person['id'] == body.person_id), None)
        evidence = [row for row in guide['evidence'] if row['id'] in body.evidence_ids]
        if not person or not person['worry'] or not evidence or len(evidence) != len(set(body.evidence_ids)):
            raise ValueError('Select a recorded concern and evidence from this path')
        rules = policy()
        quote = '\n'.join(row['quote'] for row in evidence[:rules['max_evidence']])
        script = rules['script'].format(worry=person['worry'], path=guide['path'], quote=quote)
        content = '\n\n'.join([rules['intro'], rules['worry'].format(**person),
            rules['wish'].format(**person) if person['wish'] else '', script]).strip()
        if contains_blocked_script(content, config.PAI_LANGUAGE_BLOCKED_SCRIPTS):
            raise ValueError('This evidence needs a supported-language review in chat')
        posted = await send_to_student(db, workspace_id, f'channel/{PAI_PRIMARY_CHANNEL}', PAI_AGENT_NAME,
            content, 0, metadata={'family_talk_key': key, 'family_talk_input': body.model_dump(mode='json')})
        if not posted:
            raise RuntimeError('Family preparation was not posted')
        return {'event_id': posted, 'script': content}
