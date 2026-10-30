"""Email templates (Slice 9b): `str.format` texts in templates.yaml, checked at load time, rendered at send time.

No template engine (requirements are shared). A template may use only its kind's fields (FIELDS); a missing
template, an unknown field or a broken placeholder fails `load_templates`, so the worker does not start with them.
A row whose payload cannot be rendered (an unknown template, a missing payload field) is `Unrenderable` at send time:
the outbox marks it `failed`."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from string import Formatter
from typing import TYPE_CHECKING
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

if TYPE_CHECKING:
    from app.os.outbox.outbox import OutboxMessage

TEMPLATES_PATH = Path(__file__).with_name("templates.yaml")
INBOX_SLOTS = ("w", "d3", "d", "h12", "esc")  # workers/reminders.reminder_slot's prefixes
FIELDS = {"inbox_reminder": {"title", "due"}, "replan_request": set()}
REQUIRED = (*(f"inbox_reminder.{s}" for s in INBOX_SLOTS), "replan_request")
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


class TemplateError(ValueError):
    """templates.yaml is incomplete or broken: the worker must not start."""


class Unrenderable(Exception):
    """This row cannot be rendered (unknown template, missing payload field). Carries only a short reason."""


def _fields(text: str, where: str) -> set[str]:
    try:
        return {name for _, name, _, _ in Formatter().parse(text) if name is not None}
    except ValueError as e:
        raise TemplateError(f"{where}: broken placeholder ({e})") from None


def _check(text: object, allowed: set[str], where: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise TemplateError(f"{where} is missing or empty")
    unknown = _fields(text, where) - allowed
    if unknown:
        raise TemplateError(f"{where} uses unknown field(s) {sorted(unknown)}; allowed: {sorted(allowed)}")
    try:
        text.format(**{f: "x" for f in allowed})
    except (ValueError, IndexError, KeyError) as e:
        raise TemplateError(f"{where}: does not format ({type(e).__name__})") from None
    return text


def format_due(due_at: str, due_tz: str | None) -> str:
    """E.g. 'Friday 16 July 2027, 23:59 (Asia/Tokyo)': the due date in the task's own time zone (invariant 13)."""
    tz_name = due_tz or "UTC"
    try:
        tz = ZoneInfo(tz_name)
        when = datetime.fromisoformat(due_at)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise Unrenderable("bad due date or time zone") from None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    d = when.astimezone(tz)
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}, {d:%H:%M} ({tz_name})"


@dataclass(frozen=True)
class EmailTemplates:
    greeting: str
    footer: str
    link: str
    no_link: str
    inbox_path: str
    templates: dict[str, tuple[str, str]]  # name -> (subject, body)

    def _name(self, msg: "OutboxMessage") -> str:
        if msg.template == "inbox_reminder":
            slot = str(msg.payload.get("slot") or "")
            return f"inbox_reminder.{slot.partition(':')[0]}"
        return msg.template

    def _values(self, msg: "OutboxMessage") -> dict[str, str]:
        p = msg.payload
        if msg.template == "inbox_reminder":
            if not p.get("title") or not p.get("due_at"):
                raise Unrenderable("inbox_reminder needs title and due_at")
            return {"title": str(p["title"]), "due": format_due(p["due_at"], p.get("due_tz"))}
        return {}

    def render(self, msg: "OutboxMessage", app_url: str | None) -> tuple[str, str]:
        """(subject, plain-text body). Uses only the payload fields FIELDS allows: never documents or AI text."""
        name = self._name(msg)
        if name not in self.templates:
            raise Unrenderable(f"no template for {msg.template!r}")
        subject, body = self.templates[name]
        values = self._values(msg)
        if app_url:
            url = app_url.rstrip("/") + self.inbox_path.format(student_ref=quote(msg.recipient, safe=""))
            link = self.link.format(inbox_url=url)
        else:
            link = self.no_link
        text = "\n\n".join([self.greeting, body.format(**values).strip(), link, "--", self.footer.strip()])
        return " ".join(subject.format(**values).split()), text + "\n"


def load_templates(path: Path = TEMPLATES_PATH) -> EmailTemplates:
    try:
        raw = yaml.safe_load(Path(path).read_text())
    except (OSError, yaml.YAMLError) as e:
        raise TemplateError(f"email templates cannot be read ({type(e).__name__})") from None
    if not isinstance(raw, dict) or not isinstance(raw.get("templates"), dict):
        raise TemplateError("email templates: a `templates` mapping is required")
    found = raw["templates"]
    missing = [n for n in REQUIRED if n not in found]
    extra = [n for n in found if n not in REQUIRED]
    if missing or extra:
        raise TemplateError(f"email templates: missing {missing}, unknown {extra}")
    templates = {}
    for name in REQUIRED:
        t = found[name] if isinstance(found[name], dict) else {}
        allowed = FIELDS[name.partition(".")[0]]
        templates[name] = (_check(t.get("subject"), allowed, f"{name}.subject"),
                           _check(t.get("body"), allowed, f"{name}.body"))
    return EmailTemplates(
        greeting=_check(raw.get("greeting"), set(), "greeting"),
        footer=_check(raw.get("footer"), set(), "footer"),
        link=_check(raw.get("link"), {"inbox_url"}, "link"),
        no_link=_check(raw.get("no_link"), set(), "no_link"),
        inbox_path=_check(raw.get("inbox_path"), {"student_ref"}, "inbox_path"),
        templates=templates,
    )
