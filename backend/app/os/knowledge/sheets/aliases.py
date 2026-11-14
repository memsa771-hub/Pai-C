"""Import aliases (P2-T13; master R-67, R-68, R-76): an id used inside one returned file that names an entity loaded from
elsewhere (earlier in the same plan, or already in the registry).

A returned file is kept unchanged as the source record, so a second id for an entity another batch already lists is not
edited out of it: an alias file, supplied with the batch as data, says which id is which. It is bound to one returned
file by that file's sha256, and every alias carries its evidence and the same two checks as a row. Only an alias both
checks accepted is applied (`plan.resolve_aliases`), and those checks are reviewer attestations of `attest_ref`. The
import records each alias it used, with its evidence and checkers, in the import log and in each row's provenance.

Optional keys (P2-T28; old files stay valid, so the format has no version to bump):
- `required: true`, per alias or for the whole file (an alias's own value wins): the file's id must not load as an entity
  of its own. If the alias is not accepted, every row naming the id is rejected (`alias_required_not_accepted`) instead
  of loading a new, duplicate entity.
- `target_evidence: {url, quote}`: where the target itself is shown (its own page). Kept in provenance with the alias."""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

MAX_BYTES = 1_048_576  # an alias file is a short list; anything larger is not one


class AliasError(ValueError):
    """The alias file cannot be used (unreadable, malformed, or for another file). Nothing is planned or imported."""


@dataclass(frozen=True)
class Alias:
    from_id: str
    to: str
    evidence_url: str
    evidence_quote: str
    checks: dict  # in the batch checker columns' names, so `plan.read_checks` judges it like a row
    index: int  # 1-based position in the file, for the report
    required: bool = False  # not accepted: the rows naming `from_id` are rejected, never loaded as a new entity (T28)
    target_evidence: dict | None = None  # {url, quote} of the target's own page, if given (T28)


@dataclass(frozen=True)
class AliasFile:
    path: Path
    file: str  # the returned file it is for, as named in the alias file
    file_sha256: str  # sha256 of that returned file
    sha256: str  # sha256 of the alias file itself (provenance)
    aliases: tuple[Alias, ...]

    @property
    def attest_ref(self) -> str:
        """The batch ref both checkers attest (review queue) to accept its aliases: bound to this exact file."""
        return f"aliases-{self.sha256}"

    def record(self) -> dict:
        """What the import log and each row's provenance keep of it."""
        return {"alias_file": self.path.name, "alias_sha256": self.sha256, "attest_ref": self.attest_ref,
                "file": self.file, "file_sha256": self.file_sha256}


def _s(v: Any) -> str:
    if isinstance(v, bool):  # YAML 1.1 reads an unquoted yes/no as a boolean
        return "yes" if v else "no"
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return "" if v is None else str(v).strip()


def load_aliases(path: Path) -> AliasFile:
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as e:
        raise AliasError(f"alias file {path}: {e}") from e
    if len(data) > MAX_BYTES:
        raise AliasError(f"alias file {path.name}: larger than {MAX_BYTES} bytes")
    try:
        doc = yaml.safe_load(data.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as e:
        raise AliasError(f"alias file {path.name}: not YAML ({e})") from e
    if not isinstance(doc, dict) or not _s(doc.get("file")) or not _s(doc.get("sha256")):
        raise AliasError(f"alias file {path.name}: needs `file` and `sha256` of the returned file")
    items = doc.get("aliases")
    if not isinstance(items, list) or not items:
        raise AliasError(f"alias file {path.name}: needs a non-empty `aliases` list")
    file_required = doc.get("required", False)
    if not isinstance(file_required, bool):
        raise AliasError(f"alias file {path.name}: `required` is true or false")
    out: list[Alias] = []
    seen: set[str] = set()
    for i, a in enumerate(items, 1):
        where = f"alias file {path.name}, alias {i}"
        if not isinstance(a, dict):
            raise AliasError(f"{where}: not a mapping")
        ev, c1, c2 = a.get("evidence") or {}, a.get("check1") or {}, a.get("check2") or {}
        if not all(isinstance(x, dict) for x in (ev, c1, c2)):
            raise AliasError(f"{where}: `evidence`, `check1` and `check2` are mappings")
        frm, to = _s(a.get("from")), _s(a.get("to"))
        url, quote = _s(ev.get("url")), _s(ev.get("quote"))
        if not frm or not to or frm == to:
            raise AliasError(f"{where}: needs `from` and a different `to`")
        if not url.startswith(("https://", "http://")) or not quote:
            raise AliasError(f"{where}: needs `evidence` with a url and a quote")
        if frm in seen:
            raise AliasError(f"{where}: `{frm}` is aliased twice")
        seen.add(frm)
        required = a.get("required", file_required)
        if not isinstance(required, bool):
            raise AliasError(f"{where}: `required` is true or false")
        target_ev = a.get("target_evidence")
        if target_ev is not None:
            if not isinstance(target_ev, dict):
                raise AliasError(f"{where}: `target_evidence` is a mapping with a url and a quote")
            t_url, t_quote = _s(target_ev.get("url")), _s(target_ev.get("quote"))
            if not t_url.startswith(("https://", "http://")) or not t_quote:
                raise AliasError(f"{where}: `target_evidence` needs a url and a quote")
            target_ev = {"url": t_url, "quote": t_quote}
        checks = {"checker1_result": _s(c1.get("result")) or None, "checker1_name": _s(c1.get("name")) or None,
                  "checker1_date": _s(c1.get("date")) or None, "checker2_approved": _s(c2.get("approved")) or None,
                  "checker2_name": _s(c2.get("name")) or None, "checker2_date": _s(c2.get("date")) or None}
        out.append(Alias(frm, to, url, quote, checks, i, required, target_ev))
    return AliasFile(path, _s(doc["file"]), _s(doc["sha256"]).lower(), hashlib.sha256(data).hexdigest(), tuple(out))


def bind(files: list[AliasFile] | tuple[AliasFile, ...], batch_sha: str, batch_name: str) -> None:
    """Refuses alias files that are not for this returned file (by sha256), or that alias one id twice."""
    seen: dict[str, str] = {}
    for af in files:
        if af.file_sha256 != batch_sha:
            raise AliasError(f"alias file {af.path.name} is for {af.file} (sha256 {af.file_sha256[:12]}), not "
                             f"{batch_name} (sha256 {batch_sha[:12]}); nothing was imported")
        for a in af.aliases:
            if a.from_id in seen:
                raise AliasError(f"`{a.from_id}` is aliased in both {seen[a.from_id]} and {af.path.name}")
            seen[a.from_id] = af.path.name
