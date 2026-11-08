# P2-T7 plan: season monitoring and student reports (R-27, R-28; rows 6.23, 6.24)

Spec: P2 §4.7, P2-D20, P2-D21, P2-D22. Branch `pc/p2-t7-monitoring` from the integration 409f7e9. Migration `os_0030` on `os_0029`.

## Design
- **Marker for "being re-checked".** `os_knowledge_facts.recheck_reason` (`monitor` | `report`, NULL otherwise), `Fact.recheck`.
  Set when monitoring or a report sets a fact `unconfirmed`; cleared by every store write that makes the fact confirmed or
  verified. The compiler reads it: a step dated by a high-stakes fact that is being re-checked gets
  `blocked_reason = fact_rechecking:<field>` (P2-D20, through the P1 blocked mechanism); the inbox lists such a step as waiting.
- **Notice windows (P2-D21).** Facts of class `notice_window` (scope `registry`, ref `<region>:<family>`, field
  `notice_window`, value `{opens: MM-DD, closes: MM-DD}`, wrap-around allowed). Only confirmed or verified windows count;
  with none the region is off season and the TTL sweeper stays the only check. Nothing is invented.
- **Job `os.monitor`** (flag `OS_MONITOR`, cron `30 3 * * *`): per programme of a region and family inside its window, group
  the confirmed/verified facts of the window's intake by source URL; re-fetch each URL (page gateway `refresh=True`); save the
  snapshot (T3 `SnapshotStore`); a fact whose quote is no longer on the page, or whose page is gone (404/410), goes
  `unconfirmed` (store `revise`, cause `monitor`, marker `monitor`), plans revise through `after_fact_change`, and a `change`
  review item opens (T5 `open_item`, dedupe per fact). Transient failures, integrity blocks and suspect domains change nothing
  (the source guard drops those itself; `drop_domain_facts` now sets the marker too). One run per day (`os_monitor_runs`).
- **Reports (P2-D22).** `POST /v1/os/facts/{id}/report` (student, write access): the fact must be one the student's plan uses;
  reason code from data; free text goes only to the review item. Sets the fact `unconfirmed` (marker `report`), revises plans,
  opens or joins a `report` item (same fact reported again joins). Rate limit: distinct facts per student per day (data).
  `GET /v1/os/report/texts` gives the approved sentences; My plan `sources` list `fact_ids`; `FactSource` gets a
  "Report as wrong" link and form.
- **Student sentences** only in `app/os/monitor/texts.yaml` with `approved: true`; the plan-revised bell is the existing event.

## Files / tests
`alembic/versions_os/os_0030_monitoring.py`; `models.py`, `knowledge/port.py`, `knowledge/store.py` (marker), `compiler/compile.py`;
`monitor/{windows,run,reports,texts,config}.py` + `texts.yaml`, `config.yaml`; `api/report.py`; `workers/jobs.py`; `settings.py`;
`knowledge/research/pages.py` (`refresh`); `knowledge/sources/suspect.py` (marker); `api/queries.py` (waiting text);
`my_plan.py` (`fact_ids`). Frontend: `lib/os-report.ts`, `components/os/report-link.tsx`, `fact-source.tsx`.
Tests: `tests/os/monitor/` (windows, run proof with the fixture server, reports API proof, compiler block, migration, texts).

## Verification
tests/os 2660 passed; legacy 2560 passed; vitest 593 passed; next build ok; tach, freeze, one alembic head (os_0030), traceability ok.
