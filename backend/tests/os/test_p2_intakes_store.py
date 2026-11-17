"""P2-T8: intake rows, states, terms (P2-D23, R-62, R-63, R-66). Fictional region and family codes."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from app.os import models
from app.os.intakes import IntakeError, IntakeStore, UnknownTerm, check_term, terms
from tests.os.intake_helpers import make_current

pytestmark = pytest.mark.req("R-62")
AT = datetime(2027, 3, 1, tzinfo=UTC)


def test_terms_come_from_data():
    assert {"spring", "fall"} <= set(terms())
    assert check_term("winter") == "winter"
    with pytest.raises(UnknownTerm):
        check_term("monsoon")
    assert check_term("monsoon", ("monsoon",)) == "monsoon"  # a playbook's own term is accepted


def test_two_intakes_in_one_year(engine, clean):
    s = IntakeStore(engine, "pai")
    a = s.create("r_one", "undergrad", "spring", 2027)
    b = s.create("r_one", "undergrad", "fall", 2027)
    assert a.id != b.id and a.state == "planned"
    with pytest.raises(IntakeError):
        s.create("r_one", "undergrad", "fall", 2027)
    with pytest.raises(IntakeError):
        s.create("R One", "undergrad", "fall", 2028)
    with pytest.raises(UnknownTerm):
        s.create("r_one", "undergrad", "monsoon", 2027)
    assert [i.term for i in s.list_intakes(region="r_one")] == ["fall", "spring"]


def test_states_and_the_gate(engine, clean):
    s = IntakeStore(engine, "pai")
    i = s.create("r_one", "undergrad", "fall", 2027)
    with pytest.raises(IntakeError, match="gate"):
        s.set_state(i.id, "current")  # R-66: never through set_state, planned or open
    i = s.set_state(i.id, "open")
    with pytest.raises(IntakeError, match="gate"):
        s.set_state(i.id, "current")
    i = make_current(engine, i.id, AT)
    assert i.state == "current" and i.gate_passed_at == AT
    assert s.set_state(i.id, "closed").state == "closed"
    with pytest.raises(IntakeError):
        s.set_state(i.id, "open")
    with pytest.raises(IntakeError):
        s.create("r_one", "undergrad", "fall", 2028, state="current")


def test_database_refuses_current_without_a_gate(engine, clean):
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert(models.intakes).values(
            tenant_id="pai", region="r", family="f", term="fall", year=2027, state="current"))


@pytest.mark.req("R-63")
def test_plannable_and_fallback(engine, clean):
    s = IntakeStore(engine, "pai")
    assert s.plannable("fall", 2027) and not s.fallback_applies("fall", 2027)  # nobody registered it: as today
    a = s.create("r_one", "undergrad", "fall", 2027)
    assert not s.plannable("fall", 2027) and not s.fallback_applies("fall", 2027)  # planned
    s.set_state(a.id, "open")
    assert s.plannable("fall", 2027) and s.fallback_applies("fall", 2027)
    b = s.create("r_two", "undergrad", "fall", 2027, state="open")
    make_current(engine, b.id, AT)
    assert s.plannable("fall", 2027) and not s.fallback_applies("fall", 2027)
    assert s.previous("r_one", "undergrad", "fall", 2027) is None
    p = s.create("r_one", "undergrad", "fall", 2026)
    assert s.previous("r_one", "undergrad", "fall", 2027).id == p.id
    assert s.previous("r_one", "undergrad", "spring", 2027) is None
