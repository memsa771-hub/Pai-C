"""Mounts the OS API on a host app, only when OS_ENABLED.

Services are built at mount time, so an invalid playbook or an unowned task type stops startup
instead of failing every request (spec §4.1, review I7). Research profiles are checked the same way
(Slice 2 spec §4.2). Building them does not connect to the database.
"""

from collections.abc import Callable, Mapping
from pathlib import Path

from fastapi import FastAPI

from app.os.api.deps import current_student_ref, current_student_ref_for_write
from app.os.api.router import build_router
from app.os.api.services import make_services
from app.os.documents.types import TYPES_DIR, load_document_types
from app.os.knowledge.profile import PROFILE_DIR, load_profile_dir
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from app.os.settings import load_settings

PREFIX = "/v1/os"


def mount_os(app: FastAPI, *, env: Mapping[str, str] | None = None,
             student_dependency: Callable[..., str] | None = None,
             student_write_dependency: Callable[..., str] | None = None,
             playbook_dir: Path = PLAYBOOK_DIR, profile_dir: Path = PROFILE_DIR,
             document_types_dir: Path = TYPES_DIR) -> bool:
    try:
        settings = load_settings(env)
    except ValueError:
        return False  # no database configured: the OS stays off
    if not settings.os_enabled:
        return False
    load_profile_dir(profile_dir)  # an invalid research profile stops startup (Slice 2 spec §4.2)
    load_document_types(document_types_dir)  # so does an invalid document type (Slice 3 spec S3-D2)
    services = make_services(settings, playbooks=load_playbook_dir(playbook_dir))
    app.include_router(build_router(lambda: services), prefix=PREFIX)
    if student_dependency is not None:
        app.dependency_overrides[current_student_ref] = student_dependency
    if student_write_dependency is not None:
        app.dependency_overrides[current_student_ref_for_write] = student_write_dependency
    return True
