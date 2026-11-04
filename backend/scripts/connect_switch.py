"""Owner switch for the OS `counsellor` module: `python scripts/connect_switch.py status|on|off`.
Prints the module state and each connection flag (never a secret). `status` shows the flags of this script's own
environment, which can differ from the running backend's. The tenant is OS_TENANT_ID (the OS settings), as at runtime."""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import Engine  # noqa: E402

from app.config import config  # noqa: E402
from app.os.adapters.counsellor import manifest  # noqa: E402
from app.pai_c.connect.flags import PARTS  # noqa: E402

COMMANDS = ("status", "on", "off")


def main(argv: list[str], engine: Engine | None = None, tenant_id: str | None = None) -> int:
    if len(argv) != 1 or argv[0] not in COMMANDS:
        print("usage: connect_switch.py status|on|off", file=sys.stderr)
        return 2
    own = engine is None
    if own or tenant_id is None:
        from app.os.settings import load_settings

        settings = load_settings()
        if tenant_id is None:
            tenant_id = settings.tenant_id
        if own:
            from app.os.db import make_engine

            engine = make_engine(settings)
    try:
        if argv[0] != "status":
            manifest.set_enabled(engine, tenant_id, argv[0] == "on")
        print(f"counsellor module: {'on' if manifest.is_enabled(engine, tenant_id) else 'off'}")
        for name in PARTS:
            print(f"{name}: {'on' if getattr(config, name) else 'off'}")
    finally:
        if own:
            engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
