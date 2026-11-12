"""Connection parts (P1-D9): a part is on only when its flag is on and the OS `counsellor` module is on."""

from app.config import config

PARTS: tuple[str, ...] = (
    "CONNECT_HANDOFF",
    "CONNECT_ROADMAP_FROM_PLANVIEW",
    "CONNECT_CHECKINS_FROM_PLANVIEW",
    "CONNECT_STUDENT_FACTS",
    "CONNECT_ONE_UPLOAD",
    "CONNECT_MY_PLAN",
    "CONNECT_MERIT_ANSWERS",
)


def part_on(name: str) -> bool:
    if name not in PARTS:
        raise KeyError(name)
    if not getattr(config, name):
        return False
    from app import pai_os_bridge  # lazy: keeps this module import-light

    return pai_os_bridge.counsellor_module_on()
