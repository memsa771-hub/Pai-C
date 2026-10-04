"""Small, request-scoped graph projection for the shared text/voice Counselor.

The Vault and Student Understanding remain authoritative. This module only
selects accepted, counseling-safe nodes and their already supported links.
"""

import json


_NODE_FIELDS = {
    "education": ("qualification_name", "institution_name", "canonical_level",
                  "academic_status", "field_of_study", "start_date", "end_date",
                  "graduation_year", "result", "details"),
    "courses": ("name", "grade", "score", "details"),
    "experience": ("organization", "role", "start_date", "end_date", "details"),
    "projects": ("name", "role", "details"),
    "skills": ("name", "proficiency"),
    "goals": ("title", "goal_type", "commitment", "target_date", "details"),
    "activities": ("title", "role", "details"),
    "research": ("title", "role", "details"),
    "achievements": ("title", "details"),
    "tests": ("test_type", "test_date", "overall_score"),
    "voice_statements": ("voice_type", "direction", "statement"),
    "influences": ("source_type", "direction", "suggested_direction", "student_alignment",
                   "student_quote"),
}
_SECTION_KIND = {"experience": "work_experience", "projects": "project",
                 "skills": "skill", "goals": "goal", "activities": "activity",
                 "research": "research", "achievements": "achievement",
                 "tests": "test_attempt", "voice_statements": "student_voice_statement",
                 "influences": "external_influence", "courses": "course"}
_LABEL = {"education": "qualification_name", "course": "name", "project": "name",
          "skill": "name", "goal": "title", "work_experience": "role",
          "activity": "title", "research": "title", "achievement": "title",
          "test_attempt": "test_type", "student_voice_statement": "statement",
          "external_influence": "suggested_direction"}
_MAX_CHARS = 6500


def _terms(value: str) -> set[str]:
    # Unicode word boundaries, with no language-specific dictionary or regex.
    words, current = set(), []
    for char in value.casefold():
        if char.isalnum():
            current.append(char)
        elif current:
            words.add("".join(current))
            current = []
    if current:
        words.add("".join(current))
    return {word for word in words if len(word) > 2}


def _pick(rows: list[dict], fields: tuple[str, ...], query: set[str], limit: int,
          *, baseline=None) -> list[dict]:
    ranked = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        selected = {key: row[key] for key in fields if row.get(key) is not None}
        if not selected:
            continue
        match = len(query & _terms(json.dumps(selected, ensure_ascii=False, default=str)))
        priority = int(bool(baseline and baseline(row)))
        ranked.append((priority, match, -index, row, selected))
    ranked.sort(reverse=True, key=lambda item: item[:3])
    return [{"ref": row.get("id"), "value": selected}
            for _, _, _, row, selected in ranked[:limit]]


def compact_student_context(understanding: dict, query: str = "") -> dict:
    """Select a stable baseline plus relevant connected facts under a prompt cap."""
    query_terms = _terms(query)
    context = {}
    identity = understanding.get("identity") or {}
    known_identity = {key: item["value"] for key in
                      ("preferred_name", "current_status", "status_category")
                      if isinstance((item := identity.get(key)), dict)
                      and item.get("value") is not None}
    if known_identity:
        context["identity"] = known_identity

    selected_refs = {}
    for section, fields in _NODE_FIELDS.items():
        parent = understanding.get("education" if section == "courses" else section) or {}
        rows = parent.get("courses" if section == "courses" else "nodes") or []
        if section == "education":
            baseline = lambda row: row.get("academic_status") == "current"
            limit = 4
        elif section == "goals":
            rows = [row for row in rows if (row.get("details") or {}).get(
                "direction_status") not in {"changed", "rejected"}]
            baseline = lambda row: row.get("commitment") == "committed"
            limit = 3
        else:
            baseline = None
            has_match = any(query_terms & _terms(json.dumps(row, ensure_ascii=False, default=str))
                            for row in rows if isinstance(row, dict))
            limit = (3 if section == "courses" else 2) if has_match else 1
        chosen = _pick(rows, fields, query_terms, limit, baseline=baseline)
        if chosen:
            context[section] = [item["value"] for item in chosen]
            kind = _SECTION_KIND.get(section, section)
            selected_refs[kind] = {item["ref"]: item["value"] for item in chosen
                                   if item["ref"]}

    direction = (understanding.get("student_voice") or {}).get("current_direction") or {}
    if direction.get("status") not in {None, "unknown"}:
        context["current_direction"] = {key: direction[key]
                                         for key in ("status", "title", "options")
                                         if direction.get(key)}
    for section in ("career", "preferences", "constraints", "location", "mobility"):
        values = understanding.get(section) or {}
        chosen = {key: item["value"] for key, item in values.items()
                  if isinstance(item, dict) and item.get("value") is not None}
        if chosen:
            context[section] = chosen
    interests = understanding.get("interests") or {}
    if interests:
        chosen = {key: [item.get("title") for item in interests.get(key, [])[:4]
                        if item.get("title")] for key in ("stated", "experienced")}
        if any(chosen.values()):
            context["interests"] = chosen

    links = []
    for course in (understanding.get("education") or {}).get("courses") or []:
        source = selected_refs.get("course", {}).get(course.get("id"))
        target = selected_refs.get("education", {}).get(course.get("education_id"))
        if source and target:
            links.append(f"{source['name']} belongs to {target['qualification_name']}")
    for edge in (understanding.get("education") or {}).get("edges") or []:
        first = selected_refs.get("education", {}).get(edge.get("from"))
        second = selected_refs.get("education", {}).get(edge.get("to"))
        if first and second and edge.get("relation") == "precedes":
            links.append(f"{first['qualification_name']} precedes {second['qualification_name']}")
    for edge in understanding.get("relationships") or []:
        source, target = edge.get("from") or {}, edge.get("to") or {}
        source_node = selected_refs.get(source.get("type"), {}).get(source.get("id"))
        target_node = selected_refs.get(target.get("type"), {}).get(target.get("id"))
        source_label = _LABEL.get(source.get("type"))
        target_label = _LABEL.get(target.get("type"))
        relation = edge.get("relation")
        if (source_node and target_node and source_label in source_node
                and target_label in target_node and relation in {"supports", "relevant_to", "has_evidence"}):
            wording = "has matching stated field to" if relation == "relevant_to" else relation.replace("_", " ")
            links.append(f"{source_node[source_label]} {wording} {target_node[target_label]}")
    if links:
        context["connections"] = list(dict.fromkeys(links))[:12]

    # Bound the complete projection, including free-text record details. Drop
    # lower-priority nodes before core identity, education and goals.
    while len(json.dumps(context, ensure_ascii=False, default=str)) > _MAX_CHARS:
        trimmed = False
        for section in ("connections", "influences", "voice_statements", "activities", "achievements",
                        "research", "tests", "projects", "experience", "skills", "courses",
                        "goals", "education"):
            if isinstance(context.get(section), list) and context[section]:
                context[section].pop()
                if not context[section]:
                    del context[section]
                trimmed = True
                break
        if not trimmed:
            for section in ("interests", "mobility", "location", "constraints", "preferences",
                            "career", "current_direction", "identity"):
                if section in context:
                    del context[section]
                    trimmed = True
                    break
        if not trimmed:
            break
    return context
