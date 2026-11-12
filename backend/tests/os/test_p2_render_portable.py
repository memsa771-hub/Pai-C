"""P2-T4: the render module imports on hosts without POSIX `resource` (Windows), so the app and the legacy suite still
start there. The renderer is POSIX-only (own session, rlimits, process-group kill), so on such a host it says it is
not available and a render fails cleanly (the page is then marked not readable, as with no browser)."""

import importlib
import sys

import pytest

pytestmark = pytest.mark.req("R-74")


@pytest.fixture
def render_without_resource(monkeypatch):
    monkeypatch.setitem(sys.modules, "resource", None)  # `import resource` now raises ImportError
    import app.os.knowledge.research.render as render

    yield importlib.reload(render)
    monkeypatch.undo()
    importlib.reload(render)


def test_imports_and_reports_unavailable_without_resource(render_without_resource):
    renderer = render_without_resource.PlaywrightRenderer(browser_path=sys.executable)  # an existing file
    assert renderer.available() is False


def test_render_fails_cleanly_without_resource(render_without_resource):
    renderer = render_without_resource.PlaywrightRenderer(browser_path=sys.executable)
    with pytest.raises(render_without_resource.RenderFailed, match="POSIX"):
        renderer.render("https://www.alpha-university.test/notice", lambda url, lim: None)
