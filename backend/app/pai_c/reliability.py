"""Workspace-scoped operational counts without student text or provider calls."""
from collections import Counter
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from sqlalchemy import select, func
from app.models import BackgroundJob, CounselorTurnDecision, StudentRequest, CounselorNotedQuestion, Workspace

JOB_HEALTH_ALERT = 'counselor.health_alert'


def policy():
    return json.loads(Path(__file__).with_name('reliability.json').read_text(encoding='utf-8'))


def record_fallback(db, workspace_id, event, reason):
    if not event.get('id'):
        return
    row = db.scalar(select(CounselorTurnDecision).where(CounselorTurnDecision.workspace_id == workspace_id,
        CounselorTurnDecision.source_event_id == event['id']))
    if row is None:
        row = CounselorTurnDecision(workspace_id=workspace_id, source_event_id=event['id'],
            source_timestamp=event.get('timestamp') or int(datetime.now(timezone.utc).timestamp()*1000),
            move='none', guard_violations=[])
        db.add(row)
    row.guard_violations = sorted(set([*(row.guard_violations or []), reason]))
    db.commit()


def health(db, workspace_id, *, now=None):
    now = now or datetime.now(timezone.utc)
    midnight = now.replace(hour=0,minute=0,second=0,microsecond=0)
    counts = Counter()
    for violations in db.scalars(select(CounselorTurnDecision.guard_violations).where(
        CounselorTurnDecision.workspace_id == workspace_id,
        CounselorTurnDecision.source_timestamp >= int(midnight.timestamp()*1000),
        CounselorTurnDecision.source_timestamp < int((midnight + timedelta(days=1)).timestamp()*1000))):
        counts.update(set(violations or []))
    jobs = db.scalars(select(BackgroundJob).where(BackgroundJob.workspace_id == workspace_id,
        BackgroundJob.job_type == 'counselor.analyze', BackgroundJob.status.in_(['pending','running']))).all()
    def age(job):
        stamp=job.created_at
        if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=timezone.utc)
        return max(0,int((now-stamp).total_seconds()))
    lag=max((age(job) for job in jobs),default=0)
    failed=db.scalar(select(func.count()).select_from(BackgroundJob).where(
        BackgroundJob.workspace_id == workspace_id, BackgroundJob.status == 'failed',
        BackgroundJob.updated_at >= midnight, BackgroundJob.updated_at < midnight + timedelta(days=1))) or 0
    requests = db.scalar(select(func.count()).select_from(StudentRequest).where(
        StudentRequest.workspace_id == workspace_id, StudentRequest.status == 'open')) or 0
    questions = db.scalar(select(func.count()).select_from(CounselorNotedQuestion).where(
        CounselorNotedQuestion.workspace_id == workspace_id, CounselorNotedQuestion.status.in_(['open','unanswered']))) or 0
    return {'open_requests': requests, 'open_questions': questions, 'database':'ok','planner_pending':len(jobs),'planner_lag_seconds':lag,
        'planner_lag_alert':lag > policy()['planner_lag_seconds'], 'failed_jobs':failed,
        'day':midnight.date().isoformat(),'fallbacks':dict(counts)}


def enqueue_alerts(db):
    """Called by the existing session sweep; at most one durable alert each day."""
    from app.runtime.task_runtime import enqueue
    total = 0
    for workspace_id in db.scalars(select(Workspace.id).where(Workspace.status == 'active', Workspace.owner_user_id.is_not(None))):
        snapshot = health(db, str(workspace_id))
        snapshot['fallback_total'] = sum(snapshot['fallbacks'].values())
        if not any(snapshot.get(key, 0) >= threshold for key, threshold in policy()['alert_thresholds'].items()):
            continue
        enqueue(db, job_type=JOB_HEALTH_ALERT, workspace_id=str(workspace_id),
            payload={'summary': snapshot}, idempotency_key=f"counselor-health:{workspace_id}:{snapshot['day']}")
        total += 1
    return total


async def alert_job(job, db):
    from app.pai_c.deep.analysis import _workspace_lock
    from app.services.notify import notify_once
    async with _workspace_lock(db, job.workspace_id):
        workspace = db.get(Workspace, job.workspace_id)
        if not workspace or workspace.status != 'active' or not workspace.owner_user_id:
            return {'status': 'inactive'}
        summary = job.payload['summary']
        # Only numeric health counts appear in the workspace owner's existing inbox.
        fields = {key: max(0, int(summary.get(key, 0))) for key in
            ('fallback_total', 'planner_lag_seconds', 'failed_jobs', 'open_requests', 'open_questions')}
        rules = policy()
        notice = notify_once(db, job.workspace_id, dedupe_key=job.idempotency_key,
            source='openagents:pai', title=rules['alert_title'], message=rules['alert_message'].format(**fields),
            priority=rules['alert_priority'], link_url=f'/{job.workspace_id}?view=threads')
        return {'status': 'notified', 'notification_id': notice.id}
