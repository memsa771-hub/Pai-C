# P2-T2 registry report

Branch `pc/p2-t2-registry` (T1 interface commit 18387b3 merged). Migration `os_0026_registry` (down_revision `os_0025`; renumber at merge).

## Built (R-32, R-33, R-34)
- Migration/models: `os_registry` (entity_id `<prefix>:<slug>`, kind, parent, region, institution_type, aliases, official_domains, status+successor, `list_ids`, source_url/quote/checked_at, `attrs` JSONB), append-only `os_registry_revisions` (FK RESTRICT), `os_registry_links` (`uses_test`, `has_category`, `admits`), `os_programmes` + `institution_id, campus_id, level, field, family, region`, `ck_os_knowledge_facts_scope` widened with `registry`. Downgrade refuses with data.
- `app/os/registry/`: `model.RegistryEntry` (validation: id prefix per kind, https source + quote + tz date, region in regions.yaml, institution/campus must name official lists), `store.RegistryStore.record(entry, cause=, cause_ref=, actor=)` (= knowledge.record() for registry rows; parent/successor/list must exist; one revision per change; no delete), `link`, `link_programme`, `list`, `children`, `links_from/to`, `programmes_of`, `revisions`, `list_progress(es)`; `lists.parse_official_lists/load_official_lists` (H3 research YAML shape; unknown keys kept in `attrs.extra`; `domains`/`not_found` ignored, T3/walkthroughs own them); `coverage.coverage_map/summarise`.
- Coverage (computed): listed / researched (any fact for intake on the institution, campuses, programmes, admitting systems + their tests, categories, calendars) / verified (>=1 high-stakes fact, all verified). `attrs.not_readable` keeps it listed. Unknown fact class = high-stakes. Expected-field list is T9's.
- Admin API (admin token): `GET /admin/registry/entities`, `/entities/{id}`, `/lists`, `/coverage?intake_year=`. One include line in `api/router.py`.
- `Programme` dataclass gains read-only registry fields; `ProgrammeStore.upsert` unchanged (re-seed leaves them). `SqlKnowledge` Scope literal gains `registry`.
- Raw-SQL readers (owner semantics, per T1 note): existence checks (`requests._facts_for/_has_facts`, `self_serve` x2) now count only general (`owner_ref=''`) rows, since a body's row is not research of the programme; `my_plan._knowledge_sources` stays any-owner (matches the port's `owner_ref=None`), comment added. T8 decides term.
- `docs/requirements/connection.yaml`: R-32, R-33, R-34 `built: true`.

## Deviations / notes
- Registry revisions use their own table (spec only names fact revisions).
- No new student sentences. No real data loaded; fixtures are fictional.
- test_models table list got an additive line (will conflict trivially with other tasks).

## Interfaces for others
- T6: `RegistryStore.record(...)`, `parse_official_lists`, facts about entities via `SqlKnowledge.upsert("registry", entity_id, ...)`.
- T8/T9: `coverage_map(engine, tenant, year, intake_term=, region=)`; `list_progresses()`.
- T9 needs expected-field logic on top of coverage.

## Counts / checks
tests/os: 2403 passed, 1 skipped, 1 xfailed (one test_models table-list failure fixed, rerun green); legacy: 2560 passed, 13 skipped; tach OK; freeze OK; alembic heads OK; traceability OK. New tests: 44 (+1 existence readers) in tests/os/registry and test_api_registry.
