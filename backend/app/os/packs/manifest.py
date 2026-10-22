"""The pack manifest (Slice 6a spec S6a-D7): one canonical JSON text per pack version, holding everything the student
approves: the checklist results, the data sheet, the instructions, the fees, every file's SHA-256 and the approved
statements' SHA-256s. No timestamps, sorted keys: the same pack gives the same text, so its SHA-256 binds the
approval (invariant 5)."""

import json
from dataclasses import asdict, dataclass

from app.os.artifacts.store import sha256
from app.os.packs.checklist import ItemResult, complete
from app.os.packs.datasheet import SheetRow
from app.os.packs.inputs import PackInputs, inputs_sha
from app.os.packs.instructions import FeeRow, InstructionStep


@dataclass(frozen=True)
class FileRef:
    sha256: str
    filename: str
    size: int
    pages: int


def build_manifest(inp: PackInputs, programme_ref: str, route_value: str | None, results: list[ItemResult],
                   sheet: list[SheetRow], steps: list[InstructionStep], fee_rows: list[FeeRow],
                   files: dict[str, FileRef]) -> tuple[str, str]:
    """(the manifest text, its SHA-256)."""
    body = {
        "programme": programme_ref,
        "inputs_sha256": inputs_sha(inp),  # what it was built from: a newer input means a rebuild is due
        "config": {"route": inp.cfg.route_key, "version": inp.cfg.version},
        "route_value": route_value,
        "complete": complete(results),
        "checklist": [asdict(r) for r in results],
        "data_sheet": [asdict(r) for r in sheet],
        "instructions": [asdict(s) for s in steps],
        "fees": [asdict(f) for f in fee_rows],
        "files": {k: asdict(f) for k, f in sorted(files.items())},
        "statements": {k: v for k, v in sorted(inp.statements.items())},
    }
    if inp.funds is not None:  # the visa file (Slice 6b S6b-D4): what the student must show, and its source
        body["funds"] = asdict(inp.funds)
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return text, sha256(text)
