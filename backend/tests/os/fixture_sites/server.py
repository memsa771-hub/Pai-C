"""A local server for fictional, official-looking sites (P2 spec §5 "no data from memory"; P2-T1).

Every site is a `.test` host (RFC 2606, never resolvable) defined in `sites/*.yaml`. The server listens on 127.0.0.1 and
routes by the `Host` header. `client()` returns an `httpx.Client` whose transport sends `https://<host>/<path>` to the
local port with the original host, so `PageGateway(client=sites.client())` reads the fake sites as if they were real.
`set_page` changes a page while a test runs (monitoring, T7); `reset` restores the files' contents.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import yaml

SITES_DIR = Path(__file__).with_name("sites")


@dataclass
class Resource:
    body: bytes
    content_type: str = "text/html; charset=utf-8"
    status: int = 200
    location: str | None = None  # for a redirect


def load_sites(directory: Path = SITES_DIR) -> dict[str, dict[str, Resource]]:
    sites: dict[str, dict[str, Resource]] = {}
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        host = data["host"]
        if not host.endswith(".test"):
            raise ValueError(f"{path.name}: fixture hosts must end in .test")
        if host in sites:
            raise ValueError(f"{path.name}: host {host} defined twice")
        pages = {}
        for p, spec in (data.get("pages") or {}).items():
            pages[p] = Resource(str(spec.get("body", "")).encode("utf-8"),
                                spec.get("content_type", "text/html; charset=utf-8"),
                                int(spec.get("status", 200)), spec.get("location"))
        sites[host] = pages
    return sites


class FixtureSites:
    def __init__(self, directory: Path = SITES_DIR) -> None:
        self._directory = directory
        self._lock = threading.Lock()
        self._sites = load_sites(directory)
        self.requests: list[tuple[str, str]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                host = (self.headers.get("Host") or "").split(":")[0].lower()
                path = urlsplit(self.path).path or "/"
                with owner._lock:
                    owner.requests.append((host, path))
                    res = owner._sites.get(host, {}).get(path)
                if res is None:
                    res = Resource(b"not found", "text/plain", 404)
                self.send_response(res.status)
                self.send_header("Content-Type", res.content_type)
                self.send_header("Content-Length", str(len(res.body)))
                if res.location:
                    self.send_header("Location", res.location)
                self.end_headers()
                self.wfile.write(res.body)

            def log_message(self, *args) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> FixtureSites:
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()

    @property
    def hosts(self) -> list[str]:
        return sorted(self._sites)

    @staticmethod
    def url(host: str, path: str = "/") -> str:
        return f"https://{host}{path}"

    def set_page(self, host: str, path: str, body: str | bytes, content_type: str = "text/html; charset=utf-8",
                 status: int = 200) -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        with self._lock:
            self._sites.setdefault(host, {})[path] = Resource(data, content_type, status)

    def reset(self) -> None:
        with self._lock:
            self._sites = load_sites(self._directory)
            self.requests.clear()

    def client(self, **kwargs) -> httpx.Client:
        kwargs.setdefault("follow_redirects", True)
        kwargs.setdefault("timeout", 5.0)
        return httpx.Client(transport=_LocalTransport(self.port), **kwargs)


class _LocalTransport(httpx.BaseTransport):
    """Sends every request to the local server, keeping the original host in the Host header."""

    def __init__(self, port: int) -> None:
        self._port = port
        self._inner = httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        request.read()
        if not host.endswith(".test"):
            raise httpx.ConnectError(f"fixture sites refuse non-fixture host {host}", request=request)
        local = request.url.copy_with(scheme="http", host="127.0.0.1", port=self._port)
        headers = [(k, v) for k, v in request.headers.raw if k.lower() != b"host"] + [(b"Host", host.encode())]
        forwarded = httpx.Request(request.method, local, headers=headers, content=request.content)
        response = self._inner.handle_request(forwarded)
        response.read()
        return httpx.Response(response.status_code, headers=response.headers, content=response.content,
                              request=request)

    def close(self) -> None:
        self._inner.close()
