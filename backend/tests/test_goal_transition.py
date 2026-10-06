"""Parked goals need a reviewed route and explicit student choice."""

import asyncio
from unittest.mock import AsyncMock, patch

from app.counseling.goal_transition import confirms_reviewed_route, reviewed_route


def test_route_review_and_confirmation_fail_closed():
    with patch("app.counseling.goal_transition.chat_completion",
               new=AsyncMock(return_value="not json")):
        reviewed = asyncio.run(reviewed_route(
            "You should choose this.", goal_title="Study computing", known_context={}))
        confirmed = asyncio.run(confirms_reviewed_route(
            "Maybe", goal_title="Study computing", previous_reply="Choose this."))
    assert reviewed is False
    assert confirmed is False


def test_route_confirmation_requires_positive_semantic_review():
    with patch("app.counseling.goal_transition.chat_completion",
               new=AsyncMock(return_value='{"yes": true}')):
        assert asyncio.run(confirms_reviewed_route(
            "Yes, I want to pursue that route", goal_title="Study computing",
            previous_reply="We discussed the route and its gaps."))
