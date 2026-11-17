"""The process that runs the headless browser (P2-T4). It is started by `render.py` in its own session, with resource
limits and, when the worker runs as root, as an unprivileged user. It is a STANDALONE script (standard library and
Playwright only; it imports nothing from `app`), because the unprivileged user may not be able to read the application.

Talk to the parent over stdin/stdout, one JSON object per line:
  child -> parent  {"op": "get", "url": ...}                  the browser wants this URL
  parent -> child  {"refused": true} | {"status", "headers", "body_b64"}
  child -> parent  {"op": "done", "html": ..., "url": ...} | {"op": "error", "message": ...}

The browser has no network of its own: every request is answered by the parent (see `render.py`).
"""

import base64
import json
import sys


def send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> None:
    cfg = json.loads(sys.argv[1])
    try:
        from playwright.sync_api import sync_playwright

        def handle(route) -> None:
            req = route.request
            if req.method != "GET":
                route.abort("blockedbyclient")
                return
            send({"op": "get", "url": req.url})
            answer = json.loads(sys.stdin.readline() or '{"refused": true}')
            if answer.get("refused"):
                route.abort("blockedbyclient")
                return
            route.fulfill(status=answer["status"], headers=answer["headers"], body=base64.b64decode(answer["body_b64"]))

        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=cfg["executable"], args=cfg["args"])
            context = browser.new_context(service_workers="block", user_agent=cfg["user_agent"])
            context.add_init_script(cfg["init_script"])
            context.route("**/*", handle)
            page = context.new_page()
            page.set_default_timeout(cfg["timeout_ms"])  # `content()` takes no timeout of its own: it uses this default
            page.goto(cfg["url"], wait_until="networkidle", timeout=cfg["timeout_ms"])
            send({"op": "done", "html": page.content(), "url": page.url})
            browser.close()
    except Exception as e:  # noqa: BLE001  (whatever went wrong, the parent hears it as one line)
        send({"op": "error", "message": f"{type(e).__name__}: {str(e).splitlines()[0][:160] if str(e) else ''}"})


if __name__ == "__main__":
    main()
