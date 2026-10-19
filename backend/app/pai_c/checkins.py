"""Delayed in-app follow-ups on explicit choices, using the existing queue."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlalchemy import select
from app.models import EventRecord, Workspace, RoadmapStudentState, Roadmap, PaiPossibility, CounselorTurnDecision, ExecutionRun

JOB_CHECKIN = 'counselor.checkin'


def policy():
    return json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))


def schedule(db, workspace_id, kind, reference_id, *, at=None):
    from app.runtime.task_runtime import enqueue
    delay = policy()['delay_days'][kind]
    return enqueue(db, job_type=JOB_CHECKIN, workspace_id=workspace_id,
        payload={'kind': kind, 'reference_id': reference_id},
        idempotency_key=f'checkin:{workspace_id}:{kind}:{reference_id}',
        available_at=(at or datetime.now(timezone.utc)) + timedelta(days=delay))


def utc(stamp):
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp


async def checkin_job(job, db):
    from app.jobs.service import JobDeferred
    from app.pai_c.deep.analysis import _workspace_lock
    from app.pai_c.posting import send_to_student
    from app.services.pai import PAI_AGENT_NAME, PAI_PRIMARY_CHANNEL
    kind, reference = job.payload['kind'], job.payload['reference_id']
    rules = policy()
    if kind not in rules['delay_days']:
        raise ValueError('Unknown check-in kind')
    async with _workspace_lock(db, job.workspace_id):
        workspace = db.get(Workspace, job.workspace_id)
        if not workspace or workspace.status != 'active':
            return {'status': 'inactive'}
        if db.scalar(select(EventRecord.id).where(EventRecord.network_id == job.workspace_id,
                EventRecord.metadata_['checkin_key'].as_string() == job.idempotency_key).limit(1)):
            return {'status': 'already_posted'}
        if kind == 'chosen_path':
            current = db.scalar(select(Roadmap.id).join(RoadmapStudentState).where(Roadmap.workspace_id == job.workspace_id,
                Roadmap.id == reference, RoadmapStudentState.chosen_at.is_not(None)))
        else:
            run = db.scalar(select(ExecutionRun).where(ExecutionRun.id == reference,
                ExecutionRun.workspace_id == job.workspace_id, ExecutionRun.task_type == 'path_explain', ExecutionRun.status == 'completed'))
            current = db.scalar(select(PaiPossibility.id).where(PaiPossibility.workspace_id == job.workspace_id,
                PaiPossibility.id == ((run.constraints or {}).get('possibility_id') if run else ''), PaiPossibility.status != 'dismissed'))
        if current is None:
            return {'status': 'superseded'}
        last = db.scalar(select(CounselorTurnDecision).where(CounselorTurnDecision.workspace_id == job.workspace_id)
            .order_by(CounselorTurnDecision.source_timestamp.desc()).limit(1))
        now = datetime.now(timezone.utc)
        recent_student = db.scalar(select(EventRecord).where(EventRecord.network_id == job.workspace_id,
            EventRecord.source == f'human:{workspace.owner_user_id}', EventRecord.type == 'workspace.message.posted')
            .order_by(EventRecord.timestamp.desc()).limit(1))
        previous = db.scalar(select(EventRecord).where(EventRecord.network_id == job.workspace_id,
            EventRecord.metadata_['checkin_key'].as_string().is_not(None)).order_by(EventRecord.timestamp.desc()).limit(1))
        retry_hours = rules['care_retry_hours'] if last and (last.decision or {}).get('action') == 'care' else 0
        for event, hours in ((recent_student, rules['quiet_hours']), (previous, rules['minimum_spacing_hours'])):
            if event:
                remaining = hours - (now.timestamp() - event.timestamp / 1000) / 3600
                retry_hours = max(retry_hours, remaining)
        if retry_hours > 0:
            deferred = JobDeferred('Check-in waits for care, quiet time or spacing')
            deferred.delay_seconds = max(60, int(retry_hours * 3600))
            raise deferred
        posted = await send_to_student(db, job.workspace_id, f'channel/{PAI_PRIMARY_CHANNEL}', PAI_AGENT_NAME,
            rules[kind], 0, metadata={'checkin_key': job.idempotency_key, 'in_app_only': True})
        if not posted:
            raise RuntimeError('Check-in was not posted')
        return {'status': 'posted', 'event_id': posted}
