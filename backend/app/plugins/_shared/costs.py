"""Conservative cost arithmetic over verified and cited fee components."""

from decimal import Decimal, InvalidOperation


def route_cost(fees: dict, *, verified: bool) -> dict:
    components = []
    for fact in (fees or {}).values():
        if not isinstance(fact, dict) or not isinstance(fact.get("value"), dict):
            continue
        value = fact["value"]
        try:
            amount = Decimal(str(value["amount"]))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue
        if not amount.is_finite() or amount < 0:
            continue
        components.append({"category": fact.get("category") or "other",
                           "amount": float(amount), "currency": value.get("currency"),
                           "basis": value.get("basis"),
                           "source_url": fact.get("source_url"),
                           "status": "verified" if verified else "unconfirmed"})
    if not verified:
        return {"status": "unconfirmed", "reason": "Fees are not verified yet",
                "components": components}
    tuition = next((item for item in components if item["category"] == "tuition"), None)
    living = next((item for item in components if item["category"] == "living"), None)
    if not tuition or not living:
        return {"status": "unconfirmed",
                "reason": "Official tuition and living costs are both needed for a route total",
                "components": components}
    if (tuition["basis"] != "total" or living["basis"] != "total"
            or not tuition["currency"] or tuition["currency"] != living["currency"]):
        return {"status": "unconfirmed",
                "reason": "Cost periods or currencies differ; programme duration or a sourced conversion is needed",
                "components": components}
    return {"status": "verified", "amount": float(Decimal(str(tuition["amount"]))
                                                  + Decimal(str(living["amount"]))),
            "currency": tuition["currency"], "basis": "total", "components": components}
