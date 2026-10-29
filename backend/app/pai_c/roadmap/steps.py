"""The full route of one field, every step coloured from the Vault (spec
FOUR_FEATURES_SPEC.md §4.1): done (green), half (yellow) or not (red), with the
Vault entry behind the colour and the admission rule behind the step.

Pure and deterministic like the verdict: the same Vault rows, card and day give
the same steps. Evidence is the Vault view row the status was read from, with
the view's level (the one ladder the Mirror and paths show) and its source
label, so a step done on a stated fact reads "done · stated". A manual tick
counts as done, and is offered only where the Vault is silent (`tickable`).
Labels are copy keys with values (policy/roadmap.json copy); each step carries
the calendar events it waits for (`timing`) for the time estimate.
"""

from datetime import date

from app.pai_c.memory import entry_ref, vault_catalog
from app.pai_c.paths.fields import current_education, group_rules, known_groups, read_education, study_fields
from app.pai_c.roadmap import calendar as cal
from app.pai_c.roadmap.engine import Standing, _for_group, _route_group, roadmap_policy
from app.pai_c.roadmap.rules import Rule, rule_for
from app.pai_c.roadmap.timeline import next_occurrence


def _policy() -> dict:
    return roadmap_policy()


def _evidence(row) -> dict | None:
    if row is None:
        return None
    from app.pai_c.mirror.engine import source_label
    return {"id": entry_ref(row.entry), "level": row.entry.get("level"), "source_label": source_label(row)}


def _records(rows, kind: str) -> list:
    return [row for row in rows if row.entry.get("kind") == "record" and row.entry.get("type") == kind]


def _step(key: str, label_key: str, values: dict, status: str, row=None, rule: dict | None = None,
          timing: dict | None = None) -> dict:
    return {"key": key, "kind": key.split(":")[0], "label_key": label_key, "values": values, "status": status,
            "evidence": _evidence(row), "rule": rule, "manual_done": False, "timing": timing}


def _rule_ref(rule: Rule | None, source: str | None = None) -> dict | None:
    if rule is None:
        return None
    return {"source": source or (rule.sources[0] if rule.sources else None), "confidence": rule.confidence}


def _number(text) -> float | None:
    """A test score as a percent: "62%", "62", or "248/400". A bare number
    above 100 has no scale, so it is unreadable rather than a guess."""
    text = str(text or "").strip().rstrip("%").strip()
    try:
        if "/" in text:
            got, total = (float(part) for part in text.split("/", 1))
            return got / total * 100 if total > 0 and 0 <= got <= total else None
        value = float(text)
    except ValueError:
        return None
    return value if 0 <= value <= 100 else None


# ---- the steps --------------------------------------------------------------------

def _open_groups(field_key: str, rule: Rule | None) -> list[str]:
    study = study_fields().get(field_key)
    if rule is not None and rule.groups_open is not None:
        return list(rule.groups_open)
    return list(study.open_to) if study else []


def _group_values(field_key: str, rule: Rule | None) -> tuple[str, dict]:
    groups = _open_groups(field_key, rule)
    if not groups or set(known_groups()) <= set(groups):
        return "step_any_group", {}
    return "step_group", {"groups": [_route_group(code) for code in groups if code in known_groups()]}


def _group(field_key, rule, standing: Standing, row) -> dict:
    rules = group_rules()
    label, values = _group_values(field_key, rule)
    if standing.level is None or not standing.readable:
        return _step("group", "step_tell_education", {}, "not")
    if standing.level in rules["before_intermediate"]:
        return _step("group", label, values, "not", row, _rule_ref(rule))
    if rule is None or not standing.groups:
        return _step("group", label, values, "not", row)
    results = [_for_group(field_key, rule, group, None) for group in standing.groups]
    if any(status == "open" for status, _, _ in results):
        status = "done"
    elif any(status == "step" for status, _, _ in results):
        status = "half"  # the group opens it with a bridge or check, which are their own steps
    else:
        status = "not"
    return _step("group", label, values, status, row, _rule_ref(rule))


def _track(level: str | None) -> str | None:
    return _policy()["timeline"]["tracks"].get(level)


def _finish_timing(track: str | None, variant: str | None = None) -> dict:
    finish = _policy()["timeline"]["finish"]
    key = f"{track}_{variant}" if variant and f"{track}_{variant}" in finish else track
    return dict(finish[key]) if key in finish else {"unknown": True}


def _complete_intermediate(standing: Standing, record: dict | None, row, today: date) -> dict:
    rules, catalog = group_rules(), vault_catalog()
    if standing.level is None:
        return _step("complete_intermediate", "step_finish_intermediate", {}, "not")
    level = read_education(record)[0] if record else standing.level
    track = _track(level)
    if level in rules["before_intermediate"]:
        done = (record or {}).get("academic_status") == "completed"
        return _step("complete_intermediate", "step_finish_intermediate", {}, "not", row,
                     timing=_finish_timing(track, "done" if done else None))
    values = {"level": catalog.label("levels", level)}
    status = (record or {}).get("academic_status")
    if status == "completed":
        return _step("complete_intermediate", "step_finish", values, "done", row)
    year = ((record or {}).get("details") or {}).get("current_year")
    timing = _finish_timing(track, "year_1" if year == 1 or status == "planned" else None)
    if status != "current":
        return _step("complete_intermediate", "step_finish", values, "not", row, timing=timing)
    shown = next(iter(timing.get("chain") or ()), None)
    event = cal.event(shown) if shown else None
    when = next_occurrence(event["months"], None, today) if event else None
    if when is None:
        return _step("complete_intermediate", "step_finish", values, "half", row, timing=timing)
    month = _policy()["steps"]["month_labels"][when[1] - 1]
    return _step("complete_intermediate", "step_finish_exam", {**values, "month": month, "year": when[0]},
                 "half", row, timing=timing)


def _marks(rule: Rule, standing: Standing, record: dict | None, row) -> dict:
    floor, have = rule.min_percent, standing.percent
    rules = group_rules()
    if standing.level is None or standing.level in rules["before_intermediate"] or record is None:
        # No intermediate yet: there are no marks to add, so the step is still ahead.
        return _step("marks", "step_marks_unknown", {"min": floor}, "not", None, _rule_ref(rule))
    if have is None:
        return _step("marks", "step_marks_unknown", {"min": floor}, "half", row, _rule_ref(rule))
    values = {"min": floor, "have": have}
    if have >= floor:
        return _step("marks", "step_marks", values, "done", row, _rule_ref(rule))
    improve = _policy()["timeline"]["improve"].get(_track(standing.level))
    return _step("marks", "step_marks", values, "not", row, _rule_ref(rule),
                 timing=dict(improve) if improve else {"unknown": True})


def _course_for(text: str, courses: list):
    terms = [term for term in _policy()["steps"]["bridge_course_terms"] if term in str(text or "").lower()]
    for row in courses:
        value = row.entry.get("value") or {}
        name = f"{value.get('name', '')} {value.get('normalized_name', '')}".lower()
        if any(term in name for term in terms):
            return row
    return None


def _need(need: dict, rule: Rule | None, courses: list) -> dict:
    detail = need.get("detail") or {}
    if need["kind"] == "bridge":
        values, text = {"text": detail.get("text"), "source": detail.get("source")}, detail.get("text")
        ref = {"source": detail.get("source"), "confidence": rule.confidence} if rule else None
        key, label = "bridge", "step_bridge"
    else:
        values, text, ref = {"note": detail.get("note")}, detail.get("note"), _rule_ref(rule)
        key, label = "check", "step_check"
    course = _course_for(text, courses)
    return _step(key, label, values, "done" if course else "not", course, ref)


def _test_code(row) -> str | None:
    test_type = (row.entry.get("value") or {}).get("test_type")
    return vault_catalog().choice_code("tests", str(test_type or "")) or str(test_type or "").strip().lower()


def _test(test: dict, rule: Rule | None, attempts: list) -> dict:
    codes, passing = tuple(test.get("codes") or ()), test.get("pass_percent")
    values = {"name": test["name"]}
    label = "step_test"
    if passing is not None:
        values["pass"] = passing
        label = "step_test_pass"
    ref = {"source": test.get("source"), "confidence": rule.confidence} if rule else None
    calendar_test = cal.calendar_test(codes)
    timing = ({"chain": [calendar_test["key"]], "result": calendar_test["key"] + ":result"}
              if calendar_test else {"unknown": True})
    mine = [row for row in attempts if codes and _test_code(row) in codes]
    pending = set(_policy()["steps"]["test_pending_statuses"])
    for row in mine:
        score = _number((row.entry.get("value") or {}).get("overall_score"))
        if score is not None and (passing is None or score >= passing):
            return _step(f"test:{test['name']}", label, values, "done", row, ref, timing)
    if mine:
        # Planned, registered, below the pass mark or a score PAI cannot read: under way.
        best = next((row for row in mine if str(((row.entry.get("value") or {}).get("details") or {})
                                              .get("status", "")).lower() in pending), mine[0])
        return _step(f"test:{test['name']}", label, values, "half", best, ref, timing)
    return _step(f"test:{test['name']}", label, values, "not", None, ref, timing)


def _tickable(steps: list[dict]) -> list[dict]:
    """A tick is the student's own claim, so it is offered only where the
    Vault is silent: a tickable kind that is red with no Vault entry behind
    it. Where the Vault speaks (marks below the floor, a registered test, a
    course record) the Vault's colour stands."""
    kinds = set(_policy()["steps"]["tickable_kinds"])
    for step in steps:
        step["tickable"] = step["kind"] in kinds and step["status"] == "not" and step["evidence"] is None
    return steps


def _manual(steps: list[dict], steps_done) -> list[dict]:
    """Apply the student's ticks; a stored tick on a step the Vault now
    observes (or older data) is ignored."""
    done = set(steps_done or ())
    policy = _policy()
    for step in _tickable(steps):
        if step["key"] not in done or not step["tickable"]:
            continue
        step["manual_done"] = True
        step["status"] = "done"
        step["evidence"] = {"id": None, "level": policy["steps"]["manual_level"],
                            "source_label": policy["copy"]["marked_by_you"]}
    return steps


def route_steps(card: dict, standing: Standing, snapshot: list, items: list = (), today: date | None = None,
                steps_done=(), record: dict | None = None, record_id: str | None = None) -> list[dict]:
    """Every step of the card's route in order (group, complete_intermediate,
    marks, bridge/check, each entry test, apply, degree). `snapshot` is the
    Vault view rows (MemoryService.vault_rows); `items` are extra Vault rows
    to cite; `steps_done` the student's manual ticks by step key. A degree
    student's undergraduate route is not read here (the verdict says so).
    `record`/`record_id` are the education record the standing was read
    from (current_education over profile_cards); its view row is picked by
    id so steps and standing never describe different records. Without
    them the record is chosen from the view rows the same way."""
    today = today or date.today()
    if standing.level in group_rules()["degree_levels"]:
        return []
    rows = [row for row in [*snapshot, *items] if getattr(row, "sensitivity", None) != "restricted"]
    field_key, verdict = card.get("field_key"), card["verdict"]
    rule = rule_for(field_key) if field_key in study_fields() else None
    education = _records(rows, "education")
    if record_id is not None:
        row = next((row for row in education if str(row.entry["id"]) == str(record_id)), None)
    else:
        record = current_education([row.entry["value"] for row in education])
        row = next((row for row in education if row.entry["value"] is record), None)

    steps = [_group(field_key, rule, standing, row), _complete_intermediate(standing, record, row, today)]
    if rule is not None and rule.min_percent is not None:
        steps.append(_marks(rule, standing, record, row))
    courses = _records(rows, "course")
    steps += [_need(need, rule, courses) for need in verdict["needs"] if need["kind"] in ("bridge", "check")]
    attempts = _records(rows, "test_attempt")
    steps += [_test(test, rule, attempts) for test in verdict["tests"]]
    steps.append(_step("apply", "step_apply", {"degree": card["title"]}, "not"))
    years = verdict.get("years") or (cal.degree_years(field_key) if field_key else None)
    steps.append(_step("degree", "step_degree" if years else "step_degree_years_unknown",
                       {"degree": card["title"], "years": years}, "not", None, _rule_ref(rule)))
    colours = _policy()["steps"]["colours"]
    for step in _manual(steps, steps_done):
        step["colour"] = colours[step["status"]]
    return steps


def step_key_of_legacy(step: dict) -> str | None:
    """The step key an old checklist entry (copy key step_*) stands for, so
    ticks saved by position before steps had keys map once by position."""
    legacy = {"step_marks": "marks", "step_bridge": "bridge", "step_check": "check", "step_group": "group",
              "step_any_group": "group", "step_apply": "apply"}
    key = step.get("key")
    if key == "step_test":
        return f"test:{step.get('name')}"
    return legacy.get(key, key)
