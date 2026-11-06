"""The My plan gate (P1-T9, D-z2). `GET /v1/os/plan` exists only while the host's My plan part is on. The OS cannot
read host flags, so the host hands in a callable when the OS is mounted (the same shape as `ports.choice_sink`).
Unconfigured, or a host that raises, reads as off: the route then answers like a route that does not exist."""

from collections.abc import Callable

_enabled: Callable[[], bool] | None = None


def configure(enabled: Callable[[], bool] | None) -> None:
    global _enabled
    _enabled = enabled


def enabled() -> bool:
    """True only when the host configured the gate and its part is on."""
    if _enabled is None:
        return False
    try:
        return bool(_enabled())
    except Exception:
        return False
