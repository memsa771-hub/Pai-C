"""Set-up for the local Docker test stack of branch pai-merge (docker-compose.yml service `os-setup`).

Runs once per `docker compose up`, after `alembic upgrade heads`, before the API and the OS worker start. It does on
the local database what the rehearsal driver's `_clean` and `_answers` do, but never deletes anything:

1. loads the programme registry, the seeded facts and the fictional semester starts (insert or update; safe to repeat);
2. writes the offline AI answers folder (OS_OFFLINE_ANSWERS_DIR): the fixed answer files, plus one documents answer
   per sample document in the rehearsal fixtures and in SAMPLES_DIR (docs/local-test/sample-documents). The key is
   the SHA-256 of the first image the documents reader sees, computed here with this image's Pillow, so it matches
   what the worker computes for the same file uploaded with the same document type;
3. sets the rehearsal clock to 1 Dec 2026 on a fresh database (no clock and no plan yet); later runs leave it alone.

    python -m tests.os.rehearsal.local_stack          (from backend/, with the OS_* settings of the stack)

Local test only: OS_REHEARSAL=on and OS_MODEL_MODE=offline are required. Fictional data only.
"""

import os
import shutil
import sys
from datetime import date
from pathlib import Path

import yaml

from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
from app.os.knowledge.programmes import PROGRAMME_SEED, ProgrammeStore, load_programme_seed
from app.os.rehearsal.store import ClockStore
from app.os.settings import load_settings
from app.os.db import make_engine
from tests.os.rehearsal import make_answers

HERE = Path(__file__).resolve().parent
SEMESTER_STARTS = HERE / "semester_starts.yaml"
SAMPLES_DIR = Path(os.environ.get("LOCAL_TEST_SAMPLES_DIR", "/samples"))
START = date(2026, 12, 1)


def write_answers(dest: Path) -> int:
    """Fresh answers in `dest`; returns the number of documents with an answer."""
    dest.mkdir(parents=True, exist_ok=True)
    for f in make_answers.ANSWERS.glob("*.yaml"):
        if f.name != "documents.yaml":
            shutil.copy(f, dest / f.name)
    docs = make_answers.answers(make_answers.SAMPLES)
    if (SAMPLES_DIR / make_answers.KEY_NAME).is_file():
        docs.update(make_answers.answers(SAMPLES_DIR))
    (dest / "documents.yaml").write_text(
        make_answers.HEADER + yaml.safe_dump(docs, sort_keys=True, allow_unicode=True), encoding="utf-8")
    return len(docs)


def main() -> int:
    settings = load_settings()
    if not settings.rehearsal or settings.model_mode != "offline":
        print("local_stack: refusing to run without OS_REHEARSAL=on and OS_MODEL_MODE=offline", file=sys.stderr)
        return 2
    engine = make_engine(settings)
    tenant = settings.tenant_id
    n = load_programme_seed(PROGRAMME_SEED, ProgrammeStore(engine, tenant))
    kb = SqlKnowledge(engine, tenant)
    facts = load_seed(SEED_DIR / "germany_ws2027.yaml", kb) + load_seed(SEMESTER_STARTS, kb)
    print(f"local_stack: {n} programmes, {facts} seeded facts (existing facts kept)")
    count = write_answers(Path(settings.offline_answers_dir))
    print(f"local_stack: offline answers for {count} sample documents in {settings.offline_answers_dir}")
    offset = ClockStore(engine, tenant).start(START)
    if offset is None:
        print("local_stack: rehearsal clock already set (or a plan exists): left as it is")
    else:
        print(f"local_stack: rehearsal clock set to {START.isoformat()}")
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
