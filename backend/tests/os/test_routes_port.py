"""P1-T3 Task 2: the PlanQuery `routes()` port lists the routes the loaded playbooks serve, with their intake terms
(D-g). Fictional test playbooks plus the shipped Germany route."""

from pathlib import Path

import pytest

from app.os import ports
from app.os.playbooks import load_playbook_dir
from app.os.ports import plan_query

pytestmark = pytest.mark.req("R-79")

FAKE = Path(__file__).parent / "playbooks"


@pytest.fixture
def mounted(engine, clean, os_db):
    from app.os.api.services import make_services
    from app.os.settings import load_settings

    svc = make_services(load_settings({"OS_DATABASE_URL": os_db}), engine=engine,
                        playbooks=load_playbook_dir(FAKE) | load_playbook_dir())
    ports.configure(svc)
    try:
        yield svc
    finally:
        ports.configure(None)


def by_key(rows):
    return {r["key"]: r for r in rows}


def test_routes_lists_every_loaded_route_with_terms(mounted):
    rows = by_key(plan_query.routes())
    assert set(rows) >= {"germany_master", "ireland_master", "pakistan_bs", "pakistan_inter"}
    de = rows["germany_master"]
    assert (de["origin"], de["destination"], de["level"]) == ("PK", "DE", "master")
    assert de["intake_terms"] == ["winter"]
    assert rows["ireland_master"]["intake_terms"] == ["winter"]
    assert set(de) == {"key", "origin", "destination", "level", "intake_terms"}


def test_routes_uses_newest_version_once_per_key(mounted):
    keys = [r["key"] for r in plan_query.routes()]
    assert len(keys) == len(set(keys))


def test_intake_terms_default_is_empty():
    from app.os.playbooks.models import Playbook

    base = dict(key="k", version=1, route={"origin": "AA", "destination": "BB", "level": "x"},
                default_timezone="UTC", tasks=[])
    assert Playbook(**base).intake_terms == []
    assert Playbook(**base, intake_terms=["winter"]).intake_terms == ["winter"]


def test_intake_terms_are_plain_lowercase_words():
    from app.os.playbooks.models import Playbook

    base = dict(key="k", version=1, route={"origin": "AA", "destination": "BB", "level": "x"},
                default_timezone="UTC", tasks=[])
    with pytest.raises(ValueError):
        Playbook(**base, intake_terms=["Winter 2027"])


def test_routes_empty_when_os_not_mounted():
    ports.configure(None)
    with pytest.raises(ports.OsUnavailable):
        plan_query.routes()
