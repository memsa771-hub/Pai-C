"""Keep persona examples in documentation and evaluation, never in runtime code."""

import re
import unicodedata
from pathlib import Path


def test_documented_counselor_prompt_matches_runtime_prompt():
    backend = Path(__file__).resolve().parents[1]
    docs = backend.parent / "docs"
    if not docs.exists():
        docs = Path("/docs")
    runtime = (backend / "app/pai_c/deep/prompts/counselor.md").read_text(encoding="utf-8")
    documentation = (docs / "counselor/COUNSELOR_V3_PROMPTS.md").read_text(encoding="utf-8")
    section = documentation.split("## 1.", 1)[1].split("## 2.", 1)[0]
    documented = section.split("```text\n", 1)[1].split("\n```", 1)[0]
    assert documented.rstrip() == runtime.rstrip()


def test_deep_python_modules_do_not_name_documented_personas():
    backend = Path(__file__).resolve().parents[1]
    docs = backend.parent / "docs" / "counselor"
    if not docs.exists():
        docs = Path("/docs/counselor")
    names = set()
    for document in (docs / name for name in (
        "COUNSELING_CONVERSATIONS.md", "DEEP_COUNSELING_DANISH.md",
    )):
        text = document.read_text(encoding="utf-8")
        names.update(re.findall(r"(?m)^##\s+\d+\.\s+([A-Z][a-z]+)(?=[: -])", text))
        names.update(re.findall(r"(?m)^\*\*Student:\*\*\s+([A-Z][a-z]+)", text))
    assert names, "The documentation persona inventory must be present"
    deep = backend / "app" / "pai_c" / "deep"
    assert list(deep.glob("*.py")), "Deep Counselor source must be present"
    for source in deep.glob("*.py"):
        content = source.read_text(encoding="utf-8")
        assert not any(ord(char) > 127 and unicodedata.category(char).startswith("L")
                       for char in content), f"{source.name} embeds a non-ASCII letter"
        for name in names:
            assert not re.search(rf"\b{re.escape(name)}\b", content, re.IGNORECASE), (
                f"{source.name} embeds a documentation persona"
            )
