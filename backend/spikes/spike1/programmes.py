"""The programme list the agent gets: names, start URLs and official domains. Never the answers.

Production gets the same from the programme list's `programme_page_url` (design §2).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from spikes.spike1.pages import SHARED_OFFICIAL, registrable

KEY_PATH = Path(__file__).parents[2] / "tests" / "os" / "quality" / "spike1_answer_key.yaml"

# Universities whose answer-key sources are DAAD only: their own domain still counts as official.
EXTRA_DOMAINS = {
    "saarland-embedded-systems": ("uni-saarland.de",),
    "tu-ilmenau-research-computer-systems-engineering": ("tu-ilmenau.de",),
    "tu-dortmund-automation-robotics": ("tu-dortmund.de",),
}


# Extra start pages where the answer key's links are dead (HTTP 404 on 2026-10-19). These are pages
# seen in the dry run, not guesses; the developers should add each programme's own page.
_HSRW = ("https://www.hochschule-rhein-waal.de/en/academics/prospective-students/current-application-period/masters-programmes",
         "https://www.hochschule-rhein-waal.de/en/study/before-starting-university/application-process/masters-degrees")
EXTRA_START_URLS = {
    "hsrw-mechanical-engineering": _HSRW,
    "hsrw-information-engineering-computer-science": _HSRW,
}


@dataclass(frozen=True)
class Programme:
    ref: str
    university: str
    programme: str
    start_urls: tuple[str, ...]
    domains: tuple[str, ...]  # the university's own; uni-assist and DAAD are added by is_official


def load_key(path: Path = KEY_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["programmes"]


def load_programmes(path: Path = KEY_PATH) -> list[Programme]:
    out = []
    for ref, p in load_key(path).items():
        hosts = {registrable(urlsplit(u).hostname or "") for u in p["sources"]}
        own = tuple(sorted(hosts - set(SHARED_OFFICIAL))) + EXTRA_DOMAINS.get(ref, ())
        starts = tuple(p["sources"]) + EXTRA_START_URLS.get(ref, ())
        out.append(Programme(ref, p["university"], p["programme"], starts, own))
    return sorted(out, key=lambda x: x.ref)
