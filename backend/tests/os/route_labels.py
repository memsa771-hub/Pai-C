"""The label test's shared helpers (P1-T9, D-z13, R-55): the word lists, the rule, and the frontend fixture builder.
The rule: a word of route X must not show on route Y unless Y's own list has it too; a route whose origin is its
destination must not say "abroad" or "visa". The lists are test data (`fixtures/route_labels.yaml`)."""

import json
import re
from pathlib import Path

import yaml

from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir

HERE = Path(__file__).resolve().parent
WORDS_FILE = HERE / "fixtures" / "route_labels.yaml"
FIXTURE_FILE = Path(__file__).resolve().parents[3] / "frontend/tests/fixtures/my-plan-routes.json"
ROUTES = ("germany_master", "ireland_master", "pakistan_bs", "pakistan_inter")
KINDS = ("country", "bodies", "documents")
ABROAD = re.compile(r"abroad|visa", re.IGNORECASE)


def load_words() -> dict[str, dict[str, list[str]]]:
    raw = yaml.safe_load(WORDS_FILE.read_text())
    assert set(raw) == set(ROUTES), set(raw) ^ set(ROUTES)
    return {route: {kind: list(raw[route].get(kind) or []) for kind in KINDS} for route in ROUTES}


def flat(words: dict, route_key: str) -> list[str]:
    return [w for kind in KINDS for w in words[route_key][kind]]


def pattern(word: str) -> re.Pattern:
    """Whole word, case-blind; a space and a hyphen in the word match each other."""
    body = r"[\s\-]+".join(re.escape(part) for part in re.split(r"[\s\-]+", word.strip()))
    return re.compile(rf"(?<![\w]){body}(?![\w])", re.IGNORECASE)


def _same(a: str, b: str) -> bool:
    return pattern(a).fullmatch(b) is not None or pattern(b).fullmatch(a) is not None


def foreign_words(route_key: str, text: str, words: dict | None = None) -> list[str]:
    """The words of other routes that `text` (shown on `route_key`) holds and the route's own list does not."""
    words = words or load_words()
    own = flat(words, route_key)
    found = []
    for other in words:
        if other == route_key:
            continue
        for word in flat(words, other):
            if any(_same(word, mine) for mine in own):
                continue
            if pattern(word).search(text) and word not in found:
                found.append(word)
    return found


def abroad_words(text: str) -> list[str]:
    """What a route that stays in one country must not say."""
    return sorted({m.group(0).lower() for m in ABROAD.finditer(text)})


# Keys whose strings are links, ids or codes the screen never shows as words.
SKIP = ("url", "source", "key", "route_key", "instance_key", "state", "kind", "inbox_kind", "due_at", "due_tz",
        "blocked_reason", "state_reason", "checked_at", "programme_ref")


def _strings(value, skip=SKIP):
    """Every string a student could read in an answer: links, codes and ids are not words."""
    if isinstance(value, str):
        if not value.startswith("http"):
            yield value
    elif isinstance(value, dict):
        for key, inner in value.items():
            if key not in skip:
                yield from _strings(inner, skip)
    elif isinstance(value, list):
        for inner in value:
            yield from _strings(inner, skip)


def all_text(*answers) -> str:
    return "\n".join(s for answer in answers for s in _strings(answer))


# ---- the frontend fixture ------------------------------------------------------------------------------------

_SAMPLE = {"date": "1 October 2027", "due": "18 June 2027", "days": 105, "weeks": 15, "days_left": 30}
_NOTES = ("note", "note_earliest", "note_passed", "note_passed_earliest")


def _citations(book, task) -> list[dict]:
    """The notes the compiler would put on the step's date (compile.py), with sample dates."""
    if task.anchor is None:
        return []
    values = {k: c.value for k, c in book.constants.items()} | _SAMPLE
    out = []
    for name in _NOTES:
        text = getattr(task.anchor, name)
        if text:
            out.append({"source": f"fact:{task.anchor.fact}", "url": f"https://source.example/{task.anchor.fact}",
                        "note": text.format(**values)})
    return out


def build_fixture() -> list[dict]:
    books = load_playbook_dir(HERE / "playbooks") | load_playbook_dir(PLAYBOOK_DIR)
    words = load_words()
    out = []
    for route_key in ROUTES:
        book = max((b for (k, _), b in books.items() if k == route_key), key=lambda b: b.version)
        items, steps = [], []
        for n, task in enumerate(book.tasks, start=1):
            steps.append({"title": task.title, "owner": "student" if task.kind == "student" else "pai"})
            if task.kind != "student":
                continue
            item = {"title": task.title, "inbox_kind": task.inbox_kind}
            cites = _citations(book, task)
            if cites:
                item["citations"] = cites
            items.append(item)
            if task.anchor and task.anchor.waiting:  # the same step while its date is missing
                items.append({"title": task.title, "inbox_kind": task.inbox_kind, "waiting_for": task.anchor.waiting,
                              "fact": task.anchor.fact})
        out.append({
            "route_key": route_key,
            "abroad": book.route.origin != book.route.destination,
            "plan": {"state": "active", "source": "self_serve", "plan_id": 1, "route_key": route_key,
                     "abroad": book.route.origin != book.route.destination,
                     "pages": [p.model_dump() for p in book.pages or []], "sources": {}},
            "items": items, "steps": steps, "words": words,
        })
    return out


def render(fixture: list[dict]) -> str:
    return json.dumps(fixture, indent=2, ensure_ascii=False) + "\n"


__all__ = ["abroad_words", "all_text", "build_fixture", "foreign_words", "load_words", "render"]
