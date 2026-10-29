"""What a pack is built from (Slice 6a spec §2): the student's documents, approved statements and profile values, the
programme's facts, the playbook's constants and citations, and the student's ticks and added items. The pure rules
(checklist, data sheet, instructions) read only this, so they can be tested without a database."""

from dataclasses import asdict, dataclass, field
from typing import Any

from app.os.packs.config import PackConfig
from app.os.packs.funds import FundsResult

ENTERED_PREFIX = "entered."  # profile key of a value the student typed: "entered.<data-sheet field key>"


@dataclass(frozen=True)
class DocState:
    status: str  # the os_documents status: uploaded, reading, read, needs_student, confirmed, failed
    document_id: int
    sha256: str | None


@dataclass(frozen=True)
class ProfileValue:
    value: Any
    source: str  # "document" or "entered"
    document_id: int | None


@dataclass(frozen=True)
class PackInputs:
    cfg: PackConfig
    documents: dict[str, DocState]  # by document type: the student's live document of that type
    statements: dict[str, str | None]  # "sop", "cv", and "sop:<programme>" when needed -> approved SHA-256 or None
    profile: dict[str, ProfileValue]
    facts: dict[str, Any]  # fact name -> knowledge Fact (value, url, status) for this programme and intake
    constants: dict[str, Any]  # playbook constants (value, citations, estimate)
    citations: dict[str, str]  # playbook citation source id -> URL
    ticked: set[str] = field(default_factory=set)
    added: list[tuple[str, str]] = field(default_factory=list)  # (item key, label) the student added
    required_override: list[str] | None = None  # the confirmed required_documents fact, if any
    funds: FundsResult | None = None  # the visa file only (Slice 6b S6b-D4)
    kind: str = "pack"  # "pack" or "visa" (S6b-D2)
    programme_ref: str | None = None  # the visa file only: the chosen programme is part of what it is built from


def _fact_names(cfg: PackConfig) -> list[str]:
    """Every fact the pack reads: the route and the required documents, and those its instructions and fees name."""
    import re

    names = {"application_route", "required_documents"}
    for steps in cfg.instructions.values():
        for s in steps:
            names |= set(re.findall(r"\{([a-z][a-z0-9_]*)\}", s.text))
            if s.source.startswith("fact:"):
                names.add(s.source[5:])
    names |= {f.source[5:] for f in cfg.fees if f.source.startswith("fact:")}
    return sorted(names)


def load_inputs(engine, tenant_id: str, knowledge, book, cfg: PackConfig, statement_cfg, student_ref: str,
                programme_ref: str, year: int, kind: str = "pack") -> PackInputs:
    """This student's material for one programme's pack. Only their own rows are read (every store filters by
    tenant and student). `statement_cfg` may be None (no statements for the route: no programme SOP is needed).

    A visa file (`kind="visa"`, Slice 6b) uses the base SOP and CV only, its own checklist (the programme's
    required-documents fact is the university's list, not the embassy's), its own ticks, and the funds."""
    from app.os.documents.store import DocumentStore, ProfileStore
    from app.os.packs.funds import required_funds
    from app.os.packs.store import PackItemStore
    from app.os.packs.visa import VISA_ITEMS, VisaChoiceStore
    from app.os.statements.approval import approved_shas, needed_artifacts

    visa = kind == "visa"
    if visa:
        statement_cfg = None

    documents: dict[str, DocState] = {}
    for d in DocumentStore(engine, tenant_id).list_for(student_ref):  # oldest first: the newest of a type wins
        documents[d.doc_type] = DocState(d.status, d.id, d.sha256)
    shas = approved_shas(engine, tenant_id, student_ref)
    statements: dict[str, str | None] = {"sop": shas.get(("sop", None)), "cv": shas.get(("cv", None))}
    if statement_cfg is not None:
        for statement_kind, prog in needed_artifacts(engine, tenant_id, knowledge, student_ref, programme_ref, year,
                                                     statement_cfg):
            if prog is not None:
                statements[f"{statement_kind}:{prog}"] = shas.get((statement_kind, prog))
    profile = {v["key"]: ProfileValue(v["value"], v.get("source", "document"), v["source_document_id"])
               for v in ProfileStore(engine, tenant_id).all(student_ref)}
    found = knowledge.programme_facts([programme_ref], _fact_names(cfg), year)
    facts = {name: f for (_, name), f in found.items()}
    required = facts.get("required_documents")
    override = None
    if not visa and required is not None and required.status == "confirmed" and isinstance(required.value, list):
        override = [k for k in required.value if k != "other"]
    funds = None
    if visa and cfg.funds is not None:
        choice = VisaChoiceStore(engine, tenant_id).get(student_ref)
        fact = knowledge.route_facts(cfg.route_key, [cfg.funds.fact], year).get(cfg.funds.fact)
        funds = required_funds(cfg.funds, fact, choice.reduction if choice else 0)
    items, items_key = PackItemStore(engine, tenant_id), VISA_ITEMS if visa else programme_ref
    return PackInputs(
        cfg=cfg, documents=documents, statements=statements, profile=profile, facts=facts,
        constants=dict(book.constants),
        citations={c.source: str(c.url) for t in book.tasks for c in t.citations}
        | {c.source: str(c.url) for k in book.constants.values() for c in k.citations},
        ticked=items.ticked(student_ref, items_key), added=items.added(student_ref, items_key),
        required_override=override, funds=funds, kind=kind, programme_ref=programme_ref if visa else None)


def inputs_sha(inp: PackInputs) -> str:
    """A fingerprint of everything the pack is built from: a change to any input gives a new build (and version)."""
    import hashlib
    import json

    body = {
        "config": [inp.cfg.route_key, inp.cfg.version],
        "documents": {k: [d.status, d.document_id, d.sha256] for k, d in inp.documents.items()},
        "statements": inp.statements,
        "profile": {k: [v.value, v.source, v.document_id] for k, v in inp.profile.items()},
        "facts": {k: [f.value, f.status, f.url] for k, f in inp.facts.items()},
        "constants": {k: c.value for k, c in inp.constants.items()},
        # a tick after approving (paid the fee) is not part of what is approved: it never makes a new version
        "ticked": sorted(inp.ticked - inp.cfg.after_approval_keys()),
        "added": inp.added, "override": inp.required_override,
    }
    if inp.kind != "pack":  # only when set, so a pack's fingerprint is unchanged from Slice 6a
        body["kind"], body["programme"] = inp.kind, inp.programme_ref
    if inp.funds is not None:
        body["funds"] = asdict(inp.funds)
    blob = json.dumps(body, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def show(value: Any) -> str:
    """A fact or constant value as one short line (no country-specific formatting)."""
    if isinstance(value, dict) and "date" in value:
        return str(value["date"])
    if isinstance(value, list):
        return ", ".join(show(v) for v in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, dict):
        return ", ".join(f"{k.replace('_', ' ')} {show(v)}" for k, v in value.items() if v is not None)
    return str(value)
