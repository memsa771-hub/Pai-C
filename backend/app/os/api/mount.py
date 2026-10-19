"""Mounts the OS API on a host app, only when OS_ENABLED.

Services are built at mount time, so an invalid playbook or an unowned task type stops startup
instead of failing every request (spec §4.1, review I7). Building them does not connect to the database.
"""

from collections.abc import Callable, Mapping
from pathlib import Path

from fastapi import FastAPI

from app.os.api.deps import current_student_ref, current_student_ref_for_write
from app.os.api.router import build_router
from app.os.api.services import make_services
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from app.os.settings import load_settings

PREFIX = "/v1/os"


def mount_os(app: FastAPI, *, env: Mapping[str, str] | None = None,
             student_dependency: Callable[..., str] | None = None,
             student_write_dependency: Callable[..., str] | None = None,
             playbook_dir: Path = PLAYBOOK_DIR) -> bool:
    try:
        settings = load_settings(env)
    except ValueError:
        return False  # no database configured: the OS stays off
    if not settings.os_enabled:
        return False
    services = make_services(settings, playbooks=load_playbook_dir(playbook_dir))
    app.include_router(build_router(lambda: services), prefix=PREFIX)
    if student_dependency is not None:
        app.dependency_overrides[current_student_ref] = student_dependency
    if student_write_dependency is not None:
        app.dependency_overrides[current_student_ref_for_write] = student_write_dependency
    return True
