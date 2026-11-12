# P2-T1: foundations: fact columns, `verified`, revisions, vocabularies, display rule, P2 contracts, fixture sites — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Lay the shared ground every other P2 task builds on, and nothing more (spec §6.1 row T1):
- `os_knowledge_facts` gains `intake_term`, `owner_ref`, `fact_class`, `read_method`, `language`; status `verified`;
  the unique key becomes `(tenant, scope, ref, field, intake_term, intake_year, owner_ref)` (P2-D5, P2-D6, P2-D8).
- New append-only table `os_fact_revisions`, written by `SqlKnowledge` on every insert, change and status change (P2-D9).
- `Fact` and `KnowledgePort` know the new columns and `verified`.
- Data files `knowledge/regions.yaml` (R-76) and `knowledge/fact_classes.yaml` (P2-D7), and the one display function
  `knowledge/display.py` (R-25, R-26 model).
- Contracts `programme_facts.v1`, `merit_check.v1`, `programme_list.v2` with schema files, samples and hash tests (P2-D27).
- A local fixture server serving fictional, official-looking sites (spec §5 "no data from memory").

**R-IDs:** R-23, R-25 (model), R-26 (model), R-60, R-76. `built:` stays `false` for all of them in
`docs/requirements/connection.yaml`: each is finished by a later task (T5, T8, T10, T6). Tests carry `@pytest.mark.req`.

**Spec:** `docs/superpowers/specs/2026-11-07-p2-national-data-design.md` §2.2 (P2-D3, D5–D9, D24, D26, D27), §4.4,
§5, §6.1 T1, §11.1–11.2. Master §3 (R-23, R-25, R-26, R-60, R-76), §8.2, §9.1–9.2.

**Test database:** `os_test_b`, exported as `OS_TEST_DATABASE_URL` in the shell only. Never printed, never committed.

## Global constraints

- **Flags off = today, byte for byte.** T1 adds no flag and changes no response. All new columns have defaults that
  reproduce today's rows (`intake_term=''`, `owner_ref=''`, the other three `NULL`). Port reads keep their positional
  signature; new parameters are keyword-only with defaults that match today (`intake_term=None` = any term,
  `owner_ref=''`). The display function is not wired to any surface in T1. Every existing test passes unchanged.
- No country, region, exam or suffix name in `app/os/**/*.py` (R-58, `tests/os/test_invariants.py`). Region names live
  only in `regions.yaml`.
- No real institution, fee, date or merit figure anywhere. Fixture sites use the reserved `.test` TLD and fictional names.
- Alembic OS tree only, on top of `os_0024`; one head. Migration self-contained (no `app.os` import).
- Frozen contracts and their hash tests are untouched; new contracts get their own hash test file.
- Tach: everything new lives in `app.os` (or tests); no Counsellor import.

## Deviations decided here (within the spec)

- **D-t1-1 (P2-D5 backfill).** The migration backfills `intake_term` with `''` ("term not recorded"), not with the
  playbook's term. A self-contained migration cannot read playbook YAML, and writing a route's term into the migration
  would put route data in code. Reads with `intake_term=None` match any term, so behaviour is unchanged. **T8** owns the
  real backfill: its rollover script sets `intake_term` from each route playbook's `intake_terms` for rows still `''`.
- **D-t1-2.** `Fact.confirmed` becomes "confirmed or verified" (a verified fact is also confirmed, master §8.2). No
  verified row exists before T5, so nothing changes now. The remaining raw `status == "confirmed"` comparisons
  (`packs/inputs.py:92`, `packs/instructions.py:32`, `replan/apply.py:192`, `knowledge/research/run.py:116-152`,
  `workers/freshness.py:50`, `store.mark_stale`) are left to the task that first writes `verified` (T5), listed in
  "Interfaces" below.
- **D-t1-3.** Unknown field → class `unclassified`, which is high-stakes (fail safe: shown as fact only when `verified`).

## Files

| File | Change |
|---|---|
| `backend/alembic/versions_os/os_0025_fact_intake_columns.py` | new migration |
| `backend/app/os/models.py` | `knowledge_facts` columns, constraint; `fact_revisions` table; `FACT_STATUSES`, `READ_METHODS`, `REVISION_ACTIONS`, `REVISION_CAUSES` |
| `backend/app/os/knowledge/port.py` | `Fact` fields, `verified`, port signatures |
| `backend/app/os/knowledge/store.py` | new columns in reads/writes, term/owner filters, revisions, `revisions()` reader |
| `backend/app/os/knowledge/regions.yaml`, `regions.py` | R-76 vocabulary and `normalise_region` |
| `backend/app/os/knowledge/fact_classes.yaml`, `fact_classes.py` | classes, high-stakes flag, field → class |
| `backend/app/os/knowledge/display.py` | `display(fact, field, ...)` |
| `backend/app/os/contracts/programme_facts.py`, `merit_check.py`, `programme_list_v2.py` + `.schema.json` | contracts |
| `backend/app/os/contracts/samples/p2/*.json`, `valid.yaml` | fictional samples |
| `backend/scripts/export_os_schemas.py` | three new models |
| `backend/tests/os/fixture_sites/` (`server.py`, `sites/*.yaml`) | fixture server and fictional sites |
| `backend/tests/os/test_p2_fact_columns.py`, `test_p2_vocab_display.py`, `contracts/test_frozen_p2.py`, `test_fixture_sites.py` | tests |

## Tasks (tests first in each)

### Task 1: migration and models
- [ ] Test `test_p2_fact_columns.py`: after `upgrade os@head`, the columns exist with their defaults; a row written
  the old way reads back `intake_term=''`, `owner_ref=''`; two rows differing only in `intake_term` or `owner_ref` can
  coexist; status `verified` is accepted, `bogus` rejected; `read_method` outside `fetch/render/ocr/human/model` rejected;
  `os_fact_revisions` exists; downgrade then upgrade round-trips on an empty table.
- [ ] `os_0025`: add columns (`intake_term TEXT NOT NULL DEFAULT ''`, `owner_ref TEXT NOT NULL DEFAULT ''`,
  `fact_class TEXT`, `read_method TEXT`, `language TEXT`), replace `ck_os_knowledge_facts_status` (+ `verified`), add
  `ck_os_knowledge_facts_read_method`, `ck_os_knowledge_facts_language` (`^[a-z]{2,3}$`), drop and re-create
  `uq_os_knowledge_facts` on the 7-column key (same name, so `on_conflict_do_update(constraint=...)` is unchanged),
  create `os_fact_revisions`. Downgrade refuses if any `verified` row or a duplicate old key exists (no silent loss).
- [ ] Mirror in `models.py`.

### Task 2: `Fact`, port, store, revisions
- [ ] Tests: `Fact(status="verified")` needs quote and URL; `.confirmed` true for confirmed and verified; bad
  `read_method` rejected; store round-trips every new field; `programme_facts(..., intake_term="x")` filters;
  `owner_ref` default `''` hides owner rows; upsert/insert/mark_stale/confirm each write one revision with
  before/after and cause; `insert_if_absent` on an existing key writes none; a revision cannot be updated or deleted
  through the store (no such method) — append only.
- [ ] `Fact` gains `intake_term: str = ""`, `owner_ref: str = ""`, `fact_class: str | None = None`,
  `read_method: str | None = None`, `language: str | None = None` (after `id`, so positional use is unchanged).
- [ ] Store: write/read the new columns; key by `fact.intake_term`, `fact.owner_ref`; revisions in the same transaction.

### Task 3: vocabularies and the display rule
- [ ] Tests: every region code from master R-76 loads with its display name; `normalise_region` maps accepted
  spellings case/space/punctuation-insensitively and raises `UnknownRegion` otherwise; every class in
  `fact_classes.yaml` has `high_stakes`; every high-stakes class of master §8.2 is present and high-stakes; every fact
  field used by `app/os/playbooks/*.yaml` and the research profiles has a class; display matrix: high-stakes ×
  {unconfirmed, confirmed, verified, stale, missing}, normal × the same, other intake (year label), estimate.
- [ ] Data files and loaders (cached, `yaml.safe_load`), `display()`.

### Task 4: contracts
- [ ] Tests `contracts/test_frozen_p2.py`: schema files equal the models; `schema` const; samples validate; schema
  file sha256 pinned; validators (shown level needs source; `missing` carries no value; `other_intake` iff the fact's
  intake differs; merit `computed` needs a verified formula; closing merit with `list_complete=false` needs
  `list_number`; no field named like a chance or probability); `programme_list.v2` keeps every v1 entry field.
- [ ] Models, `export_os_schemas.py`, schema files, samples.

### Task 5: fixture sites
- [ ] Tests `test_fixture_sites.py`: the server serves a fictional site by `Host`; `client()` reaches
  `https://<host>.test/...` through it; robots.txt served; `set_page` changes a page (for T7); unknown host is 404;
  every fixture host ends in `.test`.
- [ ] `tests/os/fixture_sites/server.py` (stdlib `ThreadingHTTPServer` on 127.0.0.1:0, host-routed, a
  `httpx.BaseTransport` that rewrites `https://<host>/p` to the local port with the original `Host`) and a pytest
  fixture `fixture_sites` in `tests/os/conftest.py`. Sites in `tests/os/fixture_sites/sites/*.yaml`: a fictional
  regulator, an exam board, an admission body, a university (HTML notice with a deadline, merit-list page), a
  JavaScript-shell page (T4), a spam-injected page (T3).

### Task 6: checks and commit
```
cd backend && env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider tests/os      # os_test_b
cd backend && env -u PAI_API_KEY python -m pytest -q -p no:cacheprovider --ignore=tests/os  # legacy, URL set
cd backend && tach check && PYTHONPATH=. python scripts/check_alembic_heads.py
python scripts/check_freeze.py --base origin/pai-connect && python scripts/check_traceability.py
```
Commit `feat(os): P2 foundations ... (R-23, R-25, R-26, R-60, R-76)`.

## Interfaces for T2, T3, T5, T8 (fixed here; later tasks build against them)

**Columns `os.os_knowledge_facts`** (new): `intake_term TEXT NOT NULL DEFAULT ''`, `owner_ref TEXT NOT NULL DEFAULT ''`
(registry id of the body that sets the value; `''` = no owner), `fact_class TEXT NULL` (a key of `fact_classes.yaml`;
`NULL` = look up by field), `read_method TEXT NULL` in `fetch | render | ocr | human | model`, `language TEXT NULL`
(`^[a-z]{2,3}$`). `status` in `unconfirmed | confirmed | verified | stale`. Unique `uq_os_knowledge_facts` =
`(tenant_id, scope, ref, field, intake_term, intake_year, owner_ref)`. `scope` stays `route | programme`; **T2** widens
`ck_os_knowledge_facts_scope` for registry entities in its own migration.

**Table `os.os_fact_revisions`** (append only): `id BIGSERIAL`, `tenant_id`, `fact_id BIGINT NOT NULL` (FK
`os_knowledge_facts.id`, `ON DELETE RESTRICT`), `action` in `insert | change | status | undo`, `before JSONB NULL`,
`after JSONB NOT NULL`, `cause` in `seed | manual | research | import | review | monitor | report | rollover`,
`cause_ref TEXT NULL` (run id, import id, review id ...), `actor TEXT NULL` (reviewer id or job name), `at TIMESTAMPTZ`.
Index `(tenant_id, fact_id, id)`, `(tenant_id, cause, cause_ref)` (import undo, **T6**).

**`Fact`** (`app/os/knowledge/port.py`): `value, quote, url, checked_at, intake_year, status, conflict_note=None,
id=None, intake_term="", owner_ref="", fact_class=None, read_method=None, language=None`. `STATUSES = ("confirmed",
"unconfirmed", "stale", "verified")`; `READ_METHODS`. `confirmed` and `verified` need quote and URL. `.confirmed` =
confirmed or verified; `.verified`.

**`KnowledgePort`** (revised after the T1 review):
```python
def programme_facts(self, refs, fields, intake_year, *, intake_term: str | None = None,
                    owner_ref: str | None = None) -> dict[tuple[str, str], Fact]
def route_facts(self, route_key, fields, intake_year, *, intake_term: str | None = None,
                owner_ref: str | None = None) -> dict[str, Fact]
```
**Resolution order** (one row per key):
- owner: `owner_ref="<id>"` returns that owner's row, else the general (`''`) row; other owners never. `owner_ref=""`
  returns only general rows. `owner_ref=None` (default) = any owner: the general row wins, then the newest id.
- term: `intake_term="<t>"` filters. `intake_term=None` matches every term; on a clash the newest id wins **until T8**,
  after which the row whose term is the intake's current term wins (T8 changes `_resolve`).
**T8** adds `fallback_previous: bool = False` (P2-D24) as another keyword and marks fallbacks by `fact.intake_year`.

**Raw-SQL readers of `os_knowledge_facts` that must be updated by T2/T8** (they ignore term and owner today):
`my_plan.py:80-82` (fields Knowledge has), `api/self_serve.py:39` and `:59` (programme has facts / researched),
`knowledge/requests.py:95-100` (`_has_facts`). They are existence checks; all rows are `''`/`''` today, so a filter
would change nothing now but would hide owner and term rows later, so no filter is added in T1. T2 decides owner
semantics there, T8 term semantics.

**`verified` only through review.** `upsert`, `insert_if_absent` and `confirm` raise `ValueError` on status
`verified`; `set_status(fid, "verified", cause="review")` is the only way in (any other cause raises). A write
(`upsert`, any cause) onto a verified row: same value and quote → stays `verified`; value or quote changed → status
`unconfirmed` (back to review); the revision records cause, cause_ref and before/after. `mark_stale` and the
freshness sweeper take `confirmed` and `verified` (the event's `old.status` is the real one).

**`SqlKnowledge`** writes: `upsert(scope, ref, field, fact, source="manual", research_run_id=None, evidence=None, *,
cause=None, cause_ref=None, actor=None) -> int`; `insert_if_absent(..., *, cause=None, cause_ref=None, actor=None)`;
`mark_stale(fact_id)`; `confirm(...)`; `annotate(fact_id, *, conflict_note, checked_at=None, cause="research",
cause_ref=None, actor=None)`; `set_status(fact_id, status, *, cause, cause_ref=None, actor=None) -> Fact`
(**T5** uses it for `verified`; **T3/T7** for drops to `unconfirmed`); `revisions(fact_id) -> list[Revision]`
(`Revision(id, fact_id, action, before, after, cause, cause_ref, actor, at)`). `cause` defaults to `source`.
**T6**'s `knowledge.record()` is built on `upsert` + `set_status` and reverses imports from `revisions`.

**Vocabularies**: `app/os/knowledge/regions.py`: `regions(country) -> list[Region(code, name, aliases)]`,
`normalise_region(text, country) -> str` (raises `UnknownRegion`). Countries are keys in the YAML; codes are snake
case. `app/os/knowledge/fact_classes.py`: `fact_class(field, explicit=None) -> str`, `is_high_stakes(cls) -> bool`,
`classes() -> dict[str, FactClass(key, high_stakes, label)]`.

**Display** (`app/os/knowledge/display.py`): `display(fact: Fact | None, field: str, *, intake_year: int,
intake_term: str | None = None, estimate: bool = False) -> Display(level, show_value, high_stakes, fact_class,
other_intake, year_label)`. An explicit `fact_class` never makes a high-stakes field ordinary
(`high = high(field's class) or high(explicit)`). Until T8, `year_label` is the year only, and a fact with term `''`
is never "another intake" by term. `level` in `verified | confirmed | not_confirmed | estimated | missing`. Used by T7 and T10
(and P1 `plan_view` later).

**Contracts** (`app/os/contracts/`, frozen once merged):
- `programme_facts.v1` (`ProgrammeFactsV1`): `schema, programme_ref, route_key, intake{term,year},
  facts[{field, fact_class, high_stakes, level, value|null, source{url, quote, checked_at}|null,
  fact_intake{term,year}|null, other_intake, owner_ref|null, read_method|null, language|null}]`.
- `merit_check.v1` (`MeritCheckV1`): `schema, student_ref, programme_ref, intake, category|null,
  status: computed|not_confirmed|missing, formula{parts[{name, marks_part, weight}], total, owner_ref|null, level,
  source}|null, aggregate|null, marks_used[{key, value|null, out_of|null, evidence: stated|shown|confirmed|unknown}],
  parts[{name, status: known|missing|not_confirmed}], closing_merits[{intake, value|null, list_number|null,
  list_complete, level, source}]`. `level` (formula and closing merit) is `verified|confirmed|not_confirmed`, the
  programme_facts words; a closing merit carries a value only when `verified`. No chance or prediction field (R-31).
- `programme_list.v2` (`ProgrammeListV2`): v1 fields plus per entry `coverage_level: listed|researched|verified`,
  `region|null`, `not_run_yet: bool`.

**Fixture sites** (`tests/os/fixture_sites`): pytest fixture `fixture_sites` → `FixtureSites` with `.client()`
(an `httpx.Client` for `PageGateway(client=...)`), `.url(host, path)`, `.set_page(host, path, body, content_type=...)`,
`.reset()`, `.hosts`. Hosts end in `.test`.
