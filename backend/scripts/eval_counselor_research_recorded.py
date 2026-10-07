"""Offline, synthetic research-contract evaluation for the ten Counselor personas.

This exercises roadmap composition and deterministic evidence gates. The
programmes and threshold below are fixtures, not real admissions advice.
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

from app.plugins._shared.verification import SourceVerifier, official_url
from app.plugins.gap_assessment import assess as assess_gaps
from app.plugins.qualification_recognition import recognize
from app.plugins.roadmap_builder import build


SCENARIOS = (
    ("hamza", "biology research in Pakistan", "lab science career", "Pakistan", None, "medicine"),
    ("ali", "data science in USA", "technology career", "USA", None, None),
    ("ayesha", "funded computer science masters", "earn and support family", "Germany", 7, None),
    ("bilal", "power electronics MS", "EV engineering career", "Germany", 7, None),
    ("sana", "part-time data analytics", "analytics career", "United Kingdom", 7, None),
    ("usman", "design degree", "app interface career", "Pakistan", None, "engineering"),
    ("volunteer", "funded policy masters", "education policy career", "United Kingdom", 7, None),
    ("contradiction", "architecture degree", "urban design career", "Pakistan", 7, None),
    ("refusal", "environmental science", "conservation career", "Pakistan", 7, None),
    ("urdu", "laboratory science", "health research career", "Pakistan", 7, None),
)


async def evaluate_recorded(persona_ids=None) -> list[dict]:
    selected = [case for case in SCENARIOS if persona_ids is None or case[0] in persona_ids]
    if not selected:
        raise ValueError("No matching persona")
    results = []
    for name, stated, objective, country, score, family in selected:
        started = time.monotonic()
        observed = datetime.now(timezone.utc) - timedelta(minutes=2)
        corroborated = observed + timedelta(minutes=1)
        page = "Winter 2027: IELTS overall 7 is required."
        claim = {"kind": "requirement", "field": "test.score", "value": 7,
                 "quote": "IELTS overall 7", "source_url": "https://recorded.example.edu/entry",
                 "checked_at": observed.isoformat(), "comparator": "gte",
                 "threshold": 7, "unit": "IELTS band"}
        def verified_at(url):
            route_claim = {**claim, "source_url": url}
            return SourceVerifier().verify(
                claims=[route_claim], source_url=url,
                official_domains={"example.edu"}, intake="winter 2027",
                page_text=page, checked_at=observed,
                corroboration=[{**route_claim,
                                "source_url": "https://recorded.example.edu/admissions",
                                "checked_at": corroborated.isoformat()}],
                corroborated_at=corroborated)

        verdict = verified_at(claim["source_url"])

        async def child(capability_id, payload):
            if capability_id == "program.discover":
                slug = quote(str(payload["objective"]).lower(), safe="")
                return {"candidates": [{"title": payload["objective"],
                        "url": f"https://recorded.example.edu/{slug}",
                        "country": payload.get("country") or country}], "unconfirmed": []}
            if capability_id == "program.research":
                url = payload["url"]
                route_verdict = verified_at(url)
                return {"requirements": [{"country": country, "status": route_verdict.status,
                        "source_url": url, "checked_at": observed.isoformat(),
                        "requirement_set_id": f"fixture:{name}:{url}",
                        "rules": [{**claim, "source_url": url}]}], "unconfirmed": []}
            if capability_id == "qualification.recognize":
                return await recognize(None, payload)
            if capability_id == "scholarship.discover":
                return {"scholarships": [], "unconfirmed": []}
            if capability_id == "gap.assess":
                return await assess_gaps(None, payload)
            raise AssertionError(f"Unexpected capability: {capability_id}")

        domains = {"tests": {"facts": {"test.score": score}}} if score is not None else {}
        context = SimpleNamespace(capabilities=child, student_context={"domains": domains})
        brief = {"stated_preference": stated, "underlying_objective": objective,
                 "country": country, "level": "bachelor", "intake": "winter 2027",
                 "family_wish": {"suggested_direction": family} if family else None}
        output = await build(context, {"brief": brief})
        roadmaps = output["roadmaps"]
        requests = ((output.get("pending_action") or {}).get("items") or [])
        checks = {
            "official_verification": verdict.status == "verified"
                and not official_url("https://example.edu.evil.test/entry", {"example.edu"}),
            "stated_goal": any(row["origin"] == "stated_goal" for row in roadmaps),
            "alternative": any(row["origin"] == "alternative" for row in roadmaps),
            "family_route": bool(any(row["origin"] == "family_wish" for row in roadmaps)) == bool(family),
            "sourced": all(row["sources"] and all(
                official_url(source["url"], {"example.edu"}) for source in row["sources"])
                for row in roadmaps),
            "one_request": len(requests) == (1 if score is None else 0),
            "deterministic_fit": all(row["fit_level"] == ("partial" if score is None else "strong")
                                     for row in roadmaps),
        }
        results.append({"persona": name, "checks": checks, "roadmaps": len(roadmaps),
                        "requests": len(requests),
                        "elapsed_ms": round((time.monotonic() - started) * 1000)})
    return results


def report_recorded(results: list[dict], path: Path) -> None:
    total = sum(len(row["checks"]) for row in results)
    passed = sum(sum(row["checks"].values()) for row in results)
    lines = ["# Offline Counselor research contract evaluation", "",
             "Synthetic recorded source pages only; no model or web API calls. This checks",
             "composition, evidence labels, and request counts. It does not measure natural",
             "conversation quality, real university coverage, or live source freshness.", "",
             f"Personas: {len(results)} | Checks: {passed}/{total} | Pass rate: {passed / total:.1%}", "",
             "| Persona | Roadmaps | Requests | Checks | Time to roadmaps |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for row in results:
        count = sum(row["checks"].values())
        lines.append(f"| {row['persona']} | {row['roadmaps']} | {row['requests']} | "
                     f"{count}/{len(row['checks'])} | {row['elapsed_ms']} ms |")
    failures = [(row["persona"], key) for row in results for key, ok in row["checks"].items() if not ok]
    lines.extend(["", "Failures: " + (", ".join(f"{name}/{key}" for name, key in failures) or "none"), ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    from datetime import datetime
    output = Path("eval_reports") / f"counselor_research_recorded_{datetime.now(timezone.utc):%Y%m%d}.md"
    rows = asyncio.run(evaluate_recorded())
    report_recorded(rows, output)
    print(output)
    if any(not all(row["checks"].values()) for row in rows):
        raise SystemExit(1)
