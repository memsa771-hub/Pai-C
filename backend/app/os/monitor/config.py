"""The monitoring and report settings (monitor/config.yaml) and the approved student sentences (monitor/texts.yaml).
A missing key or a file that is not approved stops the load, not a request."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

CONFIG_FILE = Path(__file__).with_name("config.yaml")
TEXTS_FILE = Path(__file__).with_name("texts.yaml")
TEXT_KEYS = ("fact_rechecking_waiting", "report_link", "report_title", "reason_wrong_date", "reason_wrong_amount",
             "reason_page_changed", "reason_other", "report_detail_label", "report_submit", "report_thanks",
             "report_limit", "report_failed")


@dataclass(frozen=True)
class MonitorConfig:
    monitored_statuses: tuple[str, ...]
    gone_http: tuple[int, ...]
    report_reasons: tuple[str, ...]
    max_reported_facts_per_day: int
    report_text_max_chars: int
    escalate_after_reporters: int
    seen_runs_needed: int
    sanity_no_match_min_facts: int
    sanity_max_shrink_percent: int
    sanity_failures_needed: int


@cache
def load_config(path: Path = CONFIG_FILE) -> MonitorConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg = MonitorConfig(tuple(raw["monitored_statuses"]), tuple(int(c) for c in raw["gone_http"]),
                        tuple(raw["report_reasons"]), int(raw["max_reported_facts_per_day"]),
                        int(raw["report_text_max_chars"]), int(raw["escalate_after_reporters"]),
                        int(raw["seen_runs_needed"]), int(raw["sanity_no_match_min_facts"]),
                        int(raw["sanity_max_shrink_percent"]), int(raw["sanity_failures_needed"]))
    if (not cfg.report_reasons or cfg.max_reported_facts_per_day < 1 or cfg.escalate_after_reporters < 2
            or cfg.seen_runs_needed < 1 or cfg.sanity_failures_needed < 1 or not 1 <= cfg.sanity_max_shrink_percent <= 100
            or set(cfg.monitored_statuses) - {"confirmed", "verified"}):
        raise ValueError("monitor/config.yaml is not valid")
    return cfg


@cache
def load_texts(path: Path = TEXTS_FILE) -> dict[str, str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if raw.get("approved") is not True:
        raise ValueError(f"{path.name} is not approved by the owner")
    texts = raw.get("texts") or {}
    missing = [k for k in TEXT_KEYS if not isinstance(texts.get(k), str) or not texts[k].strip()]
    if missing:
        raise ValueError(f"{path.name} misses: {', '.join(missing)}")
    cfg = load_config()
    absent = [r for r in cfg.report_reasons if f"reason_{r}" not in texts]
    if absent:
        raise ValueError(f"{path.name} has no sentence for the report reasons: {', '.join(absent)}")
    return {k: texts[k] for k in TEXT_KEYS}


def text(key: str) -> str:
    return load_texts()[key]
