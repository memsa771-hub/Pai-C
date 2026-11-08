# P2-T11 calendars report (code part)

Branch `pc/p2-t11-calendars`, cut from integration 409f7e9; T6 (046f529) merged first, its migration renumbered `os_0030_imports` on `os_0029` (conflicts in router, models, test_models kept on both sides). No migration needed for T11 (`os_0031` unused).

## Built (R-20 with official data, R-26, R-33; row 6.20)
- `app/os/registry/calendars.yaml` + `calendars.py`: the calendar types (exam, result, admission), their date fields and fact classes (data); `record_calendar` (kind calendar, `attrs.calendar_type`, type fixed once recorded), `record_calendar_date` (the field must belong to the calendar's type; class from the vocabulary; tz checked; value `{"date","tz"}`; verified only through review), `calendar_dates` (read).
- `SqlKnowledge.registry_facts(refs, fields, year, intake_term/owner_ref/fallback_previous/fallback_year)` (+ port): facts of scope `registry`, same owner/term/previous-year rules as programme facts.
- Playbook `Expected.calendar: cal:<id>` (optional; `fact` is then the calendar's date field). `needed_calendars(playbook)`; `needed_fields` no longer asks a route fact for such an ask. `compile_plan(calendar_facts=)`; `needs.expand` reads the registry fact when the ask names a calendar, else the route fact exactly as before (a playbook without `calendar` compiles byte-identically, tested).
- The result-expected step from a calendar: dated from the date in its zone, `fact_refs = [("registry", cal, field)]`, cites the fact's URL, provisional until the fact is confirmed and while it is for another year (R-26, the labelled previous-year read), with a `confirm_fact` task whose fact ref keeps its scope. The provide step also carries the calendar ref, so a date that arrives, moves or passes revises the plan through `after_fact_change`. Compile fix: confirm tuples carry their scope (and `_apply_overrides` updated).
- `PlanService.compile` reads the calendars a playbook names and passes them in.
- Admin read API `GET /admin/registry/calendars?intake_year=` (calendars with their dates, level by the display rule).
- Row 6.20 test (`test_calendar_plan.py`): no date yet -> only the provide step; unconfirmed date -> provisional waiting step + check; confirmed -> firm and cited; moved date -> plan follows; day passes -> step gone, provide stays; last year's date while the intake is open -> used, labelled, provisional, replaced by this year's own fact. All with fictional calendars.

## Not done (separate, later)
The freeze-exception PR moving the Counsellor calendar and admission-rules JSON into Knowledge (frozen files; `check_freeze` is clean). Real calendar data enters through the import.

## Notes
- No new student sentences. No real dates, bodies or countries in code or tests (fixture board "alpha").
- R-26 `built` left as the integration has it.

## Checks
tests/os: 2777 passed, 1 skipped, 1 xfailed. Legacy: 2560 passed, 13 skipped. tach, freeze, alembic heads (one OS head), traceability OK. One earlier full run showed 68 failures from my compile change (confirm tuple unpacking in `_apply_overrides`); fixed and rerun green (and Postgres was down for a while after a limit reset; reruns done on os_test_c).
