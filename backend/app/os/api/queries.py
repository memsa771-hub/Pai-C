"""PlanQuery and Knowledge reads (reads are allowed outside the kernel; only writes are kernel-only)."""

import re
from collections.abc import Mapping

from sqlalchemy import Engine, select

from app.os.kernel.revisions import CANCELLED_MARK, DONE_MARK, NOTICE_PREFIX
from app.os.kernel.states import PLAN_OPEN
from app.os import models

T, P = models.tasks, models.plans
F, R, A, G = models.knowledge_facts, models.research_runs, models.agent_runs, models.programmes


def task_out(row) -> dict:
    return {
        "id": row.id, "instance_key": row.instance_key, "title": row.title, "kind": row.kind,
        "inbox_kind": row.inbox_kind, "programme_ref": row.programme_ref, "state": row.state,
        "blocked_reason": row.blocked_reason, "due_at": row.due_at, "due_tz": row.due_tz,
        "provisional": row.provisional, "estimated": row.estimated, "slack_days": row.slack_days,
        "critical": row.critical, "citations": row.citations or [],
    }


def removed_programmes(conn, tenant_id: str, plan_ids) -> dict[int, set[str]]:
    """Plan id -> the programmes an accepted change removed (an active `cancel_programme` override, Slice 7). They
    stay in the plan's contract, but they are no longer the student's programmes on any page (Slice 9 Task 11,
    `walk:S3:removed_programme_still_shown`)."""
    O = models.plan_overrides
    ids = list(plan_ids)
    out: dict[int, set[str]] = {i: set() for i in ids}
    if ids:
        for plan_id, ref in conn.execute(select(O.c.plan_id, O.c.target).where(
                O.c.tenant_id == tenant_id, O.c.plan_id.in_(ids), O.c.op == "cancel_programme",
                O.c.active.is_(True))).all():
            out[plan_id].add(ref)
    return out


def plan_out(engine: Engine, tenant_id: str, plan_id: int) -> dict | None:
    with engine.connect() as conn:
        plan = conn.execute(select(P).where(P.c.id == plan_id, P.c.tenant_id == tenant_id)).first()
        if plan is None:
            return None
        rows = conn.execute(select(T).where(T.c.plan_id == plan_id)
                            .order_by(T.c.due_at.asc().nulls_last(), T.c.instance_key)).all()
    return {"plan_id": plan.id, "revision": plan.current_revision, "status": plan.status,
            "tasks": [task_out(r) for r in rows]}


def eligibility_notes(engine: Engine, tenant_id: str, student_ref: str) -> list[dict]:
    """The student's unread eligibility change notes, newest first (Slice 4 S4-D7)."""
    N = models.eligibility_notes
    with engine.connect() as conn:
        rows = conn.execute(select(N).where(N.c.tenant_id == tenant_id, N.c.student_ref == student_ref,
                                            N.c.read_at.is_(None)).order_by(N.c.id.desc())).all()
    return [{"id": r.id, "programme_ref": r.programme_ref, "verdict": r.verdict, "payload": r.payload,
             "created_at": r.created_at} for r in rows]


def mark_note_read(engine: Engine, tenant_id: str, student_ref: str, note_id: int) -> bool:
    """False if the note is not this student's."""
    from sqlalchemy import func, update

    N = models.eligibility_notes
    with engine.begin() as conn:
        found = conn.execute(update(N).where(N.c.id == note_id, N.c.tenant_id == tenant_id,
                                             N.c.student_ref == student_ref)
                             .values(read_at=func.coalesce(N.c.read_at, func.now())).returning(N.c.id)).scalar()
    return found is not None


_MARKS = re.compile(rf"(?:(?:{re.escape(CANCELLED_MARK)}|{re.escape(DONE_MARK)})\d+)+$")


def notice_changes(conn, tenant_id: str, plan_id: int, result: dict | None) -> list[dict]:
    """What a "Your plan was updated" item changed for the student: each of their steps the revision added, removed,
    changed or kept (started or kept on purpose), with its title and programme (Slice 9 Task 11). Work steps
    (research, checks) are left out."""
    number = (result or {}).get("revision")
    if number is None:
        return []
    diff = conn.execute(select(models.plan_revisions.c.diff).where(
        models.plan_revisions.c.plan_id == plan_id, models.plan_revisions.c.number == number)).scalar()
    if not diff:
        return []
    rows = conn.execute(select(T.c.instance_key, T.c.title, T.c.programme_ref, T.c.kind).where(
        T.c.plan_id == plan_id).order_by(T.c.id)).all()
    exact = {r.instance_key: r for r in rows}
    by_base = {_MARKS.sub("", r.instance_key): r for r in rows}  # the newest row of each key
    out = []
    lists = [("added", "added"), ("removed", "removed"), ("changed", "changed"), ("skipped_started", "kept"),
             ("kept_protected", "kept")]
    for name, change in lists:
        for key in diff.get(name) or []:
            row = exact.get(f"{key}{CANCELLED_MARK}{number}") if change == "removed" else None
            row = row or exact.get(key) or by_base.get(key)
            if row is not None and row.kind == "student" and not key.startswith(NOTICE_PREFIX):
                out.append({"change": change, "instance_key": key, "title": row.title,
                            "programme_ref": row.programme_ref})
    refs = {c["programme_ref"] for c in out if c["programme_ref"]}
    names = dict(conn.execute(select(G.c.ref, G.c.name).where(G.c.tenant_id == tenant_id, G.c.ref.in_(refs))).all()) \
        if refs else {}
    return [{**c, "programme_name": names.get(c["programme_ref"])} for c in out]


def inbox_items(engine: Engine, tenant_id: str, student_ref: str) -> list[dict]:
    """The student's open inbox items, each with its programme's name (Slice 9 Task 11: two cards of two programmes
    must be told apart) and, for a "Your plan was updated" item, what it changed for them."""
    with engine.connect() as conn:
        rows = conn.execute(select(T, G.c.name.label("programme_name"), G.c.university.label("university"))
                            .join(P, P.c.id == T.c.plan_id)
                            .outerjoin(G, (G.c.tenant_id == T.c.tenant_id) & (G.c.ref == T.c.programme_ref))
                            .where(T.c.tenant_id == tenant_id, P.c.student_ref == student_ref, T.c.kind == "student",
                                   T.c.state == "waiting_student")
                            .order_by(T.c.due_at.asc().nulls_last(), T.c.id)).all()
        return [{**task_out(r), "programme_name": r.programme_name, "university": r.university,
                 "changes": notice_changes(conn, tenant_id, r.plan_id, r.result) if r.instance_key.startswith(NOTICE_PREFIX)
                 else []} for r in rows]


def notice_link(engine: Engine, task_id: int) -> dict:
    """A plan-update notice's link to its revision: {"revision", "cause"} from its stored result (what is there)."""
    with engine.connect() as conn:
        result = conn.execute(select(T.c.result).where(T.c.id == task_id)).scalar() or {}
    return {k: result[k] for k in ("revision", "cause") if k in result}


def task_plan_and_template(engine: Engine, task_id: int) -> tuple[int, str] | None:
    with engine.connect() as conn:
        row = conn.execute(select(T.c.plan_id, T.c.template_key).where(T.c.id == task_id)).first()
    return None if row is None else (row.plan_id, row.template_key)


def waiting_items(engine: Engine, tenant_id: str, student_ref: str, books: Mapping) -> list[dict]:
    """The student's steps that wait for a fact nobody has given yet (blocked `fact_missing:<field>`), each with what
    it waits for in its pinned playbook's words (`anchor.waiting`; None if the playbook has none). Listed after the
    inbox items so the student is told what the plan is waiting for, never "nothing to do" (Slice 9 Task 11,
    `walk:S1:nothing_to_do_while_blocked`). Nothing can be done on them: completing one is refused."""
    pins = models.playbook_pins
    with engine.connect() as conn:
        rows = conn.execute(select(T, G.c.name.label("programme_name"), G.c.university.label("university"),
                                   pins.c.playbook_key, pins.c.version.label("pinned_version"))
                            .join(P, P.c.id == T.c.plan_id)
                            .join(pins, pins.c.plan_id == T.c.plan_id)
                            .outerjoin(G, (G.c.tenant_id == T.c.tenant_id) & (G.c.ref == T.c.programme_ref))
                            .where(T.c.tenant_id == tenant_id, P.c.student_ref == student_ref, T.c.kind == "student",
                                   P.c.status.in_(PLAN_OPEN), T.c.state == "blocked",
                                   T.c.blocked_reason.like("fact_missing:%"))
                            .order_by(T.c.id)).all()
    out = []
    for r in rows:
        book = books.get((r.playbook_key, r.pinned_version))
        tmpl = next((t for t in book.tasks if t.template_key == r.template_key), None) if book else None
        anchor = tmpl.anchor if tmpl else None
        said = anchor.waiting if anchor and r.blocked_reason == f"fact_missing:{anchor.fact}" else None
        out.append({**task_out(r), "programme_name": r.programme_name, "university": r.university, "changes": [],
                    "waiting_for": said})
    return out


# --- Knowledge (Slice 2 spec §4.8) ---------------------------------------------------------------------------


def _run_out(row) -> dict:
    return {"id": row.id, "programme_ref": row.programme_ref, "intake_year": row.intake_year,
            "workflow_id": row.workflow_id, "status": row.status, "started_at": row.started_at,
            "ended_at": row.ended_at, "pages": row.pages, "confirmed": row.confirmed,
            "unconfirmed": row.unconfirmed, "cost_usd": float(row.cost_usd)}


def research_runs(engine: Engine, tenant_id: str, programme: str | None = None, limit: int = 100) -> list[dict]:
    """Research runs, newest first, each with its readings (model, tokens, cost, error)."""
    q = select(R).where(R.c.tenant_id == tenant_id)
    if programme:
        q = q.where(R.c.programme_ref == programme)
    with engine.connect() as conn:
        runs = conn.execute(q.order_by(R.c.started_at.desc(), R.c.id.desc()).limit(limit)).all()
        readings = conn.execute(select(A).where(A.c.tenant_id == tenant_id, A.c.research_run_id.in_([r.id for r in runs]))
                                .order_by(A.c.research_run_id, A.c.reading)).all() if runs else []
    by_run: dict[int, list] = {}
    for a in readings:
        by_run.setdefault(a.research_run_id, []).append({
            "reading": a.reading, "agent": a.agent, "agent_version": a.agent_version, "model": a.model,
            "input_tokens": a.input_tokens, "cached_tokens": a.cached_tokens, "output_tokens": a.output_tokens,
            "cost_usd": float(a.cost_usd), "error": a.error, "at": a.at})
    return [{**_run_out(r), "readings": by_run.get(r.id, [])} for r in runs]


def _fact_out(row, admin: bool) -> dict:
    out = {"field": row.field, "value": row.value, "status": row.status, "source_url": row.url or None,
           "quote": row.quote or None, "checked_at": row.checked_at, "conflict_note": row.conflict_note}
    if admin:
        out |= {"fact_id": row.id, "source": row.source, "evidence": row.evidence,
                "research_run_id": row.research_run_id}
    return out


def open_facts(engine: Engine, tenant_id: str, items: list[dict]) -> list[dict]:
    """The open confirm tasks, each with its fact (for the plan's intake year, with evidence) and the
    programme's last research run."""
    year = P.c.contract["target_intake"]["year"].as_integer()
    with engine.connect() as conn:
        years = dict(conn.execute(select(P.c.id, year).where(
            P.c.tenant_id == tenant_id, P.c.id.in_({i["plan_id"] for i in items}))).all()) if items else {}
        out = []
        for i in items:
            fact = conn.execute(select(F).where(
                F.c.tenant_id == tenant_id, F.c.scope == i["scope"], F.c.ref == i["ref"], F.c.field == i["field"],
                F.c.intake_year == years.get(i["plan_id"]))).first()
            run = conn.execute(select(R).where(R.c.tenant_id == tenant_id, R.c.programme_ref == i["ref"])
                               .order_by(R.c.started_at.desc(), R.c.id.desc()).limit(1)).first() \
                if i["scope"] == "programme" else None
            out.append({**i, "intake_year": years.get(i["plan_id"]),
                        "fact": None if fact is None else _fact_out(fact, admin=True),
                        "last_research_run": None if run is None else _run_out(run)})
    return out


def student_programmes(engine: Engine, tenant_id: str, student_ref: str) -> list[dict]:
    """The programmes in the student's plans (not those a change removed), in plan then rank order, with their facts for the plan's intake
    year: value, status, source link, quote, check date and conflict note. No evidence (it is for admins)."""
    with engine.connect() as conn:
        plans = conn.execute(select(P.c.id, P.c.contract).where(
            P.c.tenant_id == tenant_id, P.c.student_ref == student_ref, P.c.status.in_(PLAN_OPEN)).order_by(P.c.id)).all()
        out, seen = [], set()
        removed = removed_programmes(conn, tenant_id, [p for p, _ in plans])
        for plan_id, contract in plans:
            intake_year = contract["target_intake"]["year"]
            for choice in sorted(contract["programmes"], key=lambda c: c["rank"]):
                ref = choice["programme_ref"]
                if ref in removed[plan_id] or (ref, intake_year) in seen:
                    continue
                seen.add((ref, intake_year))
                prog = conn.execute(select(G).where(G.c.tenant_id == tenant_id, G.c.ref == ref)).first()
                facts = conn.execute(select(F).where(
                    F.c.tenant_id == tenant_id, F.c.scope == "programme", F.c.ref == ref,
                    F.c.intake_year == intake_year).order_by(F.c.field)).all()
                out.append({"ref": ref, "plan_id": plan_id, "rank": choice["rank"], "name": prog.name if prog else ref,
                            "university": prog.university if prog else None, "intake_year": intake_year,
                            "facts": [_fact_out(f, admin=False) for f in facts]})
    return out


# --- Slice 3: documents ----------------------------------------------------------------------------------------


def finding_out(f: dict) -> dict:
    return {"id": f["id"], "kind": f["kind"], "field": f["field"], "status": f["status"],
            "resolution": f["resolution"], "items": [{"document_id": i, "value": v} for i, v in f["items"]]}


def documents_out(engine: Engine, tenant_id: str, student_ref: str, types: dict) -> dict:
    """The student's live documents with their fields and open findings. File bytes are never read here."""
    from app.os.documents.store import DocumentStore, FindingStore  # imported here: keeps the API's imports small

    store = DocumentStore(engine, tenant_id)
    findings = [finding_out(f) for f in FindingStore(engine, tenant_id).list_open(student_ref)]
    return {"documents": [document_out(store, d, findings, types) for d in store.list_for(student_ref)],
            "findings": findings,
            "doc_types": sorted(({"key": t.key, "label": t.label} for t in types.values()), key=lambda t: t["label"])}


def document_out(store, d, findings: list[dict], types: dict | None = None) -> dict:
    """A document with its fields; each field carries its type's plain label (None: the page words the name)."""
    spec = (types or {}).get(d.doc_type)
    labels = {f.name: f.label for f in spec.fields} if spec is not None else {}
    fields = [{**{k: f[k] for k in ("field", "value_read", "check", "reasons", "value_confirmed")},
               "label": labels.get(f["field"])} for f in store.fields(d.id)]
    return {"id": d.id, "doc_type": d.doc_type, "filename": d.filename, "status": d.status,
            "detected_type": d.detected_type, "pages": d.pages, "error": d.error, "created_at": d.created_at,
            "read_at": d.read_at, "confirmed_at": d.confirmed_at, "fields": fields,
            "findings": [f for f in findings if any(i["document_id"] == d.id for i in f["items"])]}


def statement_out(store, art) -> dict:
    """One artifact with its latest version and its approval (Slice 5 spec §4)."""
    latest = store.version(art.id, art.current_version) if art.current_version else None
    approval = store.approval(art.id)
    return {"id": art.id, "kind": art.kind, "programme_ref": art.programme_ref, "status": art.status,
            "version": None if latest is None else {
                "number": latest.number, "text": latest.text, "author": latest.author, "words": latest.words,
                "critic": latest.critic, "flags": latest.flags, "limit_words": latest.limit_words,
                "created_at": latest.created_at},
            "approval": None if approval is None else {"version": approval.version, "sha256": approval.sha256,
                                                       "approved_at": approval.approved_at}}
