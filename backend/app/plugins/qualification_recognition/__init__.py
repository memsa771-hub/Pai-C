"""Data-driven qualification procedure discovery, never an automatic equivalence verdict."""

import json
from pathlib import Path

from app.capabilities import CapabilityContract, CapabilityRisk, FallbackPolicy


PACKS = Path(__file__).parent / "packs"


async def recognize(context, payload):
    countries = {str(payload["country"]).strip().lower(),
                 str(payload.get("origin_country") or "").strip().lower()}
    packs = {json.loads(path.read_text(encoding="utf-8"))["country"].lower(): path
             for path in PACKS.glob("*.json")}
    selected = [packs[key] for key in sorted(countries) if key in packs]
    if not selected:
        return {"procedures": [], "recognition": "unknown", "unconfirmed": [
            {"reason": "No country pack installed for this destination"}]}
    procedures = []
    for path in selected:
        pack = json.loads(path.read_text(encoding="utf-8"))
        procedures.extend({**item, "country": pack["country"],
                           "last_reviewed_at": pack.get("last_reviewed_at")}
                          for item in pack["document_procedures"])
    return {"procedures": procedures, "recognition": "unknown", "unconfirmed": [
        {"reason": "Qualification recognition requires a program-scoped official assessment"}]}


def get_capabilities():
    return [CapabilityContract(
        id="qualification.recognize", version="1.0.0", name="Qualification recognition",
        description="Identify official recognition procedures from country data without deciding eligibility.",
        input_schema={"type": "object", "properties": {
            "country": {"type": "string"}, "origin_country": {"type": "string"},
            "qualification": {"type": "object"}},
            "required": ["country"]},
        output_schema={"type": "object", "properties": {
            "procedures": {"type": "array"}, "recognition": {"type": "string"},
            "unconfirmed": {"type": "array"}},
            "required": ["procedures", "recognition", "unconfirmed"]},
        handler=recognize, owns_task_types=frozenset({"qualification_recognition"}),
        fallback_policy=FallbackPolicy.FORBIDDEN,
        vault_scopes=frozenset({"education"}), permissions=frozenset(),
        required_tools=frozenset(), risk=CapabilityRisk.READ, timeout_seconds=10,
        evidence_expectations={"procedures": "official source URL; no equivalence inference"},
    )]
