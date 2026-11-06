"""Mounts the OS API on a host app, only when OS_ENABLED.

Services are built at mount time, so an invalid playbook or an unowned task type stops startup
instead of failing every request (spec §4.1, review I7). Research profiles are checked the same way
(Slice 2 spec §4.2). Building them does not connect to the database.
"""

import logging
import os
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
from app.os.ports.recipients import RecipientLookup
from app.os.settings import ModelModeError, flag, load_settings

PREFIX = "/v1/os"
log = logging.getLogger("app.os.mount")


def mount_os(app: FastAPI, *, env: Mapping[str, str] | None = None,
             student_dependency: Callable[..., str] | None = None,
             student_write_dependency: Callable[..., str] | None = None,
             playbook_dir: Path = PLAYBOOK_DIR, profile_dir: Path = PROFILE_DIR,
             document_types_dir: Path = TYPES_DIR, pack_dir: Path = PACK_DIR,
             recipient_lookup: RecipientLookup | None = None,
             student_facts: Callable[[str], dict | None] | None = None,
             choice_enabled: Callable[[], bool] | None = None,
             on_choice_request: Callable[[str], None] | None = None,
             choice_sink: Callable[..., dict | None] | None = None,
             choice_sink_enabled: Callable[[], bool] | None = None,
             document_files: Callable[[str, str], bytes] | None = None,
             documents_enabled: Callable[[], bool] | None = None,
             on_document_deleted: Callable[[str, str], None] | None = None) -> bool:
    """False when the OS stays off. `recipient_lookup` (Slice 9b): the host's student ref -> email address function,
    handed to the RecipientLookup port for this process (the worker loads its own from OS_RECIPIENT_LOOKUP).
    `student_facts` (P1-T4): the host's student ref -> StudentFacts dict (None while its part is off), handed to the
    StudentFacts port (the worker loads its own from OS_STUDENT_FACTS). `choice_enabled` / `on_choice_request`
    (P1-T6): the host's gate and post-commit hook for choice requests (ports.choice_requests); None keeps the OS's
    own behaviour. `choice_sink` (P1-T6, R-09): the host's route builder callback (ports.choice_sink); None keeps the
    builder standalone. `document_files` / `documents_enabled` / `on_document_deleted` (P1-T7): the host's file reader,
    its gate and its hook for a deleted linked document (ports.document_files); None keeps the OS on its own bytes
    (the worker loads its own reader from OS_DOCUMENT_FILES)."""
    enabled = flag(os.environ if env is None else env, "OS_ENABLED")
    try:
        settings = load_settings(env)
    except ModelModeError:
        if enabled:
            raise  # Slice 9a: e.g. offline AI without rehearsal mode refuses to start, with the reason
        return False
    except ValueError as e:  # e.g. no database, or resend without its key: the OS stays off
        if enabled:  # Slice 9b: say so loudly instead of failing silently (the message names settings, no values)
            log.error("PAI OS is enabled but not mounted: invalid settings (%s)", e)
        return False
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
    ports.configure(services, recipient_lookup, student_facts, choice_enabled, on_choice_request,
                    choice_sink, choice_sink_enabled, document_files, documents_enabled, on_document_deleted)  # the host calls go through the ports, never the services directly
    if student_dependency is not None:
        app.dependency_overrides[current_student_ref] = student_dependency
    if student_write_dependency is not None:
        app.dependency_overrides[current_student_ref_for_write] = student_write_dependency
    return True
