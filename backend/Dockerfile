# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS python-deps
WORKDIR /app
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=300 \
    PYTHONPATH=/app

# psycopg2-binary ships libpq; no compiler or libpq-dev layer is needed.
# Dependency and download caches survive source-only rebuilds.
COPY requirements.txt ./
RUN --mount=type=cache,id=pai-os-pip,target=/root/.cache/pip,sharing=locked \
    pip install --prefer-binary --no-compile -r requirements.txt

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]

# Cloud-only image: select this target only when Browser Fabric is configured.
# It omits Chromium and its OS libraries, reducing cold build time and size.
FROM python-deps AS cloud
COPY . .
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

# Default image retains local Playwright/Chromium for self-hosted and fallback
# browser use. Browser installation stays cached when application code changes.
FROM python-deps AS browser-deps
RUN playwright install-deps chromium
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN --mount=type=cache,id=pai-os-playwright-shell,target=/root/.cache/playwright,sharing=locked \
    PLAYWRIGHT_BROWSERS_PATH=/root/.cache/playwright \
    playwright install --only-shell chromium \
    && mkdir -p "$PLAYWRIGHT_BROWSERS_PATH" \
    && cp -a /root/.cache/playwright/. "$PLAYWRIGHT_BROWSERS_PATH"/

FROM browser-deps AS browser
COPY . .
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh
