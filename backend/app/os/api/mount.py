"""Mounts the OS API on a host app, only when OS_ENABLED.

Services are built at mount time, so an invalid playbook or an unowned task type stops startup
instead of failing every request (spec §4.1, review I7). Research profiles are checked the same way
(Slice 2 spec §4.2). Building them does not connect to the database.
"""

from collections.abc import Callable, Mapping
from pathlib import Path

from fastapi import FastAPI

from app.os import ports
from app.os.api.deps import current_student_ref, current_student_ref_for_write
from app.os.api.router import build_router
from app.os.api.services import make_services
from app.os.documents.types import TYPES_DIR, load_document_types
from app.os.eligibility.rules import check_rules, profile_keys
from app.os.packs.config import PACK_DIR, load_checked_pack_configs
from app.os.statements.config import check_config, load_statement_configs
from app.os.knowledge.profile import PROFILE_DIR, load_profile_dir
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from app.os.settings import load_settings

PREFIX = "/v1/os"


def mount_os(app: FastAPI, *, env: Mapping[str, str] | None = None,
             student_dependency: Callable[..., str] | None = None,
             student_write_dependency: Callable[..., str] | None = None,
             playbook_dir: Path = PLAYBOOK_DIR, profile_dir: Path = PROFILE_DIR,
             document_types_dir: Path = TYPES_DIR, pack_dir: Path = PACK_DIR) -> bool:
    try:
        settings = load_settings(env)
    except ValueError:
        return False  # no database configured: the OS stays off
    if not settings.os_enabled:
        return False
    # an invalid research profile stops startup (Slice 2 spec §4.2): loaded below with the playbooks
    types = load_document_types(document_types_dir)  # so does an invalid document type (Slice 3 spec S3-D2)
    profiles = load_profile_dir(profile_dir)
    books = load_playbook_dir(playbook_dir)
    keys = profile_keys(types)
    for book in books.values():  # so do eligibility rules naming an unknown fact or profile key (Slice 4 S4-D2)
        profile = next((p for p in profiles.values() if p.route_key == book.key), None)
        check_rules(book, {f.name for f in profile.fields} if profile else None, keys)
    statement_configs = load_statement_configs()
    for cfg in statement_configs.values():  # so do statement configs (Slice 5 S5-D12)
        check_config(cfg, keys, books)
    pack_configs = load_checked_pack_configs(pack_dir, types, books, profiles)  # so do pack configs (S6a-D12)
    visa_configs = load_checked_pack_configs(pack_dir, types, books, profiles, kind="visa")  # and visa files (S6b-D3)
    services = make_services(settings, playbooks=books, document_types=types, statement_configs=statement_configs,
                             pack_configs=pack_configs, visa_configs=visa_configs)
    app.include_router(build_router(lambda: services), prefix=PREFIX)
    ports.configure(services)  # the host's Slice 8 calls go through the ports, never the services directly
    if student_dependency is not None:
        app.dependency_overrides[current_student_ref] = student_dependency
    if student_write_dependency is not None:
        app.dependency_overrides[current_student_ref_for_write] = student_write_dependency
    return True
