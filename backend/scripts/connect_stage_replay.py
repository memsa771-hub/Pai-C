"""Stage A-I replay with the connection off and on (P1-T10 Task C2; R-46, R-44, R-45).

For each stage A-I of the Counsellor workflow (docs/counselor/PAI_C_WORKFLOW_LOCK_V1.md) the workspace state of that
stage is seeded with the existing fixture builders, then one or two recorded Counsellor turns run through the same
pipeline as `scripts/eval_counselor_deep.py --offline` (that script is reused unchanged: this file subclasses and
patches, never edits it). Every model call's input messages and recorded output are captured, with the reply, the
action and the screens the stage shows. The run is done twice:

  off  - the OS `counsellor` module off and every CONNECT_* flag off (today's product);
  on   - the module on (a real PAI OS on Postgres behind the ports) and every CONNECT_* flag on.

`normalise` masks ids, times and fact values (the `value` of Vault entries and document facts), and turns screens into
key/type trees. `diff` reports every other difference. No model call, no network, no API key. Fictional students only
(tests/fixtures/connect_replay/*.json).

CLI (from backend/, needs OS_TEST_DATABASE_URL for the OS side):
  env -u PAI_API_KEY python -m scripts.connect_stage_replay --out ../docs/connect/replays/p1/stage-a-i
"""

import asyncio
import itertools
import json
import os
import re
import subprocess
import sys
import uuid
import zlib
from contextlib import contextmanager, ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import config  # noqa: E402
from scripts import eval_counselor_deep as deep  # noqa: E402
from scripts.counselor_eval_support import StudentSession  # noqa: E402
from scripts.eval.cost import UsageLedger, load_prices  # noqa: E402

FIXTURES = BACKEND / "tests" / "fixtures" / "connect_replay"
STAGES = "ABCDEFGHI"
STUDENTS = ("germany_master", "pk_bs")
FLAGS = ("CONNECT_HANDOFF", "CONNECT_ROADMAP_FROM_PLANVIEW", "CONNECT_CHECKINS_FROM_PLANVIEW",
         "CONNECT_STUDENT_FACTS", "CONNECT_ONE_UPLOAD", "CONNECT_MY_PLAN", "CONNECT_CONSENT_DRAFT")
TOKEN = {"X-Workspace-Token": "synthetic-test-only"}

UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
ISO = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?")
EPOCH_MS = re.compile(r"(?<!\d)1[6-9]\d{11}(?!\d)")


def load_student(student_id: str) -> dict:
    return json.loads((FIXTURES / f"{student_id}.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- capture of every model call's input


class InputRecorder(deep.RecordedModels):
    """Recorded outputs as before, and every call's input kept for the comparison."""

    calls: list[dict] = []

    @staticmethod
    def _keep(name: str, kwargs: dict, output: str) -> None:
        shown = {k: v for k, v in kwargs.items() if k not in ("api_key", "base_url")}
        InputRecorder.calls.append({"phase": name, "input": json.loads(json.dumps(shown, default=str)),
                                    "output": output})

    async def counselor(self, **kwargs):
        out = await super().counselor(**kwargs)
        self._keep("counselor", kwargs, out)
        return out

    async def analyst(self, **kwargs):
        out = await super().analyst(**kwargs)
        self._keep("analyst", kwargs, out)
        return out

    async def sensitive(self, **kwargs):
        out = await super().sensitive(**kwargs)
        self._keep("sensitive", kwargs, out)
        return out

    async def memory(self, **kwargs):
        out = await super().memory(**kwargs)
        self._keep("memory_extractor", kwargs, out)
        return out


# ---------------------------------------------------------------- seeding one stage


def seed_stage(student, spec: dict, mode: str, out: dict, os_world=None, level_patch=None) -> None:
    """Put the workspace in the state of the stage, with the builders the unit tests use. `out['screens']` collects the
    answers of the HTTP calls made while seeding (the choose response)."""
    from app.journey import JourneyService
    from app.memory.vault import VaultService
    from app.pai_c.journey_sync import sync_counselor_stage
    from tests.counselor_fixtures import prepare
    from tests.test_roadmap_engine import add_education, add_path, field_title, fsc

    seed = spec["seed"]
    if seed.get("fresh"):
        return
    with student.factory() as db:
        prepare(student, db, ready=bool(seed.get("mirror_ready")))
        for key, value in seed.get("vault", []):
            VaultService(db).apply_fact(student.workspace_id, key, value, "user_explicit")
        db.commit()
        if seed.get("education"):
            e = seed["education"]
            add_education(student, db, fsc(e["group"], e["percent"]))
        for key in seed.get("paths", []):
            add_path(student, db, field_title(key), key)
        service = JourneyService(db)
        journey = service.ensure_counselor(student.workspace_id)
        if seed.get("mirror_ready"):
            service.mark_mirror_ready(student.workspace_id)
        sync_counselor_stage(db, student.workspace_id, reason="student")
        db.commit()
    if seed.get("choose"):
        choose = seed["choose"]
        client = _client(student)
        params = {"network": student.workspace_id}
        with level_patch(choose["level"]) if level_patch else ExitStack():
            if mode == "on":
                body = {"field_key": choose["field"], "details": {
                    "destination": choose["destination"], "places": choose["places"], "intake": choose["intake"],
                    "consent": True, "consent_version": "1"}}
            else:
                body = {"field_key": choose["field"]}
            response = client.post("/v1/roadmap/choose", params=params, headers=TOKEN, json=body)
            out["screens"]["choose_response"] = _data(response)
            if mode == "on" and os_world is not None:
                os_world.settle(student)


def _client(student):
    from tests.counselor_fixtures import client_for

    return client_for(student)


def _data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def collect_screens(student, spec: dict, out: dict) -> None:
    """The screens the Counsellor serves at this stage (existing endpoints only: a new endpoint is not compared)."""
    seed = spec["seed"]
    if seed.get("fresh"):
        return
    client = _client(student)
    params = {"network": student.workspace_id}
    if seed.get("education"):
        out["screens"]["roadmap"] = _data(client.get("/v1/roadmap", params=params, headers=TOKEN))
    if seed.get("choose"):
        out["screens"]["decision_record"] = _data(client.get("/v1/decision-records/current", params=params,
                                                             headers=TOKEN))
    with student.factory() as db:
        from app.models import StudentJourney
        from sqlalchemy import select
        journey = db.scalar(select(StudentJourney).where(StudentJourney.workspace_id == student.workspace_id))
        out["screens"]["journey"] = {"stage": journey.current_stage if journey else None,
                                     "has_goal": bool(journey and journey.active_goal)}
        if seed.get("mirror_ready"):
            from app.pai_c.mirror import MirrorEngine
            card = MirrorEngine(db).build(student.workspace_id)
            out["screens"]["mirror"] = {k: card[k] for k in ("header", "unknowns", "text", "ready", "version")}


def counts(student) -> dict:
    """Chat-bearing rows after the stage (R-45): messages, events and turn decisions."""
    from sqlalchemy import func, select
    from app.models import CounselorTurnDecision, EventRecord, NotificationRecord

    with student.factory() as db:
        return {
            "events": db.scalar(select(func.count()).select_from(EventRecord)),
            "turn_decisions": db.scalar(select(func.count()).select_from(CounselorTurnDecision)),
            "notifications": db.scalar(select(func.count()).select_from(NotificationRecord)),
        }


def session_class(spec: dict, mode: str, out: dict, os_world=None, level_patch=None):
    class SeededSession(StudentSession):
        def __enter__(self):
            super().__enter__()
            seed_stage(self, spec, mode, out, os_world, level_patch)
            return self

        def __exit__(self, *args):
            try:
                collect_screens(self, spec, out)
                out["counts"] = counts(self)
                if mode == "on" and os_world is not None:
                    os_world.settle(self)
                    out["counts_after_os"] = counts(self)
            finally:
                from app.database import get_db
                from app.main import app
                app.dependency_overrides.pop(get_db, None)
                super().__exit__(*args)

    return SeededSession


# ---------------------------------------------------------------- running a stage


def persona_of(student_fixture: dict, stage: str) -> dict:
    spec = student_fixture["stages"][stage]
    return {"id": f"{student_fixture['id']}-{stage}", "name": student_fixture["name"],
            "surface": spec["turns"][0]["student"], "hidden_truths": [], "family": "", "constraints": "",
            "style": "English", "adversarial": [], "recorded_turns": spec["turns"], "recorded_grader": None}


def run_stage(student_fixture: dict, stage: str, mode: str, os_world=None, level_patch=None) -> dict:
    """One stage, one mode. In `on` mode `os_world` is the live PAI OS (see tests/os/test_connect_stage_replay.py)."""
    spec = student_fixture["stages"][stage]
    out: dict = {"stage": stage, "screens": {}}
    InputRecorder.calls = []
    ledger = UsageLedger(load_prices(deep.PRICES), None)
    # Ids are counted, not random: the recall of Vault facts breaks ties by id (app/memory/retriever.py `order_by(model.id)`),
    # so random ids would reorder the same facts between two runs of the same code. Both modes count from the same start, which differs per student so two students never share an OS student ref (the leading letters keep SQLite from reading the id as a number).
    counter = itertools.count(1 + zlib.crc32(student_fixture["id"].encode()) % 1000 * 1_000_000)
    with patch.object(deep, "StudentSession", session_class(spec, mode, out, os_world, level_patch)), \
            patch.object(deep, "RecordedModels", InputRecorder), \
            patch.object(uuid, "uuid4", lambda: uuid.UUID(int=(0xabcdef << 100) + next(counter))):
        result = asyncio.run(deep.evaluate_persona(persona_of(student_fixture, stage), ledger, live=False,
                                                   max_turns=len(spec["turns"])))
    assert result["status"] == "complete", (stage, result["status"], result.get("stop_reason"))
    out["calls"] = list(InputRecorder.calls)
    out["turns"] = [{"student": t["student"], "reply": t["reply"], "action": t["action"],
                     "action_status": t["action_status"]} for t in result["turns"]]
    out["notebook"] = result.get("notebook")
    return out


@contextmanager
def connection(mode: str):
    """Off: the module off (no ports) and every CONNECT_* flag off. On: every flag on (the caller has switched the
    module on and configured the ports)."""
    from app.routers import roadmap  # noqa: F401 - imported so the patch target exists

    with ExitStack() as stack:
        for name in FLAGS:
            stack.enter_context(patch.object(config, name, mode == "on", create=True))
        stack.enter_context(patch("app.routers.roadmap.resolve_human", lambda db, ws, auth: SimpleNamespace()))
        yield


def run(mode: str, student_id: str, os_world=None, level_patch=None, stages: str = STAGES) -> dict:
    fixture = load_student(student_id)
    with connection(mode):
        return {stage: run_stage(fixture, stage, mode, os_world, level_patch) for stage in stages}


# ---------------------------------------------------------------- normalising and comparing


def _mask_text(text: str) -> str:
    text = UUID.sub("<id>", text)
    text = ISO.sub("<time>", text)
    return EPOCH_MS.sub("<time>", text)


FACT_SHAPE = ({"field_key", "value"}, {"key", "value", "evidence"})


OPAQUE = frozenset({"values", "evidence", "rule", "time"})  # a step's free-form payloads: the keys count, not their inner shape


def normalise(obj, *, structural: bool = False):
    """Mask ids, times and fact values. A fact is a dict with a `value` and either a `field_key` (Vault entry,
    document fact) or `key` and `evidence` (notebook entry): only its `value` is masked, never a key or a shape.
    With `structural` (screens) every leaf becomes its type name, so only keys and types are compared."""
    if isinstance(obj, dict):
        fact = any(shape <= set(obj) for shape in FACT_SHAPE)
        return {k: ("<value>" if fact and k == "value" else
                    ("null" if v is None else "payload") if structural and k in OPAQUE else
                    normalise(v, structural=structural))
                for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        items = [normalise(v, structural=structural) for v in obj]
        if structural:  # a list is the union of its elements' shapes (and its emptiness)
            merged: dict = {}
            for item in items:
                merged = _merge(merged, item)
            return [merged] if items else []
        return items
    if structural:
        return "null" if obj is None else type(obj).__name__
    if isinstance(obj, str):
        return _mask_text(obj)
    if isinstance(obj, int) and not isinstance(obj, bool) and EPOCH_MS.fullmatch(str(obj)):
        return "<time>"
    return obj


def _merge(a, b):
    """Union of two shapes: dicts join their keys, unequal leaves become the sorted set joined with `|`."""
    if isinstance(a, dict) and isinstance(b, dict):
        return {k: (_merge(a[k], b[k]) if k in a and k in b else a.get(k, b.get(k))) for k in sorted(set(a) | set(b))}
    if isinstance(a, list) and isinstance(b, list):
        return [_merge(a[0] if a else {}, b[0] if b else {})] if a or b else []
    if a == b or a == {}:
        return b if a == {} else a
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):  # a shape beside a null: keep the shape
        return a if isinstance(a, (dict, list)) else b
    left = set(str(a).split("|")) if isinstance(a, str) else {str(a)}
    right = set(str(b).split("|")) if isinstance(b, str) else {str(b)}
    return "|".join(sorted(left | right))


def _calls(stage: dict) -> list[dict]:
    return normalise(stage["calls"])


def _tree_diff(off, on, path: str, adds: list[str], bad: list[str]) -> None:
    """Screens: `on` may add keys (recorded in `adds`); a removed key or a changed type is a difference. A null is
    compatible with any shape (the key is there, the value is empty)."""
    if off == "null" or on == "null":
        return
    if isinstance(off, dict) and isinstance(on, dict):
        for key in sorted(set(off) | set(on)):
            if key not in on:
                bad.append(f"{path}.{key}: removed with the connection on")
            elif key not in off:
                adds.append(f"{path}.{key}")
            else:
                _tree_diff(off[key], on[key], f"{path}.{key}", adds, bad)
    elif isinstance(off, list) and isinstance(on, list):
        if off and on:
            _tree_diff(off[0], on[0], f"{path}[]", adds, bad)
        elif bool(off) != bool(on):
            bad.append(f"{path}: list is {'empty' if not on else 'not empty'} with the connection on")
    elif off != on:
        # a leaf: `on` may only narrow to the types `off` had, plus null (a field the plan has no value for)
        if not (isinstance(off, str) and isinstance(on, str)
                and set(on.split("|")) <= set(off.split("|")) | {"null"}):
            bad.append(f"{path}: {off} -> {on}")


def diff(off: dict, on: dict) -> dict:
    """{"differences": [...], "screen_additions": [...]}. Model inputs, outputs, replies, actions, the notebook and
    the chat-bearing row counts must be equal after masking; screens may only add keys."""
    bad: list[str] = []
    adds: list[str] = []
    for stage in sorted(set(off) | set(on)):
        a, b = off[stage], on[stage]
        ca, cb = _calls(a), _calls(b)
        if len(ca) != len(cb):
            bad.append(f"{stage}: {len(ca)} model calls off, {len(cb)} on")
        for index, (x, y) in enumerate(zip(ca, cb)):
            if x != y:
                bad.append(f"{stage}: model call {index} ({x['phase']}) differs: {_first_difference(x, y)}")
        for key in ("turns", "notebook"):
            if normalise(a[key]) != normalise(b[key]):
                bad.append(f"{stage}: {key} differ")
        chat = lambda c: {k: v for k, v in c.items() if k != "notifications"}  # noqa: E731 - a bell notice is allowed (R-45)
        if chat(a["counts"]) != chat(b["counts"]):
            bad.append(f"{stage}: chat rows differ {chat(a['counts'])} vs {chat(b['counts'])}")
        if b.get("counts_after_os") and chat(b["counts_after_os"]) != chat(a["counts"]):
            bad.append(f"{stage}: the OS side changed the chat rows {chat(a['counts'])} -> {chat(b['counts_after_os'])}")
        _tree_diff(normalise(a["screens"], structural=True), normalise(b["screens"], structural=True),
                   f"{stage}.screens", adds, bad)
    return {"differences": bad, "screen_additions": adds}


def _first_difference(x, y, path: str = "") -> str:
    if isinstance(x, dict) and isinstance(y, dict):
        for key in sorted(set(x) | set(y)):
            if key not in x or key not in y:
                return f"{path}.{key} only on one side"
            if x[key] != y[key]:
                return _first_difference(x[key], y[key], f"{path}.{key}")
    if isinstance(x, list) and isinstance(y, list):
        if len(x) != len(y):
            return f"{path} has {len(x)} vs {len(y)} items"
        for i, (p, q) in enumerate(zip(x, y)):
            if p != q:
                return _first_difference(p, q, f"{path}[{i}]")
    return f"{path}: {str(x)[:80]!r} vs {str(y)[:80]!r}"


# ---------------------------------------------------------------- report


def report_md(results: dict) -> str:
    lines = ["# Stage A-I replay, connection off and on (P1-T10 Task C2)", "",
             "Recorded model outputs, no network, no API key, fictional students. For each stage the workspace state of "
             "that stage is seeded, one or two recorded Counsellor turns run, and every model call's input and output "
             "is compared after masking ids, times and fact values. Screens are compared by shape (keys and types).", "",
             "| Student | Stage | Model calls | Replies and inputs identical | Differences | Screen keys the connection adds |",
             "| --- | --- | ---: | --- | ---: | --- |"]
    for student_id, data in results.items():
        for stage in STAGES:
            n = len(data["off"][stage]["calls"])
            stage_diff = diff({stage: data["off"][stage]}, {stage: data["on"][stage]})
            adds = ", ".join(a.split(".screens.", 1)[-1] for a in stage_diff["screen_additions"]) or "none"
            lines.append(f"| {student_id} | {stage} | {n} | "
                         f"{'yes' if not stage_diff['differences'] else 'NO'} | {len(stage_diff['differences'])} | {adds} |")
    lines += ["", "## What the replay cannot show", "",
              "- The model outputs are recorded and hand-written: a reply difference can only come from a change in what "
              "the Counsellor reads or does, and the model inputs are compared byte for byte to catch that. A real model "
              "may still answer differently to the same input; only a live run shows that (Task C3).",
              "- One or two turns per stage, on seeded state. It is not one conversation walking A to I.",
              "- Stage I is screens, as master spec section 10 says: the replay checks the choose answer, the decision "
              "record and the journey, and one J turn after the choice.",
              "- Only existing endpoints are compared. The new endpoints (choice options, places, my plan) exist only "
              "with the connection on and are covered by their own tests.", ""]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    out = None
    if "--out" in argv:
        out = Path(argv[argv.index("--out") + 1]).resolve()
    if not os.environ.get("OS_TEST_DATABASE_URL"):
        print("OS_TEST_DATABASE_URL is required for the OS side of the `on` run", file=sys.stderr)
        return 2
    env = {**os.environ, "CONNECT_REPLAY_OUT": str(out) if out else ""}
    return subprocess.call([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                            "tests/os/test_connect_stage_replay.py", "-k", "write_report"], cwd=BACKEND, env=env)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
