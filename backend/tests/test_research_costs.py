from app.plugins._shared.costs import route_cost


def test_route_total_uses_only_matching_verified_total_periods():
    fees = {
        "tuition": {"category": "tuition", "source_url": "https://example.edu/fees",
                    "value": {"amount": 12000, "currency": "GBP", "basis": "total"}},
        "living": {"category": "living", "source_url": "https://example.edu/living",
                   "value": {"amount": 4000, "currency": "GBP", "basis": "total"}},
    }
    assert route_cost(fees, verified=True)["amount"] == 16000
    assert route_cost(fees, verified=False)["status"] == "unconfirmed"
    fees["living"]["value"]["currency"] = "EUR"
    assert route_cost(fees, verified=True)["status"] == "unconfirmed"
    fees["living"]["value"]["currency"] = "GBP"
    fees["tuition"]["value"]["basis"] = "per_year"
    assert route_cost(fees, verified=True)["status"] == "unconfirmed"
