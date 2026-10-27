"""Writes the offline documents answers (Slice 9a spec §2.3, plan ruling 2): `answers/documents.yaml`.

Each Spike 2 sample document (`tests/os/fixtures/documents/samples`, listed in its `samples_key.yaml`) is run through
the documents pipeline's own functions: `intake.check_upload` and `intake.prepare` (render, EXIF, resize, JPEG), then
`reader.content` with the documents agent's mode (tiles), exactly as `os.document` builds the reader's input. The key
is the SHA-256 of the first image in that input (page 1, or its first tile), which is what the offline documents
model hashes. The values are the sample key's fields plus `detected_type`, so the planted mismatches reach the
cross-checks as in real use.

    python -m tests.os.rehearsal.make_answers

Run it again whenever the samples, the page preparation or the tiling change. Test data only (invariant 12).
"""

import argparse
import hashlib
import sys
from pathlib import Path

import yaml
from pydantic_ai import BinaryContent

from app.os.agents.spec import AGENT_DIR, load_agent_spec
from app.os.documents.intake import check_upload, prepare
from app.os.documents.reader import content
from app.os.documents.types import load_document_types

HERE = Path(__file__).resolve().parent
ANSWERS = HERE / "answers"
SAMPLES = HERE.parent / "fixtures" / "documents" / "samples"
KEY_NAME = "samples_key.yaml"
HEADER = ("# Offline documents answers (Slice 9a spec §2.3). Written by `python -m tests.os.rehearsal.make_answers`;\n"
          "# do not edit. Key: SHA-256 of the first image the documents reader receives (page 1 or its first tile).\n")


def first_image_sha(name: str, data: bytes, doc_type: str, types, mode: str | None) -> str:
    """The SHA-256 of the first image the pipeline sends the documents model for this file."""
    parts = prepare(data, check_upload(name, data))
    image = next(c for c in content(types[doc_type], parts, mode) if isinstance(c, BinaryContent))
    return hashlib.sha256(image.data).hexdigest()


def answers(samples: Path = SAMPLES) -> dict[str, dict]:
    key = yaml.safe_load((samples / KEY_NAME).read_text(encoding="utf-8"))["documents"]
    types, mode = load_document_types(), load_agent_spec(AGENT_DIR / "documents.v1.yaml").mode
    out: dict[str, dict] = {}
    for name, doc in sorted(key.items()):
        sha = first_image_sha(name, (samples / name).read_bytes(), doc["type"], types, mode)
        if sha in out:
            raise ValueError(f"{name} and {out[sha]['file']} reach the model as the same first image")
        values = {f.name: doc["fields"].get(f.name) for f in types[doc["type"]].fields}
        out[sha] = {"file": name, "values": {**values, "detected_type": doc["type"]}}
    return out


def write(out_dir: Path = ANSWERS, samples: Path = SAMPLES) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "documents.yaml"
    path.write_text(HEADER + yaml.safe_dump(answers(samples), sort_keys=True, allow_unicode=True), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ANSWERS)
    ap.add_argument("--samples", type=Path, default=SAMPLES)
    args = ap.parse_args(argv)
    print(f"wrote {write(args.out, args.samples)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
