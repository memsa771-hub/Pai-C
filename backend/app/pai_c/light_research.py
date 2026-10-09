"""Collect decisive public facts through existing registered capabilities."""

from app.plugins._shared.sources import public_https


def _facts(requirements):
    facts = []
    for requirement in requirements:
        for kind, values in (("rule", requirement.get("rules") or []),
                ("fee", (requirement.get("fees") or {}).values()),
                ("deadline", (requirement.get("deadlines") or {}).values())):
            for index, fact in enumerate(values):
                if fact.get("quote") and public_https(fact.get("source_url")):
                    facts.append({**fact, "fact_id": fact.get("fact_id") or
                        f"{requirement['requirement_set_id']}:{kind}:{index}",
                        "label": requirement["status"], "requirement_set_id": requirement["requirement_set_id"]})
    return facts


async def collect_light_research(context, brief):
    lanes = (brief.get("mirror") or {}).get("roadmap_lanes") or []
    goals = brief.get("goals") or []
    details = (goals[0].get("details") or {}) if goals else {}
    countries = details.get("target_countries") or []
    results, missing = [], []
    for lane in lanes:
        key = lane["lane"]
        # The route is student data, not an inline list of destinations or subjects.
        route = lane.get("route") or {}
        goal_text = " ".join(str(goal.get("title") or goal.get("text") or "") for goal in goals)
        search = {"objective": " ".join(str(value) for value in (
            route.get("field"), route.get("level"), route.get("place_preference"),
            route.get("kind"), goal_text) if value),
            "country": route.get("place_preference") or (countries[0] if len(countries) == 1 else ""),
            "level": route.get("level") or details.get("degree_level") or ""}
        source = lane.get("source_url") or lane.get("url")
        refresh = brief.get("refresh_candidate") or {}
        if refresh.get("url") and key in refresh.get("lanes", [refresh.get("lane")]):
            source = refresh["url"]
        # If a source/program is already known, program.research checks the cache
        # before invoking any fetch, search, extraction or registry lookup.
        if public_https(source):
            candidates = [{"url": source, "title": lane.get("title") or search["objective"]}]
        else:
            found = await context.capabilities("program.discover", search)
            candidates = found.get("candidates") or []
        requirements = []
        if candidates:
            candidate = candidates[0]
            payload = {"url": candidate["url"], "country": candidate.get("country") or search["country"] or "unknown",
                "level": candidate.get("level") or search["level"],
                "intake": candidate.get("intake") or details.get("target_intake") or "",
                "route": {"url": candidate["url"]},
                "focus": {"fields": brief.get("decisive_fields") or [], "questions": brief.get("questions") or []}}
            related = candidate.get("related_urls") or []
            if related:
                payload["corroborating_url"] = related[0]
            researched = await context.capabilities("program.research", payload)
            requirements = researched.get("requirements") or []
        facts = _facts(requirements)
        if not facts:
            missing.append({"lane": key, "need": "decisive_facts", "status": "needs_info"})
        results.append({"lane": key, "facts": facts})
    question_facts = []
    for question in brief.get("questions") or []:
        if any(question["id"] in (fact.get("question_ids") or []) for item in results for fact in item["facts"]):
            continue
        found = await context.capabilities("program.discover", {"objective": question["question"],
            "country": countries[0] if len(countries) == 1 else "", "level": details.get("degree_level") or ""})
        candidates = found.get("candidates") or []
        if candidates:
            researched = await context.capabilities("program.research", {
                "url": candidates[0]["url"], "country": candidates[0].get("country") or "unknown",
                "level": candidates[0].get("level") or "", "intake": details.get("target_intake") or "",
                "route": {"url": candidates[0]["url"]}, "focus": {"fields": [], "questions": [question]}})
            question_facts.extend(_facts(researched.get("requirements") or []))
    return {"lanes": results, "question_facts": question_facts, "missing": missing,
            "questions": brief.get("questions") or []}
