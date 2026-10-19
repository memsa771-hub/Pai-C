"""Mounts the OS API on a host app, only when OS_ENABLED. Services are built on first use, not at import."""

from collections.abc import Callable, Mapping
from functools import cache

from fastapi import FastAPI

from app.os.api.deps import current_student_ref
from app.os.api.router import build_router
from app.os.api.services import Services, make_services
from app.os.settings import load_settings

PREFIX = "/v1/os"


def mount_os(app: FastAPI, *, env: Mapping[str, str] | None = None,
             student_dependency: Callable[..., str] | None = None) -> bool:
    try:
        settings = load_settings(env)
    except ValueError:
        return False  # no database configured: the OS stays off
    if not settings.os_enabled:
        return False

    @cache
    def services() -> Services:
        return make_services(settings)

    app.include_router(build_router(services), prefix=PREFIX)
    if student_dependency is not None:
        app.dependency_overrides[current_student_ref] = student_dependency
    return True
