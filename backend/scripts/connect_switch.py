"""Owner switch for the OS `counsellor` module: `python scripts/connect_switch.py status|on|off`.
Prints the module state and each connection flag (never a secret)."""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import Engine  # noqa: E402

from app.config import config  # noqa: E402
from app.os.adapters.counsellor import manifest  # noqa: E402
from app.pai_c.connect.flags import PARTS  # noqa: E402

TENANT = "pai"
COMMANDS = ("status", "on", "off")


def main(argv: list[str], engine: Engine | None = None) -> int:
    if len(argv) != 1 or argv[0] not in COMMANDS:
        print("usage: connect_switch.py status|on|off", file=sys.stderr)
        return 2
    own = engine is None
    if own:
        from app.os.db import make_engine
        from app.os.settings import load_settings

        engine = make_engine(load_settings())
    try:
        if argv[0] != "status":
            manifest.set_enabled(engine, TENANT, argv[0] == "on")
        print(f"counsellor module: {'on' if manifest.is_enabled(engine, TENANT) else 'off'}")
        for name in PARTS:
            print(f"{name}: {'on' if getattr(config, name) else 'off'}")
    finally:
        if own:
            engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
