"""P2-T5: the reviewer script adds, lists, disables and re-keys reviewers without SQL (P2-D15)."""

import pytest

from app.os.knowledge.review import ReviewerStore
from scripts import os_reviewers

pytestmark = pytest.mark.req("R-42")


def run(engine, *args):
    lines: list[str] = []
    code = os_reviewers.main(list(args), engine=engine, tenant_id="pai", out=lines.append)
    return code, lines


def test_add_prints_a_working_token_once_and_list_never_shows_it(engine, clean, capsys):
    code, out = run(engine, "add", "--ref", "ai_check_1", "--name", "AI check 1", "--role", "checker", "--kind", "ai",
                   "--identity", "model-a/prompt-1")
    assert code == 0
    token = out[0].split("shown once): ")[1]
    r = ReviewerStore(engine, "pai").authenticate(token)
    assert (r.ref, r.role, r.kind, r.identity) == ("ai_check_1", "checker", "ai", "model-a/prompt-1")
    _, listed = run(engine, "list")
    assert listed == ["ai_check_1\tAI check 1\tchecker\tai\tmodel-a/prompt-1\tactive"] and token not in "".join(listed)


def test_disable_enable_rotate(engine, clean):
    _, out = run(engine, "add", "--ref", "amina", "--name", "Amina", "--role", "approver")
    old = out[0].split("shown once): ")[1]
    store = ReviewerStore(engine, "pai")
    assert run(engine, "disable", "--ref", "amina")[0] == 0 and store.authenticate(old) is None
    assert run(engine, "enable", "--ref", "amina")[0] == 0 and store.authenticate(old) is not None
    _, rotated = run(engine, "rotate", "--ref", "amina")
    new = rotated[0].split("shown once): ")[1]
    assert store.authenticate(old) is None and store.authenticate(new).ref == "amina"


def test_refusals_exit_2(engine, clean, capsys):
    run(engine, "add", "--ref", "amina", "--name", "Amina", "--role", "checker")
    assert run(engine, "add", "--ref", "amina", "--name", "Again", "--role", "checker")[0] == 2
    assert run(engine, "add", "--ref", "Bad Ref", "--name", "X", "--role", "checker")[0] == 2
    assert run(engine, "disable", "--ref", "nobody")[0] == 2
    assert run(engine, "rotate", "--ref", "nobody")[0] == 2
    assert "refused" in capsys.readouterr().err


def test_ai_reviewer_needs_an_identity_and_a_person_equal_to_ref_gets_a_warning(engine, clean, capsys):
    assert run(engine, "add", "--ref", "ai_x", "--name", "AI X", "--role", "checker", "--kind", "ai")[0] == 2
    assert "identity" in capsys.readouterr().err
    assert run(engine, "add", "--ref", "amina", "--name", "Amina", "--role", "checker")[0] == 0
    assert "warning: the identity of amina is its ref" in capsys.readouterr().err
    assert run(engine, "add", "--ref", "ai_y", "--name", "AI Y", "--role", "checker", "--kind", "ai",
               "--identity", " Model-Y/P1 ")[0] == 0
    assert "warning" not in capsys.readouterr().err
    assert run(engine, "list")[1][-1].split("\t")[4] == "model-y/p1"
