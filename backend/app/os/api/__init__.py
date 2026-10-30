"""The OS HTTP API, mounted by the host app under /v1/os when OS_ENABLED."""

from app.os.api.deps import current_student_ref, current_student_ref_for_write
from app.os.api.mount import PREFIX, mount_os
from app.os.api.router import build_router
from app.os.api.services import Services, make_services

__all__ = [
    "PREFIX", "Services", "build_router", "current_student_ref", "current_student_ref_for_write",
    "make_services", "mount_os",
]
