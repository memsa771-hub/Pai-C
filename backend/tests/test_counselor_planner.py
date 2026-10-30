"""Offline bounded views, atomic patches, plans and durable Planner jobs."""
import json
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select
from app.config import config
from app.models import PaiTurnPlan, CounselorTurnDecision, CounselorNotebookHistory, EventRecord
from app.pai_c.memory import MemoryService
from app.pai_c.deep.notebook_schema import CounselorNotebookData
from app.pai_c.deep.analysis import analyze_job, _input
from app.pai_c.deep.context import build_context, estimated_tokens
from app.pai_c.deep.turn_input import CounselorTurnInput
from app.pai_c.planner.view import build_planner_view, PARTS
from app.pai_c.understanding.data import at_path, set_path
from app.pai_c.planner.patch import apply_patch, PatchRejected
from app.pai_c.planner.plan import validate_plan
from scripts.counselor_eval_support import StudentSession
from scripts.eval.recorded_planner import PLAN
from tests.test_counselor_deep_pr4 import _turn_job
from tests.truth_map_fixtures import item, STAMP

NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


def notebook():
    return CounselorNotebookData.model_validate({
        "said": [item(id="a")], "shown": [item(id="b")],
        "source": [item(id="c", category="self")], "self": [item(id="d")],
        "pressures": {"items": [item(id="e")]},
        "sure": {"score": 3, "reason": "Earlier rating", "asked_at": STAMP},
    })


def new_item(**changes):
    return {"key": "wish", "value": "Student wish", "kind": "said", "confidence": "medium",
            "evidence": "Student stated a wish", **changes}


@pytest.mark.parametrize("op", [
    {"op":"add","part":"said","item":new_item()},
    {"op":"update","id":"a","fields":{"value":"Changed","evidence":"New statement"}},
    {"op":"confirm","id":"a","evidence":"Confirmed statement"},
    {"op":"retire","id":"a","reason":"Student corrected it"},
    {"op":"upsert_person","role":"Guardian","wish":"Security","worry":"Stability","evidence":"Student explanation"},
    {"op":"set_sure","score":7,"reason":"Explored","would_raise":"Try it","evidence":"I rate it 7"},
    {"op":"set_private","field":"private_notes","value":"Tentative interpretation"},
    {"op":"set_coverage","part":"said","value":True},
])
def test_each_patch_operation_is_atomic_and_keeps_unmentioned_items(op):
    before=notebook()
    after=apply_patch(before,[op],build_planner_view(before).ids,"I rate it 7",now=NOW)
    assert after.shown == before.shown and after.source == before.source and after.self == before.self
    assert before.said[0].value == "A student statement"
    if op["op"] == "add":
        added=after.said[-1]; UUID(added.id)
        assert added.first_seen == NOW and added.last_confirmed == NOW
    if op["op"] in {"update","confirm"}:
        assert after.said[0].last_confirmed == NOW and after.said[0].first_seen == before.said[0].first_seen
    if op["op"] == "retire":
        assert after.said[0].status == "retired" and len(after.said)==1
    if op["op"] == "set_sure":
        assert after.sure.score == 7 and after.sure.history[0].score == 3 and after.sure.asked_at == NOW


@pytest.mark.parametrize("op", [
    {"op":"add","part":"said","item":new_item(id="model-id")},
    {"op":"add","part":"said","item":new_item(first_seen=STAMP)},
    {"op":"update","id":"a","fields":{"value":"No evidence"}},
    {"op":"confirm","id":"unknown","evidence":"Evidence"},
    {"op":"set_private","field":"chapter","value":"coach"},
    {"op":"unknown"},
])
def test_invalid_operation_rejects_entire_patch(op):
    before=notebook(); saved=before.model_dump(mode="json")
    with pytest.raises(PatchRejected) as error:
        apply_patch(before,[{"op":"add","part":"said","item":new_item()},op],build_planner_view(before).ids,"",now=NOW)
    assert error.value.index == 1
    assert before.model_dump(mode="json") == saved


@pytest.mark.parametrize("text", ["I feel sure", "I previously rated it 17", "My rating is 7.5", "My rating is -7"])
def test_set_sure_requires_score_in_latest_student_text(text):
    before=notebook()
    with pytest.raises(PatchRejected):
        apply_patch(before,[{"op":"set_sure","score":7,"reason":"Reason","would_raise":"Practice","evidence":"Evidence"}],build_planner_view(before).ids,text)


@pytest.mark.parametrize("part", ["said","shown","source","self","pressures","sure"])
def test_coverage_true_requires_active_evidence(part):
    before=CounselorNotebookData()
    with pytest.raises(PatchRejected):
        apply_patch(before,[{"op":"set_coverage","part":part,"value":True}],frozenset(),"")


def test_person_upsert_matches_role_case_insensitively_and_preserves_first_seen():
    before=notebook(); op={"op":"upsert_person","role":"Guardian","wish":"Security","worry":"Stability","evidence":"Evidence"}
    first=apply_patch(before,[op],build_planner_view(before).ids,"",now=NOW)
    second=apply_patch(first,[{**op,"role":"guardian","worry":"Distance"}],build_planner_view(first).ids,"",now=NOW+timedelta(days=1))
    assert len(second.world.people)==1
    assert second.world.people[0].first_seen == NOW
    assert second.world.people[0].last_confirmed == NOW+timedelta(days=1)
    assert second.world.people[0].worry == "Distance"


def large_map():
    data={"pressures":{"items":[]}}
    for part in PARTS:
        rows=[item("x"*200,id=part+str(i),evidence="e"*300,
             last_confirmed=(NOW+timedelta(days=i)).isoformat()) for i in range(10)]
        if part=="source":
            for row in rows:row["category"]="self"
        set_path(data, part, rows)
    return CounselorNotebookData.model_validate(data)


def test_view_is_within_budget_keeps_newest_and_each_nonempty_part():
    before=large_map(); view=build_planner_view(before,budget=4000)
    assert view.tokens == estimated_tokens(view.text) <= 4000
    assert "<omitted_items>" in view.text
    for part in PARTS:
        assert part+"9" in view.ids and part+"0" not in view.ids
        assert view.omitted[part] > 0
        rows=at_path(view.data,part)
        assert rows and len(rows)+view.omitted[part]==10
        assert all(len(row["evidence"]) == 200 for row in rows)


def test_retired_and_archive_excluded_private_notes_cut_and_mandatory_included():
    before=notebook().model_copy(update={"private_notes":"p"*1500,"legacy_v1":{"secret_archive":"never sent"}})
    before.said[0].status="retired"
    view=build_planner_view(before)
    assert "a" not in view.ids and "never sent" not in view.text
    assert len(view.data["private_notes"]) == 1000
    assert all(key in view.data for key in ("sure","tensions","identity_status","decision_difficulties","hypotheses","open_questions","coverage","depth_mode","engagement_style"))
    assert "people" in view.data["world"]


@pytest.mark.parametrize("op", ["update","confirm","retire"])
def test_omitted_id_rejects_whole_patch(op):
    before=large_map(); view=build_planner_view(before,budget=4000)
    operation={"op":op,"id":"said0"}
    operation.update({"fields":{"evidence":"New"}} if op=="update" else {"evidence":"New"} if op=="confirm" else {"reason":"Changed"})
    with pytest.raises(PatchRejected):
        apply_patch(before,[{"op":"confirm","id":"said9","evidence":"Visible"},operation],view.ids,"")
    assert before.said[-1].evidence == "e"*300


def test_patch_applies_to_full_map_preserving_omitted_items_exactly():
    before=large_map(); view=build_planner_view(before,budget=4000)
    after=apply_patch(before,[{"op":"confirm","id":"said9","evidence":"Reconfirmed"}],view.ids,"",now=NOW)
    assert len(after.said)==10
    for part in PARTS:
        old=at_path(before.model_dump(mode="json"),part)
        new=at_path(after.model_dump(mode="json"),part)
        assert [row for row in new if row["id"] not in view.ids] == [row for row in old if row["id"] not in view.ids]


def test_mandatory_content_over_budget_proceeds_and_logs_only_size(caplog):
    view = build_planner_view(notebook(), budget=1)
    assert view.tokens > 1 and view.ids == frozenset("abcde")
    assert "planner_input_over_budget tokens=" in caplog.text
    assert "A student statement" not in caplog.text


@pytest.mark.parametrize("change", [{"next_move":"invalid"},{"intent":"x"*201},{"give":"x"*201},
    {"avoid_questions":["q"]*6},{"playbooks":["not-installed"]},{"extra":True},{"target_gap":"other"}])
def test_plan_is_strict_and_playbooks_empty(change):
    with pytest.raises(ValueError):validate_plan({**PLAN,**change})


@pytest.mark.asyncio
async def test_patch_retry_is_whole_and_second_rejection_preserves_map_plan_logs(caplog):
    with StudentSession() as student, student.factory() as db:
        job,event_id=_turn_job(student,db)
        before=MemoryService(db).truth_map(student.workspace_id)
        bad={"patch":[{"op":"add","part":"said","item":new_item(value="private student text")},{"op":"confirm","id":"not-visible","evidence":"private student text"}],"plan":PLAN}
        model=AsyncMock(return_value=json.dumps(bad))
        with patch("app.pai_c.deep.analysis.chat_completion",model):
            assert (await analyze_job(job,db))["status"]=="patch_rejected"
        assert MemoryService(db).truth_map(student.workspace_id) == before
        assert not db.scalars(select(PaiTurnPlan)).all()
        assert "op_index=1" in caplog.text and "private student text" not in caplog.text
        assert "op_index=1" in model.await_args_list[1].kwargs["system_prompt"]


@pytest.mark.asyncio
async def test_corrected_patch_retry_saves_only_corrected_result():
    with StudentSession() as student, student.factory() as db:
        job,_=_turn_job(student,db)
        responses=[{"patch":[{"op":"add","part":"said","item":new_item(value="Discarded")},{"op":"unknown"}],"plan":PLAN},
                   {"patch":[{"op":"add","part":"said","item":new_item(value="Corrected")}],"plan":PLAN}]
        model=AsyncMock(side_effect=[json.dumps(row) for row in responses])
        with patch("app.pai_c.deep.analysis.chat_completion",model):result=await analyze_job(job,db)
        assert result["model_calls"]==2 and result["version"]==1
        assert [row.value for row in MemoryService(db).truth_map(student.workspace_id).notebook.said] == ["Corrected"]


@pytest.mark.asyncio
async def test_plan_saved_with_map_version_context_and_wellbeing_forces_care():
    with StudentSession() as student, student.factory() as db:
        job,event_id=_turn_job(student,db)
        db.add(CounselorTurnDecision(workspace_id=student.workspace_id,source_event_id=event_id,source_timestamp=job.payload["source_timestamp"],move="wellbeing",guard_violations=[]));db.commit()
        output={"patch":[{"op":"add","part":"said","item":new_item()}],"plan":{**PLAN,"give":"Some reflection","avoid_questions":["Already answered?"]}}
        with patch("app.pai_c.deep.analysis.chat_completion",AsyncMock(return_value=json.dumps(output))):result=await analyze_job(job,db)
        row=db.scalar(select(PaiTurnPlan)); assert row.notebook_version==result["version"]==1
        assert row.plan["next_move"]=="care" and row.plan["target_gap"] is None
        service=MemoryService(db)
        assert service.latest_plan(student.workspace_id).next_move == "care"
        assert service.latest_plan(str(uuid4())) is None
        turn=CounselorTurnInput("chat",student.workspace_id,"Next",(),None,event_id,None,f"human:{student.user_id}")
        from app.pai_c.policy.controller import Decision
        context=await build_context(db,student.workspace_id,turn,
            decision=Decision("counsel","counsel",None,False,False,False))
        assert "<plan>" not in context.text and "<decision>" in context.text
        assert "Some reflection" in context.text and "Already answered?" in context.text
        assert '"playbooks"' not in context.text
        service.delete_for_workspace(student.workspace_id);db.commit()
        assert not db.scalars(select(PaiTurnPlan)).all()


@pytest.mark.asyncio
async def test_invalid_plan_keeps_previous_valid_plan_while_patch_saves():
    with StudentSession() as student, student.factory() as db:
        job,event_id=_turn_job(student,db)
        output={"patch":[{"op":"add","part":"said","item":new_item()}],"plan":PLAN}
        with patch("app.pai_c.deep.analysis.chat_completion",AsyncMock(return_value=json.dumps(output))):await analyze_job(job,db)
        job.status="succeeded";db.commit()
        later,_=_turn_job(student,db)
        with patch("app.pai_c.deep.analysis.chat_completion",AsyncMock(return_value=json.dumps({"patch":[],"plan":{**PLAN,"playbooks":["invalid"]}}))):result=await analyze_job(later,db)
        assert result["version"]==2 and len(db.scalars(select(PaiTurnPlan)).all())==1
        assert MemoryService(db).latest_plan(student.workspace_id).intent == PLAN["intent"]


@pytest.mark.asyncio
async def test_oversize_mandatory_map_still_makes_one_planner_call():
    from app.models import CounselorNotebook
    with StudentSession() as student, student.factory() as db:
        job,event_id=_turn_job(student,db)
        original = CounselorNotebookData(private_notes="private interpretation " * 1000)
        db.add(CounselorNotebook(workspace_id=student.workspace_id,version=1,
            notebook=original.storage_data(),last_event_id=event_id,updated_at=NOW))
        db.commit()
        model=AsyncMock(return_value=json.dumps({"patch":[], "plan":PLAN}))
        with patch.object(config,"PAI_PLANNER_MAP_CONTEXT_TOKENS",1),patch("app.pai_c.deep.analysis.chat_completion",model):
            result=await analyze_job(job,db)
        assert result["status"] == "applied" and result["model_calls"] == model.await_count == 1
        assert MemoryService(db).truth_map(student.workspace_id).notebook.private_notes == original.private_notes


def test_planner_history_and_input_size_are_flat_at_100_turns():
    with StudentSession() as student, student.factory() as db:
        sizes=[]
        for index in range(100):
            job,_=_turn_job(student,db,"x"*1500)
            if index in (11,99):
                current=db.get(EventRecord,job.payload["user_event_id"]);reply=db.get(EventRecord,job.payload["assistant_event_id"])
                text=_input(db,student.workspace_id,current,reply,CounselorNotebookData())
                transcript=json.loads(text.split("<transcript>")[1].split("</transcript>")[0])
                assert len(transcript)==config.PAI_PLANNER_HISTORY_TURNS==12
                sizes.append(estimated_tokens(text))
        assert sizes[0]==sizes[1]


@pytest.mark.asyncio
async def test_version_conflict_rolls_back_plan_and_retries_with_new_version():
    from app.pai_c.deep.notebook import NotebookVersionConflict, NotebookService
    with StudentSession() as student, student.factory() as db:
        job,_=_turn_job(student,db)
        real=NotebookService.apply; calls=0
        def conflict(service,*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==1:raise NotebookVersionConflict("race")
            return real(service,*args,**kwargs)
        model=AsyncMock(return_value=json.dumps({"patch":[],"plan":PLAN}))
        with patch.object(NotebookService,"apply",conflict),patch("app.pai_c.deep.analysis.chat_completion",model):
            result=await analyze_job(job,db)
        assert result["model_calls"]==2
        rows=db.scalars(select(PaiTurnPlan)).all()
        assert len(rows)==1 and rows[0].notebook_version==1


@pytest.mark.asyncio
async def test_v2_notebook_archive_and_unmentioned_items_survive_job():
    from app.models import CounselorNotebook
    with StudentSession() as student, student.factory() as db:
        job,event_id=_turn_job(student,db)
        original=notebook().model_copy(update={"legacy_v1":{"original":"private archive"}})
        db.add(CounselorNotebook(workspace_id=student.workspace_id,version=1,notebook=original.storage_data(),last_event_id=event_id,updated_at=NOW));db.commit()
        model=AsyncMock(return_value=json.dumps({"patch":[{"op":"confirm","id":"a","evidence":"Reconfirmed"}],"plan":PLAN}))
        with patch("app.pai_c.deep.analysis.chat_completion",model):result=await analyze_job(job,db)
        saved=MemoryService(db).truth_map(student.workspace_id).notebook
        assert result["version"]==2 and saved.shown==original.shown
        assert saved.legacy_v1==original.legacy_v1
        assert "private archive" not in model.await_args.kwargs["messages"][0]["content"]


def test_migration_105_creates_plan_table_and_downgrade_preserves_other_tables():
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.operations import Operations
    from alembic.migration import MigrationContext
    path=Path(__file__).parents[1]/"alembic/versions/105_counselor_turn_plans.py"
    spec=importlib.util.spec_from_file_location("turn_plan_migration",path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    assert migration.revision=="105" and migration.down_revision=="104"
    with StudentSession() as student, student.factory() as db:
        job,event_id=_turn_job(student,db)
        db.execute(sa.text("DROP TABLE pai_turn_plans"));db.commit()
        with patch.object(migration,"op",Operations(MigrationContext.configure(db.connection()))):
            migration.upgrade()
            assert {column["name"] for column in sa.inspect(db.connection()).get_columns("pai_turn_plans")} == {"id","workspace_id","source_event_id","notebook_version","plan","created_at"}
            db.add(PaiTurnPlan(workspace_id=student.workspace_id,source_event_id=event_id,notebook_version=1,plan=PLAN));db.flush()
            constraints=sa.inspect(db.connection()).get_unique_constraints("pai_turn_plans")
            assert any(row["column_names"]==["workspace_id","source_event_id"] for row in constraints)
            migration.downgrade()
        db.commit()
        assert "pai_turn_plans" not in sa.inspect(db.connection()).get_table_names()
        assert db.get(EventRecord,event_id) is not None


def test_view_orders_accepted_naive_and_offset_dates_without_changing_storage():
    before=large_map()
    before.said[0].last_confirmed=NOW.replace(tzinfo=None)
    original=before.said[0].model_dump(mode="json")
    view=build_planner_view(before,budget=4000)
    assert "said0" not in view.ids and "said9" in view.ids
    assert before.said[0].model_dump(mode="json")==original

@pytest.mark.parametrize('field,cap,entry', [
    ('hypotheses', 8, {'text':'Possible pattern','status':'open','evidence_for':'Evidence'}),
    ('tensions', 6, {'between':['a','b'],'evidence':'Evidence','status':'open'}),
    ('decision_difficulties', 6, {'category':'information','evidence':'Evidence','status':'open'}),
    ('open_questions', 3, {'priority':1,'area':'source','question_intent':'Explore source'}),
])
def test_private_write_caps_reject_whole_patch(field, cap, entry):
    before=notebook()
    operations=[{'op':'confirm','id':'a','evidence':'Changed'},
                {'op':'set_private','field':field,'value':[entry]*(cap+1)}]
    with pytest.raises(PatchRejected):
        apply_patch(before,operations,build_planner_view(before).ids,'')
    assert before.said[0].evidence == 'Student described this'
    accepted=apply_patch(before,[operations[-1] | {'value':[entry]*cap}],build_planner_view(before).ids,'')
    assert len(getattr(accepted,field)) == cap


def test_private_trimming_order_and_newest_entries_preserves_stored_map():
    before=notebook().model_copy(update={'private_notes':'p'*2000})
    data=before.model_dump(mode='json')
    data['hypotheses']=[{'text':str(i),'status':'rejected' if i==0 else 'open','evidence_for':'e'*500} for i in range(12)]
    data['tensions']=[{'between':[str(i)],'status':'open','evidence':'e'*500} for i in range(9)]
    data['decision_difficulties']=[{'category':'information','status':'open','evidence':str(i)+'e'*500} for i in range(9)]
    data['open_questions']=[{'priority':i+1,'area':'source','question_intent':str(i)+'x'*500} for i in range(5)]
    before=CounselorNotebookData.model_validate(data)
    stored=before.model_dump(mode='json')
    view=build_planner_view(before,budget=1)
    assert [row['text'] for row in view.data['hypotheses']]==[str(i) for i in range(4,12)]
    assert [row['between'][0] for row in view.data['tensions']]==[str(i) for i in range(3,9)]
    assert len(view.data['decision_difficulties'])==6
    assert [row['priority'] for row in view.data['open_questions']]==[1,2,3]
    assert len(view.data['private_notes'])==500
    assert before.model_dump(mode='json') == stored
    # A budget that fits after removing rejected hypotheses stops at that step.
    intermediate=deepcopy(data)
    intermediate['hypotheses']=intermediate['hypotheses'][1:]
    intermediate['private_notes']=intermediate['private_notes'][:1000]
    limit=build_planner_view(CounselorNotebookData.model_validate(intermediate),budget=100000).tokens
    early=build_planner_view(before,budget=limit)
    assert len(early.data['hypotheses'])==11 and len(early.data['tensions'])==9
    assert len(early.data['private_notes'])==1000
    intermediate['hypotheses']=intermediate['hypotheses'][-8:]
    limit=build_planner_view(CounselorNotebookData.model_validate(intermediate),budget=100000).tokens
    early=build_planner_view(before,budget=limit)
    assert len(early.data['hypotheses'])==8 and len(early.data['tensions'])==9


def test_plan_age_counts_only_later_student_messages_in_workspace():
    with StudentSession() as student, student.factory() as db:
        job,event_id=_turn_job(student,db)
        db.add(PaiTurnPlan(workspace_id=student.workspace_id,source_event_id=event_id,notebook_version=1,plan=PLAN))
        db.commit()
        for index in range(config.PAI_PLAN_MAX_AGE_TURNS):
            _turn_job(student,db)
        assert MemoryService(db).latest_plan(student.workspace_id) is not None
        _turn_job(student,db)
        assert MemoryService(db).latest_plan(student.workspace_id) is None


def test_rejection_carries_a_schema_only_reason_for_the_planner():
    """The correction feedback names why the op failed (this module's fixed
    message, or a pydantic field path and error type), never the student's words."""
    before=notebook()
    with pytest.raises(PatchRejected) as error:
        apply_patch(before,[{"op":"confirm","id":"not-visible","evidence":"private student text"}],build_planner_view(before).ids,"")
    assert error.value.reason == "id not present in Planner view" and "reason=id not present" in str(error.value)
    with pytest.raises(PatchRejected) as error:
        apply_patch(before,[{"op":"add","part":"said","item":{**new_item(value="private student text"),"kind":"private student text"}}],build_planner_view(before).ids,"")
    assert error.value.error_type == "ValidationError" and "kind" in error.value.reason
    assert "private student text" not in str(error.value)


def test_category_outside_source_is_dropped_not_rejected():
    before=notebook()
    after=apply_patch(before,[{"op":"add","part":"said","item":new_item(category="self")}],build_planner_view(before).ids,"",now=NOW)
    assert after.said[-1].model_dump().get("category") is None and len(after.said)==len(before.said)+1
