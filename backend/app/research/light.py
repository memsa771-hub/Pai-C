"""Collect decisive public facts through existing registered capabilities."""

from app.plugins._shared.sources import public_https


async def collect_light_research(context, brief):
    lanes = (brief.get("mirror") or {}).get("roadmap_lanes") or []
    goals = brief.get("goals") or []
    details = (goals[0].get("details") or {}) if goals else {}
    countries = details.get("target_countries") or []
    results, missing = [], []
    for lane in lanes:
        key = lane["lane"]
        # The route is student data, not an inline list of destinations or subjects.
        search = {"objective": " ".join(str(value) for value in (
            lane.get("title"), lane.get("why"), brief.get("stated_preference")) if value),
            "country": lane.get("country") or (countries[0] if len(countries) == 1 else ""),
            "level": lane.get("level") or details.get("degree_level") or ""}
        source = lane.get("source_url") or lane.get("url")
        refresh = brief.get("refresh_candidate") or {}
        if refresh.get("url") and (not refresh.get("lane") or refresh["lane"] == key):
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
        if not facts:
            missing.append({"lane": key, "need": "decisive_facts", "status": "needs_info"})
        results.append({"lane": key, "facts": facts})
    return {"lanes": results, "missing": missing, "questions": brief.get("questions") or []}
