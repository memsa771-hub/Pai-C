from pathlib import Path

import pytest

from app.os.playbooks import load_playbook_dir
from app.os.playbooks.loader import select_playbook

pytestmark = pytest.mark.req("R-41")

FAKE = Path(__file__).parent / "playbooks"


def test_fake_intermediate_route_loads():
    books = load_playbook_dir(FAKE)
    assert ("pakistan_inter", 1) in books
    book = select_playbook(books, "PK", "PK", "intermediate")
    assert book.key == "pakistan_inter"
    assert not any("visa" in t.template_key for t in book.tasks)
    assert book.default_timezone == "Asia/Karachi"
