"""Keep persona examples in documentation and evaluation, never in runtime code."""

import re
from pathlib import Path


def test_deep_python_modules_do_not_name_documented_personas():
    root = Path(__file__).resolve().parents[2]
    docs = root / "docs" / "counselor"
    names = set()
    for document in docs.glob("*.md"):
        text = document.read_text(encoding="utf-8")
        names.update(re.findall(r"(?m)^##\s+\d+\.\s+([A-Z][a-z]+)(?=[: -])", text))
        names.update(re.findall(r"(?m)^\*\*Student:\*\*\s+([A-Z][a-z]+)", text))
    assert names, "The documentation persona inventory must be present"
    deep = root / "backend" / "app" / "counseling" / "deep"
    for source in deep.glob("*.py"):
        content = source.read_text(encoding="utf-8")
        for name in names:
            assert not re.search(rf"\b{re.escape(name)}\b", content, re.IGNORECASE), (
                f"{source.name} embeds a documentation persona"
            )
