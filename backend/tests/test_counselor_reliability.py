"""Private diagnostics count fallbacks and detect delayed analysis offline."""
from datetime import datetime, timedelta, timezone
from app.models import BackgroundJob
from app.pai_c.reliability import health, record_fallback
from scripts.counselor_eval_support import StudentSession


def test_daily_counts_are_idempotent_scoped_and_detect_lag():
    with StudentSession() as student, student.factory() as db:
        now=datetime.now(timezone.utc)
        event={'id':'test-event','timestamp':int(now.timestamp()*1000)}
        record_fallback(db,student.workspace_id,event,'provider_fallback')
        record_fallback(db,student.workspace_id,event,'provider_fallback')
        record_fallback(db,student.workspace_id,{'id':'yesterday','timestamp':int((now-timedelta(days=1)).timestamp()*1000)},'old')
        db.add(BackgroundJob(workspace_id=student.workspace_id,job_type='counselor.analyze',status='pending',
            created_at=now-timedelta(minutes=5)))
        db.commit()
        result=health(db,student.workspace_id,now=now)
        assert result['fallbacks']=={'provider_fallback':1}
        assert result['planner_lag_alert'] and result['planner_lag_seconds']==300
        assert health(db,'00000000-0000-0000-0000-000000000000',now=now)['fallbacks']=={}
        assert 'test-event' not in str(result)


def test_parse_fallback_is_countable_but_fences_are_not_a_fallback():
    from app.pai_c.deep.turn import _parse_response
    violations=[]
    _parse_response('{broken', violations=violations)
    assert violations == ['invalid_json_fallback']
    violations=[]
    _parse_response('```json\n{"reply":"A reply","action":{}}\n```', violations=violations)
    assert violations == []


def test_health_counts_unanswered_requests_without_returning_text():
    from app.models import CounselorNotedQuestion, EventRecord
    with StudentSession() as student, student.factory() as db:
        for event_id in ['event', 'event2']:
            db.add(EventRecord(id=event_id,network_id=student.workspace_id,type='workspace.message.posted',source='human:student',target='channel/pai',timestamp=1,payload={'content':'Question'}))
        db.flush()
        db.add(CounselorNotedQuestion(workspace_id=student.workspace_id,source_event_id='event',question_to_research='Private question',status='open'))
        db.add(CounselorNotedQuestion(workspace_id=student.workspace_id,source_event_id='event2',question_to_research='Answered',status='answered_now'))
        db.commit()
        result=health(db,student.workspace_id)
        assert result['open_questions']==1 and result['open_requests']==0
        assert 'Private question' not in str(result)
