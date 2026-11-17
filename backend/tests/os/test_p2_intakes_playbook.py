"""P2-T8: playbook versions that name their intakes (P2-D25; R-65)."""

import pytest

from app.os.playbooks import AppliesTo, Playbook, PlaybookError, select_playbook
from tests.os.test_compiler import IE

pytestmark = pytest.mark.req("R-65")


def version(n, **kw) -> Playbook:
    data = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    return Playbook.model_validate({**data, "version": n, **kw})


def books(*vs):
    return {(b.key, b.version): b for b in vs}


def pick(bs, intake=None):
    return select_playbook(bs, IE.route.origin, IE.route.destination, IE.route.level, intake=intake).version


def test_no_applies_to_is_unchanged():
    bs = books(version(1), version(2))
    assert pick(bs) == 2 and pick(bs, ("winter", 2027)) == 2


def test_newest_version_that_applies_to_the_intake():
    bs = books(version(1), version(2, applies_to={"term": "winter", "from_year": 2028}))
    assert pick(bs, ("winter", 2027)) == 1  # v2 starts with the 2028 intake
    assert pick(bs, ("winter", 2028)) == 2
    assert pick(bs, ("winter", 2030)) == 2
    assert pick(bs) == 2  # no intake given: as before


def test_term_scoped_and_any_term():
    bs = books(version(1), version(2, intake_terms=["winter", "summer"], applies_to={"term": "summer", "from_year": 2027}),
               version(3, applies_to={"from_year": 2029}))
    assert pick(bs, ("winter", 2027)) == 1
    assert pick(bs, ("summer", 2027)) == 2
    assert pick(bs, ("winter", 2029)) == 3


def test_nothing_applies_is_an_error():
    only = books(version(1, applies_to={"term": "winter", "from_year": 2030}))
    with pytest.raises(PlaybookError):
        pick(only, ("winter", 2027))


def test_bad_applies_to_refused():
    with pytest.raises(ValueError):
        AppliesTo(term="Winter", from_year=2027)
    with pytest.raises(ValueError):
        version(2, intake_terms=["winter"], applies_to={"term": "summer", "from_year": 2027})
