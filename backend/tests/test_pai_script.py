"""The pure helpers of pai.py (the one-file server deployer at the repo root)."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("pai_script", ROOT / "pai.py")
op = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(op)


def test_parse_env_skips_comments_and_strips_quotes():
    text = "# comment\nA=1\nB = 'two'\n\n# C=3\nD=\"x=y\"\n"
    assert op.parse_env(text) == {"A": "1", "B": "two", "D": "x=y"}


def test_set_env_values_replaces_in_place_uncomments_and_appends():
    text = "# head\nFRONTEND_PORT=3000\n# PROXY_NETWORK=pai-website_default\nWEB_CONCURRENCY=2\n"
    new = op.set_env_values(text, {"FRONTEND_PORT": "3001", "PROXY_NETWORK": "web_default", "NEW_KEY": "v"})
    assert new.splitlines() == ["# head", "FRONTEND_PORT=3001", "PROXY_NETWORK=web_default",
                                "WEB_CONCURRENCY=2", "NEW_KEY=v"]


def test_set_env_values_does_not_touch_keys_sharing_a_prefix():
    text = "PAI_MODEL=gpt-5-mini\nPAI_MODEL_X=keep\n"
    assert op.set_env_values(text, {"PAI_MODEL": "gpt-5"}) == "PAI_MODEL=gpt-5\nPAI_MODEL_X=keep\n"


def test_splice_block_appends_once_then_replaces():
    website = "placement-ai.com {\n\treverse_proxy web:3000\n}\n"
    once = op.splice_block(website, "app.x {\n\treverse_proxy a:1\n}")
    assert once.startswith(website)
    assert once.count(op.MARK_BEGIN) == 1 and once.count(op.MARK_END) == 1
    twice = op.splice_block(once, "app.x {\n\treverse_proxy b:2\n}")
    assert twice.count(op.MARK_BEGIN) == 1
    assert "a:1" not in twice and "b:2" in twice
    assert twice.startswith(website)


def test_splice_block_on_empty_file_has_no_leading_blank_lines():
    assert op.splice_block("", "x {\n}").startswith(op.MARK_BEGIN)


def test_render_caddy_blocks_names_both_domains_and_upstreams():
    text = op.render_caddy_blocks("127.0.0.1:3001", "127.0.0.1:8000")
    assert f"{op.APP_DOMAIN} {{" in text and f"{op.API_DOMAIN} {{" in text
    assert "reverse_proxy 127.0.0.1:3001" in text and "reverse_proxy 127.0.0.1:8000" in text
    assert text.count("max_size 50MB") == 2


@pytest.mark.parametrize("preferred,used,expected", [
    (3000, set(), 3000),
    (3000, {3000}, 3001),
    (3000, {3000, 3001, 3002}, 3003),
])
def test_pick_port(preferred, used, expected):
    assert op.pick_port(preferred, used) == expected


STOCK = """# The Caddyfile is an easy way to configure your Caddy web server.
#
:80 {
\t# Set this path to your site's directory.
\troot * /usr/share/caddy

\t# Enable the static file server.
\tfile_server

\t# reverse_proxy localhost:8080
}

# Refer to the Caddy docs for more information:
"""


def test_is_stock_caddyfile():
    assert op.is_stock_caddyfile(STOCK)
    assert op.is_stock_caddyfile("")
    assert op.is_stock_caddyfile("# only comments\n")
    assert not op.is_stock_caddyfile("placement-ai.com {\n\treverse_proxy web:3000\n}\n")
    assert not op.is_stock_caddyfile(STOCK + "\nplacement-ai.com {\n\treverse_proxy web:3000\n}\n")


def test_cli_dispatches_and_requires_a_command(monkeypatch):
    seen = {}
    monkeypatch.setattr(op, "cmd_status", lambda: seen.setdefault("ran", True))
    op.main(["--dir", str(ROOT), "status"])
    assert seen["ran"] and op.ARGS.dir == ROOT
    with pytest.raises(SystemExit):
        op.main([])
