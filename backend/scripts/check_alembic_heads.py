"""Fail unless the Alembic history has exactly one `os` head and exactly one other head."""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))  # loading migration 101 imports `app`

from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

OS_BRANCH = "os"


def main() -> int:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    script = ScriptDirectory.from_config(config)
    os_heads: list[str] = []
    other_heads: list[str] = []
    for head in script.get_heads():
        lineage = script.iterate_revisions(head, "base")
        on_os_branch = any(OS_BRANCH in (rev.branch_labels or ()) for rev in lineage)
        (os_heads if on_os_branch else other_heads).append(head)
    if len(os_heads) == 1 and len(other_heads) == 1:
        return 0
    print(f"expected one head on the '{OS_BRANCH}' branch and one other head")
    print(f"  {OS_BRANCH} heads: {os_heads}")
    print(f"  other heads: {other_heads}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
