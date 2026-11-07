"""The OS HTTP API (spec §4.9; Slice 2 spec §4.8; Slice 3 spec §4): PlanSource (admin), PlanQuery, the student
inbox, the student's programme facts, research (admin), and the student's documents and profile."""

import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Response, UploadFile
from fastapi.responses import JSONResponse

from datetime import date, timedelta

from app.os import clock, my_plan as my_plan_view
from app.os.ports import my_plan as my_plan_gate
from app.os.costs import cost_report
from app.os.api.deps import check_admin, current_student_ref, current_student_ref_for_write
from app.os.api.queries import (
    document_out,
    documents_out,
    eligibility_notes,
    finding_out,
    inbox_items,
    mark_note_read,
    notice_link,
    open_facts,
    plan_out,
    research_runs,
    student_programmes,
    waiting_items,
)
from app.os.api.schemas import (
    CompleteIn,
    CostReportOut,
    EmailStatusOut,
    ConsentIn,
    ConsentOut,
    CompleteOut,
    ConfirmDocumentIn,
    VaultCheckOut,
    ConfirmIn,
    ConfirmOut,
    DocumentOut,
    DocumentsOut,
    FindingOut,
    InboxOut,
    MyPlanOut,
    OpenFactsOut,
    PlanOut,
    ProfileOut,
    ProgrammesOut,
    ResearchRunsOut,
    ResolveIn,
    EligibilityOut,
    RequestIn,
    RequestOut,
    RequestAnswerIn,
    RequestAnswerOut,
    RequestsOut,
    RouteProgrammesOut,
    RoutesOut,
    SelfPlanOut,
    SelfStartIn,
    SwapIn,
    ResearchStartOut,
    SupplyIn,
    UpgradeOut,
    AnswerIn,
    AnswerOut,
    ApproveIn,
    ApproveOut,
    DraftIn,
    InterviewOut,
    PastedRulesIn,
    StatementOut,
    StatementsOut,
    TextIn,
)
from app.os.api.queries import statement_out
from app.os.artifacts.store import STATEMENT_KINDS, ArtifactStore
from app.os.statements import interview as stmt
from app.os.statements.approval import complete_documents_tasks
from app.os.statements.facts_check import unsupported
from app.os.statements.rules import resolve_rules
from app.os.statements.run import inputs_for, sources
from dataclasses import asdict
from app.os.knowledge.programmes import ProgrammeStore
from app.os.knowledge.research.run import enqueue_one
from app.os.api.services import Services
from app.os.consent import ConsentStore, current_terms, gate
from app.os.compiler import CompileError
from app.os.service import NothingNewer
from app.os.contracts.route_contract import RouteContract
from app.os.documents.confirm import NotConfirmable, confirm_document, delete_document, resolve_finding
from app.os.documents import connect_texts
from app.os.documents.vault_check import compare as vault_compare
from app.os.documents.intake import MAX_BYTES, UploadError, check_upload
from app.os.documents.run import enqueue_document
from app.os.documents.store import DocumentStore, DuplicateDocument, FindingStore, ProfileStore
from app.os.eligibility.notes import on_profile_change
from app.os.api import self_serve
from app.os import inbox_actions
from app.os.inbox_actions import StepActionError
from app.os.api.packs import add_pack_routes, add_visa_routes, complete_ready_packs
from app.os.api.consistency import add_consistency_routes
from app.os.api.replan import add_replan_routes, changes_paused, student_proposals
from app.os.knowledge.requests import RequestLimit, request_programme
from app.os.ports import choice_requests, document_files, fact_proposals, student_facts
from app.os.replan import choice_texts
from app.os.routes import builder
from app.os.kernel import IllegalTransition
from app.os.kernel.revisions import NOTICE_PREFIX
from app.os.playbooks import PlaybookError
from app.os.requests import answers as request_answers, gate as needs_gate, store as request_store, texts as request_texts
from app.os.requests.refresh import refresh
from app.os.workers import confirm_fact, open_confirm_tasks, supply_fact

log = logging.getLogger(__name__)


def _notify(plans, student: str) -> None:
    """Eligibility notes after a confirm or resolve. A note is extra: it never turns a saved confirm into an error."""
    try:
        on_profile_change(plans, student)
    except Exception:
        log.exception("eligibility notes failed for a student")


def refusal(code: str, message: str) -> HTTPException:
    """A 409 the screens tell apart by `code` (Slice 9a: consent_needed, consent_version, terms_not_set)."""
    return HTTPException(status_code=409, detail={"code": code, "message": message})


_accepts = gate.accepts  # placeholder terms count only in rehearsal mode (Slice 9a spec §3.2)


def build_router(get_services: Callable[[], Services]) -> APIRouter:
    router = APIRouter(tags=["os"])

    def services() -> Services:
        return get_services()

    def require_admin(x_os_admin_token: str | None = Header(None), svc: Services = Depends(services)) -> None:
        check_admin(svc.settings, x_os_admin_token)

    # --- Slice 9a: pilot consent (spec §3.2). Starting a plan and uploading need consent to the current terms. ---

    def consented_student(student: str = Depends(current_student_ref_for_write),
                          svc: Services = Depends(services)) -> str:
        """A dependency, so it runs before the body is validated and before any write or enqueue. Only a new start
        and an upload are refused: the inbox and changes to a running plan keep working (Review Focus 3)."""
        code = gate.upload_refusal(svc, student)
        if code is not None:
            raise refusal(code, gate.MESSAGES[code])
        return student

    @router.get("/consent", response_model=ConsentOut)
    def consent(student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        terms = current_terms(svc.terms_dir)
        return {"version": terms.version, "text": terms.text, "placeholder": terms.placeholder,
                "agreed": _accepts(svc, terms)
                and ConsentStore(svc.engine, svc.settings.tenant_id).has(student, terms.version)}

    @router.post("/consent", status_code=204)
    def agree(body: ConsentIn, student: str = Depends(current_student_ref_for_write),
              svc: Services = Depends(services)) -> Response:
        terms = current_terms(svc.terms_dir)
        if body.version != terms.version:
            raise refusal("consent_version", f"these are not the current terms (version {terms.version})")
        if not _accepts(svc, terms):  # no real student starts before the owners' text
            raise refusal("terms_not_set", "the pilot terms are not written yet")
        ConsentStore(svc.engine, svc.settings.tenant_id).agree(student, terms.version)
        return Response(status_code=204)

    @router.post("/plans", status_code=201, response_model=PlanOut, dependencies=[Depends(require_admin)])
    def post_plan(contract: RouteContract, response: Response, svc: Services = Depends(services)) -> dict:
        try:
            ref = svc.plans.start_plan(contract)
        except (PlaybookError, CompileError) as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        if not ref.created:
            response.status_code = 200
        return plan_out(svc.engine, svc.settings.tenant_id, ref.plan_id)

    @router.get("/plans/{plan_id}", response_model=PlanOut, dependencies=[Depends(require_admin)])
    def get_plan(plan_id: int, svc: Services = Depends(services)) -> dict:
        found = plan_out(svc.engine, svc.settings.tenant_id, plan_id)
        if found is None:
            raise HTTPException(status_code=404, detail="plan not found")
        return found

    @router.post("/plans/{plan_id}/upgrade", response_model=UpgradeOut, dependencies=[Depends(require_admin)])
    def upgrade(plan_id: int, svc: Services = Depends(services)) -> dict:
        try:
            return {"revision": svc.plans.upgrade(plan_id)}
        except KeyError:
            raise HTTPException(status_code=404, detail="plan not found") from None
        except NothingNewer as e:
            raise HTTPException(status_code=409, detail=str(e)) from None

    def drop_empty_notices(svc: Services, student: str, items: list[dict]) -> list[dict]:
        """A "Your plan was updated" item whose revision changed none of the student's steps has nothing to tell
        them: it is done (Slice 9 Task 11, `walk:S1:plan_updated_notice_empty`). Extra work on a read: a failure
        leaves the item listed; one another request moved on meanwhile (IllegalTransition, e.g. two loads at once) is
        left out, quietly."""
        kept = []
        for item in items:
            if item["instance_key"].startswith(NOTICE_PREFIX) and not item["changes"]:
                try:  # the result keeps the notice's link to its revision and cause
                    svc.kernel.complete_student_task(item["id"], student, {
                        "closed": "no_student_changes", **notice_link(svc.engine, item["id"])})
                    continue
                except IllegalTransition:  # another request moved it on meanwhile: no longer the student's to see
                    continue
                except Exception:
                    log.exception("closing an empty plan update notice failed")
            kept.append(item)
        return kept

    @router.get("/inbox", response_model=InboxOut)
    def inbox(student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        complete_ready(svc, student)  # Slice 5: a documents task whose statements are already approved
        complete_ready_packs(svc, student)  # Slice 6a/6b: a review task whose pack or visa file is approved
        tenant = svc.settings.tenant_id
        items = drop_empty_notices(svc, student, inbox_items(svc.engine, tenant, student))
        return {"items": items + waiting_items(svc.engine, tenant, student, svc.plans.playbooks),
                "notes": eligibility_notes(svc.engine, tenant, student),
                "proposals": student_proposals(svc, student), "changes_paused": changes_paused(svc, student)}

    @router.post("/inbox/notes/{note_id}/read", status_code=204)
    def read_note(note_id: int, student: str = Depends(current_student_ref_for_write),
                  svc: Services = Depends(services)) -> Response:
        if not mark_note_read(svc.engine, svc.settings.tenant_id, student, note_id):
            raise HTTPException(status_code=404, detail="note not found")
        return Response(status_code=204)

    @router.post("/inbox/{task_id}/complete", response_model=CompleteOut)
    def complete(task_id: int, body: CompleteIn | None = None,
                 student: str = Depends(current_student_ref_for_write),  # a write: needs write access (I6)
                 svc: Services = Depends(services)) -> dict:
        try:
            done = inbox_actions.complete(svc, student, task_id, (body or CompleteIn()).payload) == "done"
        except StepActionError as e:
            raise HTTPException(status_code=404 if e.code in ("not_found", "not_yours") else 409,
                                detail=e.message) from None
        return {"completed": done}

    # --- P1-T8: the student's requests (R-19, D-w19). Only while the needs gate is on (D-w1). ---

    @router.get("/requests", response_model=RequestsOut)
    def requests(student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        """The student's open requests, and those answered in the last 7 days. The step's title and date, the way it
        closes in words; never a value. 404 while the gate is off, as if the route did not exist."""
        tenant = svc.settings.tenant_id
        if needs_gate.on(student, engine=svc.engine, tenant_id=tenant) is None:
            raise HTTPException(status_code=404, detail="Not Found")
        found = request_store.open_for(svc.engine, tenant, student, answered_since=clock.now() - timedelta(days=7))
        asked = request_answers.choices_for(svc, student, found)  # P1-T8: both values, read live from where they are held
        out = []
        for r in found:
            c = asked.get(r.id, request_answers.Choices())
            out.append({
                "id": r.id, "task_id": r.task_id, "kind": r.kind,
                "need": {"kind": r.need_kind, "ref": r.need_ref, "evidence": r.evidence}, "status": r.status,
                "due_at": r.due_at, "due_tz": r.due_tz, "title": r.title,
                "how": request_texts.how(r.kind, r.need_kind, r.evidence, impossible=c.impossible),
                "ref": c.ref, "seen": c.seen, "choices": c.choices, "allow_new": c.allow_new,
                "new_label": request_texts.text("new_label") if c.allow_new else None})
        return {"requests": out}

    @router.post("/requests/{request_id}/answer", response_model=RequestAnswerOut)
    def answer_request(request_id: int, body: RequestAnswerIn, student: str = Depends(current_student_ref_for_write),
                       svc: Services = Depends(services)) -> dict:
        """The student's answer to a "which is right" request (D-w13). A Vault conflict is answered through the host's own
        card resolution, a value above its total by a new value, two documents that differ by `resolve_finding`; then the
        plan is recomputed, so the step is done before this returns. 404 for another student's request and while the gate
        is off; 409 `already_answered`, `answer_elsewhere` for a request that asks for information, or `answer_changed` (with
        a note) when the question is not the one the student saw (`ref`); 503 `counsellor_unavailable` when the host failed."""
        tenant = svc.settings.tenant_id
        if needs_gate.on(student, engine=svc.engine, tenant_id=tenant) is None:
            raise HTTPException(status_code=404, detail="Not Found")
        found = request_store.get(svc.engine, tenant, request_id)
        if found is None or found.student_ref != student:
            raise HTTPException(status_code=404, detail="Not Found")
        if found.status != "open":
            raise HTTPException(status_code=409, detail="already_answered")
        if found.kind != "which_is_right":
            raise HTTPException(status_code=409, detail="answer_elsewhere")  # a provide request closes when PAI has the data
        try:
            request_answers.answer(svc, student, found, body.ref, body.seen, body.choice, body.value)
        except request_answers.AnswerError as e:
            if e.note:
                return JSONResponse(status_code=e.status, content={"detail": e.detail, "note": e.note})
            raise HTTPException(status_code=e.status, detail=e.detail) from None
        refresh(svc, student, "request_answered")
        after = request_store.get(svc.engine, tenant, request_id)
        return {"status": "answered" if after is not None and after.status == "answered" else "still_open"}

    @router.post("/facts/{fact_id}/confirm", response_model=ConfirmOut, dependencies=[Depends(require_admin)])
    def confirm(fact_id: int, body: ConfirmIn, svc: Services = Depends(services)) -> dict:
        try:
            revised = confirm_fact(svc.plans, svc.knowledge, svc.kernel, fact_id, **body.model_dump())
        except KeyError:
            raise HTTPException(status_code=404, detail="fact not found") from None
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        return {"revised_plans": revised}

    @router.post("/facts", response_model=ConfirmOut, dependencies=[Depends(require_admin)])
    def supply(body: SupplyIn, svc: Services = Depends(services)) -> dict:
        try:
            revised = supply_fact(svc.plans, svc.knowledge, svc.kernel, **body.model_dump())
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        return {"revised_plans": revised}

    @router.get("/facts/open", response_model=OpenFactsOut, dependencies=[Depends(require_admin)])
    def facts_open(svc: Services = Depends(services)) -> dict:
        tenant = svc.settings.tenant_id
        return {"items": open_facts(svc.engine, tenant, open_confirm_tasks(svc.engine, tenant)),
                "requested_programmes": self_serve.requested_programmes_out(svc.plans)}

    @router.post("/research/{programme_ref}", status_code=202, response_model=ResearchStartOut,
                 dependencies=[Depends(require_admin)])
    def research_now(programme_ref: str, intake_year: int = Query(ge=2025, le=2100),
                     svc: Services = Depends(services)) -> dict:
        """Starts today's research run for a programme now (the same workflow ID the worker would use)."""
        tenant = svc.settings.tenant_id
        if ProgrammeStore(svc.engine, tenant).get(programme_ref) is None:
            raise HTTPException(status_code=404, detail="programme not found")
        wid, sent = enqueue_one(svc.engine, svc.dbos_client(), tenant, programme_ref, intake_year, svc.today())
        return {"workflow_id": wid, "enqueued": sent}

    @router.get("/research/runs", response_model=ResearchRunsOut, dependencies=[Depends(require_admin)])
    def runs(programme: str | None = None, svc: Services = Depends(services)) -> dict:
        return {"runs": research_runs(svc.engine, svc.settings.tenant_id, programme)}

    @router.get("/programmes", response_model=ProgrammesOut)
    def programmes(student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        return {"programmes": student_programmes(svc.engine, svc.settings.tenant_id, student)}

    # --- Slice 4: self-serve start and eligibility (spec §4). Eligibility warns, never blocks (S4-D5). ----------

    def my_plan_on() -> None:
        if not my_plan_gate.enabled():  # P1-T9: off, the route does not exist (the body FastAPI gives an unknown one)
            raise HTTPException(status_code=404, detail="Not Found")

    @router.get("/plan", response_model=MyPlanOut, dependencies=[Depends(my_plan_on)])
    def my_plan(student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        return my_plan_view.build_my_plan(svc, student)

    @router.get("/routes", response_model=RoutesOut)
    def routes(student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        return {"routes": self_serve.routes_out(svc.plans)}

    @router.get("/routes/{route_key}/programmes", response_model=RouteProgrammesOut)
    def route_programmes(route_key: str, intake: int = Query(ge=2025, le=2100),
                         student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        found = self_serve.route_programmes(svc.plans, student, route_key, intake)
        if found is None:
            raise HTTPException(status_code=404, detail="route not found")
        return {"route": route_key, "intake_year": intake, "programmes": found}

    @router.get("/eligibility/{programme_ref}", response_model=EligibilityOut)
    def eligibility(programme_ref: str, route: str, intake: int = Query(ge=2025, le=2100),
                    student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        found = self_serve.eligibility(svc.plans, student, programme_ref, route, intake)
        if found is None:
            raise HTTPException(status_code=404, detail="programme not found on this route")
        return found

    @router.post("/plans/self", status_code=201, response_model=SelfPlanOut)
    def start_self(body: SelfStartIn, response: Response, student: str = Depends(consented_student),
                   svc: Services = Depends(services)) -> dict:
        try:
            ref = builder.start(svc.plans, student, body.route, body.intake, body.choices)
        except builder.PlanExists as e:
            raise HTTPException(status_code=409, detail=str(e)) from None
        except builder.ChoiceRefused as e:  # the Counsellor is on and would not take the choice (R-09)
            return JSONResponse(status_code=409, content={"detail": e.code, "note": choice_texts.note(e.code, svc.settings)})
        except builder.CounsellorUnavailable:
            return JSONResponse(status_code=503, content={"detail": "counsellor_unavailable"})
        except (builder.NotAllowed, PlaybookError, CompileError) as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        if isinstance(ref, builder.Preparing):  # no plan yet: it comes from the intake of the decision version
            note = choice_texts.note("preparing", svc.settings) if ref.state == "preparing" else None
            return JSONResponse(status_code=202, content={"state": ref.state, "decision_version": ref.decision_version,
                                                          "note": note})
        if not ref.created:
            response.status_code = 200
        return self_serve.self_plan_out(svc.plans, ref.plan_id)

    def _change(svc: Services, plan_id: int, do):
        try:
            done = do()
        except builder.NotYourPlan:
            raise HTTPException(status_code=404, detail="plan not found") from None
        except builder.NotAllowed as e:  # includes SwapLimit
            raise HTTPException(status_code=409, detail=str(e)) from None
        if isinstance(done, tuple) and done[0] == "requested":  # a Counsellor plan: the change goes to the Counsellor
            choice_requests.notify(choice_requests.key_of(done[1]))  # the transaction is committed
            return JSONResponse(status_code=202, content={"state": "requested", "proposal_id": done[1]})
        return self_serve.self_plan_out(svc.plans, plan_id)

    @router.post("/plans/{plan_id}/swap", response_model=SelfPlanOut)
    def swap_programme(plan_id: int, body: SwapIn, student: str = Depends(current_student_ref_for_write),
                       svc: Services = Depends(services)) -> dict:
        return _change(svc, plan_id, lambda: builder.swap(svc.plans, student, plan_id, body.out, body.in_))

    @router.delete("/plans/{plan_id}/programmes/{programme_ref}", response_model=SelfPlanOut)
    def remove_programme(plan_id: int, programme_ref: str, student: str = Depends(current_student_ref_for_write),
                         svc: Services = Depends(services)) -> dict:
        return _change(svc, plan_id, lambda: builder.remove(svc.plans, student, plan_id, programme_ref))

    @router.post("/programmes/requests", status_code=202, response_model=RequestOut)
    def request_new(body: RequestIn, student: str = Depends(current_student_ref_for_write),
                    svc: Services = Depends(services)) -> dict:
        if body.route not in self_serve.newest_books(svc.plans):
            raise HTTPException(status_code=422, detail=f"unknown route '{body.route}'")
        tenant = svc.settings.tenant_id
        try:
            ref, created = request_programme(
                svc.engine, tenant, student, body.route, body.university, body.name, body.url,
                now=clock.now(), intake_year=body.intake_year,
                enqueue=lambda r: enqueue_one(svc.engine, svc.dbos_client(), tenant, r, body.intake_year, svc.today()))
        except RequestLimit as e:
            raise HTTPException(status_code=429, detail=str(e)) from None
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        return {"programme_ref": ref, "created": created}

    # --- Slice 3: documents (spec §4). Students see and change only their own; files never leave (S3-D10). ---

    def own_document(svc: Services, doc_id: int, student: str):
        doc = DocumentStore(svc.engine, svc.settings.tenant_id).get(doc_id)
        if doc is None or doc.student_ref != student or doc.status == "deleted":
            raise HTTPException(status_code=404, detail="document not found")
        return doc

    @router.get("/documents/admin", response_model=DocumentsOut, dependencies=[Depends(require_admin)])
    def documents_admin(student: str = Query(min_length=1), svc: Services = Depends(services)) -> dict:
        """Status, fields and findings only: never file bytes (S3-D10)."""
        return documents_out(svc.engine, svc.settings.tenant_id, student, svc.document_types)

    @router.post("/documents", status_code=201, response_model=DocumentOut)
    def upload_document(file: UploadFile = File(...), doc_type: str = Form(...),
                        student: str = Depends(consented_student),
                        svc: Services = Depends(services)) -> dict:
        if document_files.enabled():  # P1-T7: the one upload is POST /v1/files; refused before the file is read into memory
            raise HTTPException(status_code=409, detail=connect_texts.text("use_documents_page"))
        t = svc.document_types.get(doc_type)
        if t is None:
            raise HTTPException(status_code=422, detail=f"unknown document type: {doc_type}")
        name = (file.filename or "document")[:255]
        data = file.file.read(MAX_BYTES + 1)  # one byte over the limit is enough to refuse it
        try:
            kind = check_upload(name, data)
        except UploadError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        tenant = svc.settings.tenant_id
        store = DocumentStore(svc.engine, tenant)
        try:
            doc_id = store.create(student, doc_type, t.version, name, "application/pdf" if kind == "pdf"
                                  else f"image/{kind}", data)
        except DuplicateDocument as e:
            raise HTTPException(status_code=409, detail=str(e)) from None
        doc = store.get(doc_id)
        enqueue_document(svc.dbos_client(), tenant, doc)  # if this is lost, the daily documents_retry sends it
        return document_out(store, doc, [], svc.document_types)

    @router.get("/documents", response_model=DocumentsOut)
    def documents(student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        return documents_out(svc.engine, svc.settings.tenant_id, student, svc.document_types)

    @router.get("/documents/{doc_id}/vault-check", response_model=VaultCheckOut)
    def vault_check(doc_id: int, student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        """Every field with a Vault key compared with the Vault, live (P1-T7, D-y11, R-16). Nothing is stored. Without
        the one upload or without the host's answer there is nothing to compare with: 404 (no standalone fallback)."""
        doc = own_document(svc, doc_id, student)
        t = svc.document_types.get(doc.doc_type)
        tenant = svc.settings.tenant_id
        facts = (student_facts.host_facts(student, engine=svc.engine, tenant_id=tenant)
                 if document_files.enabled() and t is not None else None)
        if facts is None:
            raise HTTPException(status_code=404, detail="nothing to compare with")
        values = {f["field"]: f["value_confirmed"] if f["confirmed_at"] else f["value_read"]
                  for f in DocumentStore(svc.engine, tenant).fields(doc_id)}
        fields = vault_compare(t, values, facts)
        differs = any(f["outcome"] == "differs" for f in fields)
        return {"fields": fields, "note": connect_texts.text("vault_differs") if differs else None}

    @router.post("/documents/{doc_id}/confirm", response_model=DocumentOut)
    def confirm_doc(doc_id: int, body: ConfirmDocumentIn, student: str = Depends(current_student_ref_for_write),
                    svc: Services = Depends(services)) -> dict:
        doc = own_document(svc, doc_id, student)
        tenant = svc.settings.tenant_id
        try:
            proposal_key = confirm_document(svc.engine, tenant, svc.document_types, svc.name_variants, doc, body.fields)
        except NotConfirmable as e:
            raise HTTPException(status_code=409, detail=str(e)) from None
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        _notify(svc.plans, student)  # Slice 4: a note if a programme's eligibility changed
        refresh(svc, student, "document_changed")  # P1-T8: a confirmed document may answer a request
        store = DocumentStore(svc.engine, tenant)
        findings = [finding_out(f) for f in FindingStore(svc.engine, tenant).list_open(student)]
        out = document_out(store, store.get(doc_id), findings, svc.document_types)
        fact_proposals.notify(proposal_key)  # P1-T7: after the answer is built; the host's sweep is the backup
        return out

    @router.post("/documents/findings/{finding_id}/resolve", response_model=FindingOut)
    def resolve(finding_id: int, body: ResolveIn, student: str = Depends(current_student_ref_for_write),
                svc: Services = Depends(services)) -> dict:
        tenant = svc.settings.tenant_id
        finding = FindingStore(svc.engine, tenant).get(finding_id)
        if finding is None or finding["student_ref"] != student:
            raise HTTPException(status_code=404, detail="finding not found")
        if finding["status"] != "open":
            raise HTTPException(status_code=409, detail="this finding is already resolved")
        try:
            resolved = resolve_finding(svc.engine, tenant, finding, body.value)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        _notify(svc.plans, student)  # Slice 4: the resolved value may change eligibility
        refresh(svc, student, "document_changed")  # P1-T8: a resolved mismatch unblocks the steps it paused
        return finding_out(resolved)

    @router.delete("/documents/{doc_id}", status_code=204)
    def delete_doc(doc_id: int, student: str = Depends(current_student_ref_for_write),
                   svc: Services = Depends(services)) -> Response:
        doc = own_document(svc, doc_id, student)
        delete_document(svc.engine, svc.settings.tenant_id, svc.document_types, svc.name_variants, doc,
                        client=svc.dbos_client())
        refresh(svc, student, "document_changed")  # P1-T8: a deleted document is asked for again
        return Response(status_code=204)

    @router.get("/profile", response_model=ProfileOut)
    def profile(student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        return {"values": ProfileStore(svc.engine, svc.settings.tenant_id).all(student)}

    # --- Slice 5: statements (spec §4). The student's own only; the route comes from their plan. ---

    def route_of(svc: Services, student: str):
        plan = self_serve.student_plan(svc.plans, student)
        cfg = plan and svc.statement_configs.get(plan.route_key)
        if cfg is None:
            raise HTTPException(status_code=404, detail="no statements for your route yet: start a plan first")
        return plan, cfg

    def complete_ready(svc: Services, student: str) -> None:
        """Completes a documents task that became ready after its statements were approved (final review). Extra
        work on a read: it never turns the read into an error."""
        try:
            plan = self_serve.student_plan(svc.plans, student)
            cfg = plan and svc.statement_configs.get(plan.route_key)
            if cfg is not None:
                complete_documents_tasks(svc.engine, svc.kernel, svc.knowledge, svc.settings.tenant_id, student, cfg,
                                         plan.plan_id, plan.year)
        except Exception:
            log.exception("statement task completion failed for a student")

    def not_while_drafting(art) -> None:
        if art.status == "drafting":  # the running draft would land on top of the student's change (final review)
            raise HTTPException(status_code=409, detail="a draft is being written; wait for it, then edit or approve")

    def own_artifact(svc: Services, artifact_id: int, student: str):
        art = ArtifactStore(svc.engine, svc.settings.tenant_id).get(artifact_id)
        if art is None or art.student_ref != student or art.kind not in STATEMENT_KINDS:  # never a pack or visa file
            raise HTTPException(status_code=404, detail="statement not found")
        return art

    @router.get("/statements/interview", response_model=InterviewOut)
    def statement_interview(student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        _, cfg = route_of(svc, student)
        tenant = svc.settings.tenant_id
        return {"route": cfg.route_key, "questions": stmt.interview(svc.engine, tenant, student, cfg),
                "missing": stmt.missing_required(svc.engine, tenant, student, cfg)}

    @router.put("/statements/answers/{question_id}", response_model=AnswerOut)
    def statement_answer(question_id: str, body: AnswerIn, student: str = Depends(current_student_ref_for_write),
                         svc: Services = Depends(services)) -> dict:
        plan, cfg = route_of(svc, student)
        tenant = svc.settings.tenant_id
        try:
            if question_id.startswith(stmt.FOLLOW_UP):
                started = stmt.answer_follow_up(svc.engine, svc.dbos_client(), tenant, student, cfg, question_id,
                                                body.answer, plan.year, svc.knowledge)
            else:
                stmt.save_answer(svc.engine, tenant, student, cfg, question_id, body.answer)
                started = []
        except ValueError as e:
            code = 404 if "unknown question" in str(e) else 422
            raise HTTPException(status_code=code, detail=str(e)) from None
        return {"saved": True, "drafting": len(started)}

    @router.put("/statements/rules/{programme_ref}", status_code=204)
    def statement_rules(programme_ref: str, body: PastedRulesIn, student: str = Depends(current_student_ref_for_write),
                        svc: Services = Depends(services)) -> Response:
        plan, _ = route_of(svc, student)
        if programme_ref not in plan.programmes:
            raise HTTPException(status_code=404, detail="this programme is not in your plan")
        try:
            stmt.save_pasted_rules(svc.engine, svc.settings.tenant_id, student, programme_ref, body.prompt,
                                   body.limit_words, body.limit_chars)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        return Response(status_code=204)

    @router.get("/statements", response_model=StatementsOut)
    def statements(student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        complete_ready(svc, student)
        tenant = svc.settings.tenant_id
        store = ArtifactStore(svc.engine, tenant)
        plan = self_serve.student_plan(svc.plans, student)
        cfg = plan and svc.statement_configs.get(plan.route_key)
        store_p = ProgrammeStore(svc.engine, tenant)
        programmes = [] if cfg is None else [  # each plan programme's rules: does it ask for its own statement?
            {"programme_ref": ref, "name": p.name if p else None, "university": p.university if p else None,
             **asdict(resolve_rules(svc.engine, tenant, svc.knowledge, student, ref, plan.year, cfg, "sop"))}
            for ref in plan.programmes for p in [store_p.get(ref)]]
        return {"statements": [statement_out(store, a) for a in store.list_for(student, STATEMENT_KINDS)],
                "programmes": programmes}

    @router.post("/statements/{kind}/draft", status_code=202, response_model=StatementOut)
    def statement_draft(kind: str, body: DraftIn | None = None, student: str = Depends(current_student_ref_for_write),
                        svc: Services = Depends(services)) -> dict:
        if kind not in ("sop", "cv"):
            raise HTTPException(status_code=404, detail=f"unknown statement kind: {kind}")
        plan, cfg = route_of(svc, student)
        programme_ref = (body or DraftIn()).programme_ref
        if programme_ref is not None and (kind == "cv" or programme_ref not in plan.programmes):
            raise HTTPException(status_code=422, detail="a programme SOP needs a programme in your plan; a CV has none")
        tenant = svc.settings.tenant_id
        missing = stmt.missing_required(svc.engine, tenant, student, cfg)
        if missing:
            raise HTTPException(status_code=409, detail={"message": "answer these questions first", "missing": missing})
        store = ArtifactStore(svc.engine, tenant)
        art = store.get_or_create(student, kind, programme_ref)
        stmt.start_draft(svc.engine, svc.dbos_client(), tenant, cfg, art.id, plan.year, svc.knowledge)
        return statement_out(store, store.get(art.id))

    @router.put("/statements/{artifact_id}/text", response_model=StatementOut)
    def statement_text(artifact_id: int, body: TextIn, student: str = Depends(current_student_ref_for_write),
                       svc: Services = Depends(services)) -> dict:
        art = own_artifact(svc, artifact_id, student)
        not_while_drafting(art)
        plan, cfg = route_of(svc, student)
        tenant = svc.settings.tenant_id
        inputs = inputs_for(svc.engine, tenant, cfg, student, art.kind, art.programme_ref, svc.knowledge, plan.year)
        flags = [c.text for c in unsupported(body.text, sources(inputs))]
        store = ArtifactStore(svc.engine, tenant)
        store.add_version(artifact_id, body.text, "student", flags=flags, limit_words=inputs.rules.limit_words)
        return statement_out(store, store.get(artifact_id))

    @router.post("/statements/{artifact_id}/approve", response_model=ApproveOut)
    def statement_approve(artifact_id: int, body: ApproveIn, student: str = Depends(current_student_ref_for_write),
                          svc: Services = Depends(services)) -> dict:
        not_while_drafting(own_artifact(svc, artifact_id, student))
        plan, cfg = route_of(svc, student)
        tenant = svc.settings.tenant_id
        try:
            approval = ArtifactStore(svc.engine, tenant).approve(artifact_id, body.version)
        except KeyError:
            raise HTTPException(status_code=404, detail="version not found") from None
        done = complete_documents_tasks(svc.engine, svc.kernel, svc.knowledge, tenant, student, cfg, plan.plan_id,
                                        plan.year)
        return {"version": approval.version, "sha256": approval.sha256, "approved_at": approval.approved_at,
                "completed_tasks": done}

    @router.get("/admin/costs", response_model=CostReportOut, dependencies=[Depends(require_admin)])
    def costs(start: date = Query(alias="from"), end: date = Query(alias="to"),
              svc: Services = Depends(services)) -> dict:
        """Slice 9 Task 8 (spec §3.4): AI cost per student between two calendar dates (UTC), both included."""
        if end < start:
            raise HTTPException(status_code=422, detail="to is before from")
        return asdict(cost_report(svc.engine, svc.settings.tenant_id, start, end))

    @router.get("/admin/email-status", response_model=EmailStatusOut, dependencies=[Depends(require_admin)])
    def email_status_route(svc: Services = Depends(services)) -> dict:
        """Slice 9b: the sender, the recipient lookup, outbox email rows per status and the last config error."""
        from app.os.outbox.status import email_status

        return email_status(svc.engine, svc.settings)

    add_pack_routes(router, services)  # Slice 6a (spec §4)
    add_visa_routes(router, services)  # Slice 6b (spec §4)
    add_replan_routes(router, services, require_admin)  # Slice 7 (spec §4)
    add_consistency_routes(router, services, require_admin)  # P1-T10 (R-05)
    if get_services().settings.rehearsal:  # Slice 9a (spec §2.2): absent on a pilot server, so 404
        from app.os.rehearsal.api import add_rehearsal_routes

        add_rehearsal_routes(router, services, require_admin)
    return router
