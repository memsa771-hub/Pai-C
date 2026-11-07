"""What the student can choose between in a "which is right" request, and where their answer goes (P1-T8, D-w12, D-w13).

The two values are read live on every call and never stored (R-01). A question has one of three origins
(`state.QuestionRef.origin`), and the origin decides the route of the answer:

- `vault`: the host writes it through the Vault's own card resolution (`ports.fact_questions.answer`);
- `impossible`: a value above its total; only a new value is taken, and the host writes it as the student's own edit;
- `documents`: two of the student's documents differ on an identity field. That stays OS document data
  (`resolve_finding`); it never goes to the Vault (identity fields are not on the StudentFacts allow-list)."""

import hashlib
import json
from dataclasses import dataclass, field

from app.os.documents.confirm import resolve_finding
from app.os.documents.store import DocumentStore, FindingStore
from app.os.ports import fact_questions
from app.os.requests import state as state_mod, texts
from app.os.requests.store import Request

_BY_ANSWER = {"keep_current": "current", "accept_proposed": "proposed", "provide_new": "new"}


class AnswerError(Exception):
    """The answer cannot be taken: `status` is the HTTP status, `detail` a code (never a value), `note` an approved
    sentence for the student, when there is one."""

    def __init__(self, status: int, detail: str, note: str | None = None):
        super().__init__(detail)
        self.status, self.detail, self.note = status, detail, note


@dataclass(frozen=True)
class Choices:
    choices: list[dict] = field(default_factory=list)
    allow_new: bool = False
    impossible: bool = False
    ref: str | None = None  # the question the student sees; the answer names it back (409 `answer_changed` when it moved)
    seen: str | None = None  # a short hash of the values the student sees; the answer names it back too


def _kind(value: dict) -> str:
    """Where the value comes from. The host says "from a document" or not; it does not say whether a stated value was
    said in the chat or typed on the profile page, so a stated one is simply "vault" (saved in PAI): never a guess."""
    return "document" if value.get("document_ref") else "vault"


def seen_token(ref: str, pairs) -> str:
    """A short hash of the question and the values on it, so an answer can be tied to what the student saw (no value is
    readable from it)."""
    raw = json.dumps([ref, sorted([str(k), v] for k, v in pairs)], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def question_ref(q: state_mod.QuestionRef) -> str:
    """The ref the student is shown and sends back: the Vault card, the open finding, or `impossible:<value key>`."""
    return f"impossible:{q.ref.partition(':')[0]}" if q.origin == "impossible" else q.ref


def _from_conflict(conflict, key: str) -> Choices:
    sides = {v.side: v for v in conflict.values}
    labels = {"current": texts.text("current_label"), "proposed": texts.text("proposed_label")}
    offered = {_BY_ANSWER[a] for a in conflict.answers}
    seen = seen_token(conflict.ref, [(v.side, v.value) for v in conflict.values])
    out = []
    for side in ("current", "proposed"):
        v = sides[side]
        if side not in offered:
            continue
        source = {"kind": _kind(v.model_dump()), "evidence": v.evidence, "document_ref": v.document_ref, "as_of": v.as_of}
        out.append({"ref": conflict.ref, "key": key, "seen": seen, "choice": side, "label": labels[side], "value": v.value,
                    "source": source})
    return Choices(out, "new" in offered, ref=conflict.ref, seen=seen)


def doc_choice(doc_id) -> str:
    return f"doc:{doc_id}"


def _from_finding(svc, student: str, finding: dict) -> Choices:
    """One choice per document that holds a value, each with its own id (a third document is a third choice)."""
    docs = DocumentStore(svc.engine, svc.settings.tenant_id)
    ref = f"finding:{finding['id']}"
    seen = seen_token(ref, finding["items"])
    out = []
    for doc_id, value in finding["items"]:
        doc = docs.get(doc_id)
        if doc is None or doc.student_ref != student or doc.deleted_at is not None:
            continue
        label = svc.document_types[doc.doc_type].label if doc.doc_type in svc.document_types else doc.doc_type
        out.append({"ref": ref, "key": doc.doc_type, "seen": seen, "choice": doc_choice(doc_id), "label": label, "value": value,
                    "source": {"kind": "document", "evidence": "shown", "document_ref": doc.file_ref or f"os:{doc.id}",
                               "as_of": doc.confirmed_at or doc.created_at}})
    return Choices(out, False, ref=ref, seen=seen)


def choices_for(svc, student: str, requests: list[Request]) -> dict[int, Choices]:
    """`request id -> Choices` for the open "which is right" requests among `requests`. Others have none. The host's
    conflicts are read once for all of them."""
    asked = [r for r in requests if r.kind == "which_is_right" and r.status == "open"]
    if not asked:
        return {}
    found = fact_questions.read(student)
    by_key = {c.key: c for c in found.conflicts} if found else {}
    state = state_mod.build(svc.plans, student, conflicts=found)
    out: dict[int, Choices] = {}
    for r in asked:
        q = state.question(r.need_kind, r.need_ref) if state else None
        if q is None:
            continue  # answered elsewhere a moment ago: the next recompile closes the request
        if q.origin == "vault":
            conflict = by_key.get(r.need_ref)
            if conflict is not None:
                out[r.id] = _from_conflict(conflict, r.need_ref)
        elif q.origin == "impossible":
            ref = question_ref(q)
            out[r.id] = Choices([], True, impossible=True, ref=ref, seen=seen_token(ref, []))
        else:
            finding = FindingStore(svc.engine, svc.settings.tenant_id).get(int(q.ref.partition(":")[2]))
            if finding is not None and finding["status"] == "open":
                out[r.id] = _from_finding(svc, student, finding)
    return out


def _seen_now(svc, student: str, req: Request, q: state_mod.QuestionRef) -> str | None:
    """The token of the values the question holds now."""
    if q.origin == "vault":
        found = fact_questions.read(student)
        conflict = next((c for c in found.conflicts if c.key == req.need_ref), None) if found else None
        return seen_token(conflict.ref, [(v.side, v.value) for v in conflict.values]) if conflict else None
    if q.origin == "impossible":
        return seen_token(question_ref(q), [])
    finding = FindingStore(svc.engine, svc.settings.tenant_id).get(int(q.ref.partition(":")[2]))
    return seen_token(q.ref, finding["items"]) if finding else None


def answer(svc, student: str, req: Request, ref: str, seen: str, choice: str, value) -> None:
    """Sends the student's answer to where the question comes from. Returns when it is written, or when the question is
    gone already (answered elsewhere); the caller then refreshes the plan. `ref` and `seen` name the question and the
    values the student saw: if either is different now, nothing is written (409 `answer_changed`). Raises AnswerError."""
    state = state_mod.build(svc.plans, student)
    q = state.question(req.need_kind, req.need_ref) if state else None
    if q is None:
        return
    if ref != question_ref(q) or seen != _seen_now(svc, student, req, q):
        raise AnswerError(409, "answer_changed", texts.text("answer_changed"))
    if q.origin in ("vault", "impossible"):
        key = req.need_ref if q.origin == "vault" else q.ref.partition(":")[0]
        done = fact_questions.answer(student, ref, key, choice, value, req.id)
        if done is None:
            raise AnswerError(404, "Not Found")  # the host's part is off, or nothing is configured
        if done["status"] == "error":
            raise AnswerError(503, "counsellor_unavailable")  # the host failed unexpectedly: not "does not exist"
        if done["status"] == "refused":
            raise AnswerError(422, str(done.get("code") or "refused"))
        return
    tenant = svc.settings.tenant_id
    finding = FindingStore(svc.engine, tenant).get(int(q.ref.partition(":")[2]))
    if finding is None or finding["student_ref"] != student or finding["status"] != "open":
        return
    items = finding["items"]
    picked = [v for d, v in items if doc_choice(d) == choice]
    if not picked:
        raise AnswerError(422, "bad_choice")  # typing a value is not offered for two documents: "new" is refused
    chosen = picked[0]
    try:
        resolve_finding(svc.engine, tenant, finding, chosen)
    except ValueError:
        raise AnswerError(422, "not_one_of_the_values") from None
