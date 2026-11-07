# P2-T3 report: sources (R-24, R-71, R-29 snapshot part)

Branch `pc/p2-t3-sources`, merged with T1 commit 18387b3 (interface change). Migration `os_0026_sources` (down_revision `os_0025`; expect a renumber).

## Built
- Tables `os_source_domains`, `os_page_snapshots`, `os_source_files` (models + migration; downgrade refuses if rows exist).
- `app/os/knowledge/sources/`:
  - `allowlist.py`: YAML loader (`lists/*.yaml`, validated: list_ref and reviewed_by required), `SourceDomains` (sync, `state_of`, `is_listed(host, Scope)`, `mark_suspect`, `reactivate` two-person rule with an injected `is_approver`), one-body-one-domain rule with preferred suffixes from data (`duplicate_claim` / `ambiguous_claim`, `multiple_domains_ok` override), `seed_route_entries` to load old `official_sources` / `official_domains` as route entries.
  - `integrity.py` + `integrity.yaml`: spam (distinct terms, text/anchors/URLs), link flood (vs last clean snapshot), wholesale change (3-word shingle similarity, explained by a new notice word), TLS failure detection. All thresholds and words are data.
  - `snapshots.py`: `SnapshotStore` (hash dedupe per URL, flagged snapshots never the "last clean", original bytes for PDF/images with size cap).
  - `suspect.py`: `SourceGuard` (`is_suspect`, `is_listed`, `inspect`, `flag`) and `drop_domain_facts` (`set_status` to unconfirmed, cause `monitor`, cause_ref `source:<domain>`, actor `source_guard`, then the `after_change` hook).
- `PageGateway(sources=guard)`; `fetch(url, own, shared, scope=None)`. With a guard: suspect domains refused before cache and network (`suspect_domain`, not cached); allow-list scope lookup for page and redirect target; integrity after read (`integrity:<code>`, text cleared); snapshot per read page (`Page.snapshot_id`); TLS failure (robots or page) flags the domain and returns `tls_invalid`. Cached integrity/TLS blocks are re-read once the domain is active. With no guard: unchanged (old research tests pass untouched).
- `runner/worker.py`: `_source_guard` builds the guard only when `OS_SOURCE_GUARD=1`, syncs the lists and wires `after_fact_change(complete=False)`. Off by default.
- Spam proof (`test_p2_sources_gateway.py`): fixture `beta-college.test/admissions` is refused, domain suspect, its confirmed and verified facts drop to unconfirmed with revisions, other domains untouched, event `source_suspect` + hook once, flagged snapshot kept, later fetches make no HTTP request, two approvers needed to reactivate.

## Deviations
- `lists/` ships empty (no data from memory); real lists come from people lane H3. Tests use fictional `tests/os/fixtures/sources/*.yaml`.
- The `suspect_domain` review item belongs to T5 (`os_review_items` does not exist yet): T3 writes an `os_events` row and calls `SourceGuard.on_suspect(SuspectCase)`; T5 wires the item there. Reviewer-role check is the injected `is_approver` callable (T5 supplies it from `os_reviewers`).
- Revision cause for suspect drops is `monitor` (no new cause added).
- Urdu spam terms in `integrity.yaml` are marked for review by a reader before the first live run. No student sentences added.
- Allow-list matching is by host suffix (domain or subdomain); the old registrable-domain matching stays for `own`/`shared` lists.
- Language of snapshots is NULL (T4 sets it); read_method is `fetch` (T4 adds `render`/`ocr`).

## Interfaces for others
- T4: `PageGateway._inspected` is the hook; `SnapshotStore.save(..., read_method=, language=, original=, original_type=)`.
- T5: `SourceGuard(on_suspect=...)`, `SourceDomains.reactivate(domain, requested_by=, approved_by=, is_approver=)`, `SnapshotStore.get(id)` / `original(id)` for the snapshot view.
- T6: `SourceDomains.is_listed(host, Scope)`, `PageGateway.fetch(..., scope)`.
- T7: `SnapshotStore.latest(url)`, `drop_domain_facts`.

## Counts and checks
- tests/os: 2400 passed, 1 skipped, 1 xfailed. New: 30 tests in `test_p2_sources_*.py` (+ models table list).
- legacy: 2559 passed, 14 skipped.
- tach: all modules validated. Freeze check: clean. Alembic heads: `os_0026` (os) single head. Traceability: pass.
- ruff clean on new files (remaining findings in pages.py and worker.py are pre-existing).
