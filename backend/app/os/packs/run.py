"""The `os.pack` DBOS workflow (Slice 6a spec S6a-D7, D10): build one programme's pack.

Steps: `start` (the pack artifact, status `building`) -> `load` (what to render, no bytes) -> `render:<item>` (one
step per file: read the source, convert or render it, store it once per SHA-256, return only its reference) ->
`store` (the manifest; a new version only if its SHA-256 changed) . Step retries are the only retries (invariant 7);
every write is idempotent (invariant 8): files by SHA-256, versions by manifest SHA-256. No file bytes go into a step
output (the Slice 3 rule). The workflow ID holds the inputs' SHA-256, so the same inputs are built once.
"""

import io
from collections.abc import Mapping
from dataclasses import asdict

from dbos import DBOS, DBOSClient, EnqueueOptions
from pypdf import PdfReader
from sqlalchemy import Engine

from app.os.artifacts.store import ArtifactStore
from app.os.documents.intake import check_upload
from app.os.documents.store import DocumentStore
from app.os.packs import render
from app.os.packs.checklist import checklist, complete
from app.os.packs.config import PackConfig
from app.os.packs.datasheet import data_sheet
from app.os.packs.inputs import load_inputs
from app.os.packs.instructions import fees, instructions
from app.os.packs.manifest import FileRef, build_manifest
from app.os.packs.store import PackFileStore
from app.os.settings import OsSettings

PACK_WORKFLOW = "os.pack"
PACK_KIND = "pack"
SHEET = "data_sheet"


def pack_workflow_id(tenant_id: str, student_ref: str, programme_ref: str, inputs_sha: str, version: int = 0,
                     attempt: int = 0) -> str:
    """The same inputs on top of the same current version are one build (invariant 8). The version is in the ID so
    inputs that change and change back (A -> B -> A) build again; `attempt` grows only when the student rebuilds after
    a failure (final review C1, C2)."""
    wid = f"pack:{tenant_id}:{student_ref}:{programme_ref}:{inputs_sha[:16]}:v{version}"
    return f"{wid}:r{attempt}" if attempt else wid


def latest_attempt(client: DBOSClient, tenant_id: str, student_ref: str, programme_ref: str, inputs_sha: str,
                   version: int) -> int:
    """The highest attempt already started for these inputs and version (0 if none or only the first)."""
    base = pack_workflow_id(tenant_id, student_ref, programme_ref, inputs_sha, version)
    ids = [w.workflow_id for w in client.list_workflows(workflow_id_prefix=base, load_input=False, load_output=False)]
    return max((int(i.rsplit(":r", 1)[1]) for i in ids if ":r" in i[len(base):]), default=0)


def enqueue_pack(client: DBOSClient, tenant_id: str, student_ref: str, programme_ref: str, route_key: str,
                 year: int, inputs_sha: str, version: int = 0, attempt: int = 0) -> str:
    from app.os.runner.workflow import APP_VERSION, QUEUE_NAME  # imported here: the runner imports packs

    wid = pack_workflow_id(tenant_id, student_ref, programme_ref, inputs_sha, version, attempt)
    options: EnqueueOptions = {"queue_name": QUEUE_NAME, "workflow_name": PACK_WORKFLOW, "workflow_id": wid,
                               "app_version": APP_VERSION}
    client.enqueue(options, student_ref, programme_ref, route_key, year)
    return wid


def _newest_books(books) -> dict:
    newest = {}
    for (key, version), b in books.items():
        if key not in newest or version > newest[key].version:
            newest[key] = b
    return newest


def register_packs(engine: Engine, settings: OsSettings, knowledge, books, configs: Mapping[str, PackConfig],
                   statement_configs: Mapping) -> None:
    """Registers os.pack and its steps. Must run before DBOS.launch(). No model key is needed: there is no AI."""
    from app.os.runner.workflow import STEP_CONFIG  # imported here: the runner imports packs

    tenant = settings.tenant_id
    arts, files, docs = ArtifactStore(engine, tenant), PackFileStore(engine, tenant), DocumentStore(engine, tenant)
    newest = _newest_books(books)

    def inputs(student: str, programme: str, route_key: str, year: int):
        return load_inputs(engine, tenant, knowledge, newest[route_key], configs[route_key],
                           statement_configs.get(route_key), student, programme, year)

    def start(student: str, programme: str) -> int:
        art = arts.get_or_create(student, PACK_KIND, programme)
        arts.set_status(art.id, "building")
        return art.id

    def load(student: str, programme: str, route_key: str, year: int) -> list[dict]:
        """The files to render: the data sheet, each confirmed document and each approved statement on the list."""
        inp = inputs(student, programme, route_key, year)
        todo = [{"key": SHEET, "kind": SHEET, "label": "Data sheet"}]
        by_key = {i.key: i for i in inp.cfg.checklist}
        for r in checklist(inp, programme):
            item = by_key.get(r.key)
            if item is None:
                continue  # an item the student added: they upload it in the portal themselves
            if item.kind == "document" and r.document_id is not None and inp.documents[item.ref].status == "confirmed":
                todo.append({"key": item.key, "kind": "document", "label": item.label, "document_id": r.document_id})
            elif item.kind == "statement" and r.state == "ready":
                own = f"{item.ref}:{programme}" in inp.statements
                todo.append({"key": item.key, "kind": "statement", "label": item.label, "ref": item.ref,
                             "programme": programme if own else None})
        return todo

    def render_file(student: str, programme: str, route_key: str, year: int, spec: dict) -> dict:
        cfg = configs[route_key]
        if spec["kind"] == SHEET:
            data = render.render_sheet(data_sheet(inputs(student, programme, route_key, year)),
                                       f"Data sheet: {programme}")
            pages = len(PdfReader(io.BytesIO(data)).pages)
        elif spec["kind"] == "statement":
            art = arts.get_or_create(student, spec["ref"], spec["programme"])
            ap = arts.approval(art.id)
            if ap is None:
                return {"unfixable": f"approve your {spec['ref'].upper()} first"}
            data = render.render_statement(arts.version(art.id, ap.version).text, spec["label"])
            pages = len(PdfReader(io.BytesIO(data)).pages)
        else:
            original = docs.file_bytes(spec["document_id"])
            item = next(i for i in cfg.checklist if i.key == spec["key"])
            got = render.convert_document(original, check_upload("document", original), cfg.format_for(item))
            if isinstance(got, render.Unfixable):
                return {"unfixable": got.reason}
            data, pages = got
        name = render.filename(spec["key"], spec["label"])
        sha = files.put(student, programme, spec["key"], name, "application/pdf", data, pages)
        return asdict(FileRef(sha, name, len(data), pages))

    def store(artifact_id: int, student: str, programme: str, route_key: str, year: int, refs: dict,
              unfixable: dict) -> dict:
        inp = inputs(student, programme, route_key, year)
        results = checklist(inp, programme, unfixable)
        route_value, steps = instructions(inp, programme)
        text, sha = build_manifest(inp, programme, route_value, results, data_sheet(inp), steps, fees(inp),
                                   {k: FileRef(**v) for k, v in refs.items()})
        art = arts.get(artifact_id)
        current = arts.version(artifact_id, art.current_version) if art.current_version else None
        if current is None or current.sha256 != sha:
            current = arts.add_version(artifact_id, text, "system")  # drops any approval (S6a-D7)
        approved = (ap := arts.approval(artifact_id)) is not None and ap.version == current.number
        status = "approved" if approved else "ready" if complete(results) else "incomplete"
        arts.set_status(artifact_id, status)
        return {"status": status, "version": current.number, "sha256": current.sha256}

    def fail(artifact_id: int) -> None:
        arts.set_status(artifact_id, "failed")

    step = lambda name, fn: DBOS.step(name=f"os.pack.{name}", **STEP_CONFIG)(fn)  # noqa: E731
    start_step, load_step, store_step, fail_step = step("start", start), step("load", load), step("store", store), \
        step("fail", fail)
    render_step = step("render", render_file)

    def pack(student: str, programme: str, route_key: str, year: int) -> dict:
        artifact_id = start_step(student, programme)
        try:
            refs, unfixable = {}, {}
            for spec in load_step(student, programme, route_key, year):
                out = render_step(student, programme, route_key, year, spec)
                if "unfixable" in out:
                    unfixable[spec["key"]] = out["unfixable"]
                else:
                    refs[spec["key"]] = out
            return store_step(artifact_id, student, programme, route_key, year, refs, unfixable)
        except Exception:  # noqa: BLE001  (a step's retries are used up: the student sees `failed` and can rebuild)
            fail_step(artifact_id)
            return {"status": "failed"}

    DBOS.workflow(name=PACK_WORKFLOW)(pack)
