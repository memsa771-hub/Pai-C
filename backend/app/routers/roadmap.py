"""The Roadmap page API: the engine's fields for the student and their chosen
route (spec ROADMAP_ENGINE_SPEC.md §3). Reads compute on request; writes only
touch pai_route_decisions. Step colours and the time estimate are read
against the request day."""

import logging
import re
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import pai_os_bridge
from app.api.response import success_response
from app.database import get_db
from app.models import GuardianConsent
from app.pai_c.connect import age, consent, flags, guardian, places
from app.pai_c.connect.choice import ChoiceDetails
from app.services.email import mask_email
from app.pai_c.roadmap.decisions import RouteDecisionError, RouteDecisionService
from app.pai_c.roadmap.engine import RoadmapEngine
from app.routers._workspace_auth import _authorized
from app.security.event_identity import resolve_human

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/roadmap", tags=["Roadmap"])


class PlaceIn(BaseModel):
    ref: str = Field(min_length=1, max_length=200)
    rank: int = Field(ge=1, le=places.MAX_PLACES)


class IntakeIn(BaseModel):
    term: str = Field(pattern=r"^[a-z_]{1,40}$")
    year: int = Field(ge=2000, le=2200)


class ChoiceIn(BaseModel):
    """What the student picked on the choice screen (R-79) and their own consent (R-10)."""
    destination: str = Field(pattern=r"^[A-Z]{2}$")
    places: list[PlaceIn] = Field(default_factory=list, max_length=places.MAX_PLACES)
    intake: IntakeIn
    date_of_birth: str | None = Field(default=None, max_length=10)
    consent: bool
    consent_version: str = Field(min_length=1, max_length=40)  # the consent text version the screen showed
    guardian_email: str | None = Field(default=None, max_length=254)


class GiveConsentAction(BaseModel):
    consent_version: str = Field(min_length=1, max_length=40)  # the consent text version the screen showed


class ChooseAction(BaseModel):
    field_key: str = Field(min_length=1, max_length=120)
    details: ChoiceIn | None = None


class ResendAction(BaseModel):
    guardian_email: str | None = Field(default=None, max_length=254)


class StepAction(BaseModel):
    """A step is named by its key; index (its position in the live steps) is
    kept for clients written before steps had keys."""
    key: str | None = Field(default=None, min_length=1, max_length=300)
    index: int | None = Field(default=None, ge=0)
    done: bool


def _handoff_on() -> bool:
    return flags.part_on("CONNECT_HANDOFF")


def _need_handoff() -> None:
    if not _handoff_on():
        raise HTTPException(status_code=409, detail="The connection to PAI OS is not on")


def _choice_view(db, workspace_id: str) -> dict | None:
    """The live choice as the choice screen needs it: version, places, intake and the two consents."""
    row = RouteDecisionService(db).active(workspace_id)
    if row is None:
        return None
    if not row.guardian_required:
        guardian_state = "not_needed"
    else:
        guardian_state = "given" if row.guardian_authorized_at else "missing"
    view = {"version": row.decision_version, "places": list(row.places or []), "intake": row.intake,
            "destination": row.destination_country, "level": row.level, "os_supported": row.os_supported,
            "consent": {"student": "given" if row.authorized_at else "missing", "guardian": guardian_state},
            "consent_version": row.consent_version}
    if row.authorized_at is None:  # what the student reads before giving consent again (the text is None while unapproved)
        view["consent_offer"] = {"text": _usable_text(), "version": consent.current_version()}
    return view


def _usable_text() -> dict | None:
    try:
        consent.ensure_usable()
    except consent.ConsentTextNotApproved:
        return None
    return consent.texts()["student"]


def _same_text(version: str) -> None:
    """The student agreed to the text version the screen showed; a text changed since is refused (R-10)."""
    if version != consent.current_version():
        _refuse("The consent text has changed; read it again", 409)


def _consent_on_record(db, workspace_id: str) -> bool:
    """True when the live choice carries a consent. With CONNECT_HANDOFF off it is still shown, so it can be withdrawn
    (I1); a student who chose with the flag off never has one, so their answer stays as it was."""
    row = RouteDecisionService(db).active(workspace_id)
    return row is not None and (row.authorized_at is not None or row.guardian_authorized_at is not None)


def _write(action, db, workspace_id, *, with_choice: bool = False, always_choice: bool = False):
    try:
        result = action()
    except RouteDecisionError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except IntegrityError as exc:  # a concurrent choice won the one-active-route index
        db.rollback()
        raise HTTPException(status_code=409, detail="Another route was just chosen; reload the page") from exc
    db.commit()
    try:  # the choice is saved; a delivery problem is logged and the 5-minute sweep tries again
        pai_os_bridge.deliver_pending(db, workspace_id)
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("PAI OS delivery after a roadmap change failed")
    if always_choice or (with_choice and _handoff_on()):
        result = {**result, "choice": _choice_view(db, workspace_id)}
    return success_response(result)


@router.get("")
def get_roadmap(network: str = Query(...), db=Depends(get_db), x_workspace_token: str | None = Header(None),
                authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    workspace_id = str(workspace.id)
    page = RoadmapEngine(db).build(workspace_id, today=date.today())
    # Flag off: the answer stays as it was, except that a consent on record is shown so it can be withdrawn (I1).
    if page.get("chosen") is not None and (_handoff_on() or _consent_on_record(db, workspace_id)):
        page["chosen"] = {**page["chosen"], "choice": _choice_view(db, workspace_id)}
    return success_response(page)


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOB = re.compile(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$")


def _refuse(detail: str, status: int = 422):
    raise HTTPException(status_code=status, detail=detail)


def _valid_dob(text: str) -> str:
    """The date of birth as the Vault takes it (YYYY, YYYY-MM or YYYY-MM-DD, a real day, not in the future)."""
    if not _DOB.match(text):
        _refuse("The date of birth must be YYYY, YYYY-MM or YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(text + ("-01-01" if len(text) == 4 else "-01" if len(text) == 7 else ""))
    except ValueError:
        _refuse("The date of birth is not a real date")
    if parsed > date.today():
        _refuse("The date of birth cannot be in the future")
    return text


def _write_dob(db, workspace_id: str, dob: str) -> None:
    """Writes the date of birth to the Vault as the student's own statement (the Vault's own write path). Anything
    but a saved fact (the Vault may put it "in question") is refused: age is decided only from the stored value."""
    from app.routers import vault as vault_router

    answer = vault_router._write(db, workspace_id, "fact", "identity.date_of_birth", value=dob, text=dob)
    if not isinstance(answer, dict):  # the Vault refused it: an error response
        _refuse("The date of birth could not be saved")
    if (answer.get("data") or {}).get("saved") is not True:
        _refuse("Confirm your date of birth in your Vault first", 409)


def _details(db, workspace_id: str, field_key: str, body: ChoiceIn) -> tuple[ChoiceDetails, str | None]:
    """Checks the student's picks against what the screen offered and builds `ChoiceDetails`. Returns it with the
    guardian address to ask (None when the student is an adult). Writes the date of birth only when it is missing."""
    _need_handoff()
    if not body.consent:
        _refuse("Consent is needed to share the choice with your plan")
    try:
        consent.ensure_usable()
    except consent.ConsentTextNotApproved:
        _refuse("The consent text is not approved yet", 409)
    _same_text(body.consent_version)
    options = places.choice_options(db, workspace_id, field_key)
    origin, level = options["origin"], options["level"]
    if origin is None:
        _refuse("PAI does not know which country you study in now; add it to your Vault first")
    if body.destination not in {d["code"] for d in options["destinations"]}:
        _refuse("This destination is not on offer")
    if body.intake.term not in options["intake_terms"][body.destination] or body.intake.year not in options["years"]:
        _refuse("This intake is not on offer")
    ranks = sorted(p.rank for p in body.places)
    refs = [p.ref for p in body.places]
    if ranks != list(range(1, len(ranks) + 1)) or len(set(refs)) != len(refs):
        _refuse("Rank your places 1, 2, 3 ... without repeating one")
    if not body.places and pai_os_bridge.route_supported(origin, body.destination, level):
        # spec §3.2: a route PAI OS runs needs 1-5 places (C1). Without one the OS could never hear of the choice.
        _refuse("Rank at least one place. If none is on offer for this intake, pick another intake")
    if body.places:
        offered = {p["ref"] for p in places.places_for(db, workspace_id, body.destination, level,
                                                       body.intake.term, body.intake.year)}
        if not set(refs) <= offered:
            _refuse("A place you ranked is not on offer for this intake")
    stored = places.vault_value(db, workspace_id, "identity.date_of_birth")
    if not stored:  # never rewrite one that is there
        if not body.date_of_birth:
            _refuse("Your date of birth is needed")
        _write_dob(db, workspace_id, _valid_dob(body.date_of_birth.strip()))
        stored = places.vault_value(db, workspace_id, "identity.date_of_birth")
        if not stored:
            _refuse("Confirm your date of birth in your Vault first", 409)
    # Age comes only from the stored value. One that cannot be read counts as under 18 (D-i).
    minor = age.under_18(str(stored), date.today())
    minor = True if minor is None else minor
    email = None
    if minor:
        email = (body.guardian_email or "").strip().lower()
        if not _EMAIL.match(email):
            _refuse("You are under 18: a parent or guardian's email address is needed")
    now = datetime.now(timezone.utc)
    return ChoiceDetails(origin_country=origin, destination_country=body.destination, level=level,
                         places=tuple((p.ref, p.rank) for p in sorted(body.places, key=lambda p: p.rank)),
                         intake=(body.intake.term, body.intake.year), authorized_at=now,
                         guardian_required=minor, consent_version=body.consent_version), email


@router.get("/choice-options")
def choice_options(field_key: str = Query(..., min_length=1, max_length=120), network: str = Query(...),
                   db=Depends(get_db), x_workspace_token: str | None = Header(None),
                   authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    if not _handoff_on():
        return success_response({"handoff": False})
    workspace_id = str(workspace.id)
    text = _usable_text()
    dob = places.vault_value(db, workspace_id, "identity.date_of_birth")
    under_18 = None  # no stored date: the screen asks for it. One that cannot be read counts as under 18, as in choose.
    if dob:
        minor = age.under_18(str(dob), date.today())
        under_18 = True if minor is None else minor
    return success_response({**places.choice_options(db, workspace_id, field_key), "handoff": True,
                             "consent_text": text, "consent_version": consent.current_version(),
                             "needs_dob": not dob, "under_18": under_18})


@router.get("/places")
def offered_places(destination: str = Query(...), level: str = Query(...), term: str = Query(...),
                   year: int = Query(...), network: str = Query(...), db=Depends(get_db), x_workspace_token: str | None = Header(None),
                   authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)  # sign-in is checked before the values
    if not _handoff_on():
        return success_response({"handoff": False, "places": []})
    if not (re.fullmatch(r"[A-Z]{2}", destination) and re.fullmatch(r"[a-z_]{1,40}", term)
            and re.fullmatch(r"[a-z_]{1,40}", level) and 2000 <= year <= 2200):
        _refuse("Destination, level, term or year is not valid")
    return success_response({"handoff": True, "places": places.places_for(
        db, str(workspace.id), destination, level, term, year)})


def _request_guardian(db, workspace_id: str, email: str) -> bool:
    """Asks the guardian after the choice is saved. False when the address was asked too often (the choice stays)."""
    row = RouteDecisionService(db).newest(workspace_id)
    try:
        guardian.request(db, workspace_id, row, email)
        db.commit()
    except Exception as exc:  # noqa: BLE001 - the choice is saved; whatever goes wrong here must not turn into a 500
        db.rollback()
        if not isinstance(exc, guardian.GuardianRateLimited):
            log.warning("guardian request failed for %s: %s", mask_email(email), type(exc).__name__)
        return False
    return True


@router.post("/choose")
def choose_route(body: ChooseAction, network: str = Query(...), db=Depends(get_db),
                 x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    workspace_id = str(workspace.id)
    if body.details is None:
        return _write(lambda: RouteDecisionService(db).choose(workspace_id, body.field_key), db, workspace_id,
                      with_choice=True)
    details, email = _details(db, workspace_id, body.field_key, body.details)
    answer = _write(lambda: RouteDecisionService(db).choose(workspace_id, body.field_key, details), db,
                    workspace_id, with_choice=True)
    if email:
        answer["data"]["guardian_email_sent"] = _request_guardian(db, workspace_id, email)
    return answer


def _consent_change(db, workspace_id: str, **change):
    return _write(lambda: RouteDecisionService(db).update_consent(workspace_id, **change), db, workspace_id,
                  always_choice=True)


@router.post("/consent/withdraw")
def withdraw_consent(network: str = Query(...), db=Depends(get_db), x_workspace_token: str | None = Header(None),
                     authorization: str | None = Header(None)):
    """The student withdraws their own consent: a new version, the plan pauses. Never blocked: not by the text gate,
    not by CONNECT_HANDOFF (an OS plan may still run with the flag off; I1). Delivery follows the flag and the sweep."""
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return _consent_change(db, str(workspace.id), authorized_at=None)


@router.post("/consent/give")
def give_consent(body: GiveConsentAction, network: str = Query(...), db=Depends(get_db),
                 x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    _need_handoff()
    try:
        consent.ensure_usable()
    except consent.ConsentTextNotApproved:
        _refuse("The consent text is not approved yet", 409)
    _same_text(body.consent_version)
    return _consent_change(db, str(workspace.id), authorized_at=datetime.now(timezone.utc),
                           consent_version=body.consent_version)


@router.post("/guardian/resend")
def resend_guardian(body: ResendAction | None = None, network: str = Query(...), db=Depends(get_db),
                    x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    """Sends the guardian a new link for the live choice: an agree link, to the address on file or to a new one; once
    the guardian has agreed, a fresh withdraw link to the address that agreed (the old one stays valid)."""
    workspace = _authorized(db, network, x_workspace_token, authorization)
    workspace_id = str(workspace.id)
    row = RouteDecisionService(db).active(workspace_id)
    if row is not None and row.guardian_required and row.guardian_authorized_at is not None:
        # The guardian has agreed: a fresh withdraw link goes to the address that agreed, never to a new one (I3).
        # It serves a withdrawal, so like the withdraw link itself it works whatever CONNECT_HANDOFF says (I1).
        try:
            sent = guardian.resend_withdraw(db, workspace_id)
        except guardian.GuardianRateLimited:
            db.rollback()
            raise HTTPException(status_code=429, detail="Too many requests; try again later") from None
        except guardian.GuardianRequestError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        db.commit()
        return success_response({"sent": sent, "kind": "withdraw"})
    _need_handoff()
    if row is None:
        _refuse("No route is chosen", 404)
    if not row.guardian_required:
        _refuse("This choice needs no guardian agreement", 409)
    if row.authorized_at is None:
        _refuse("Give your own consent first", 409)
    email = ((body.guardian_email if body else None) or "").strip().lower()
    if not email:
        email = db.scalar(select(GuardianConsent.email).where(
            GuardianConsent.workspace_id == workspace_id, GuardianConsent.purpose == guardian.AGREE)
            .order_by(GuardianConsent.created_at.desc()).limit(1)) or ""
    if not _EMAIL.match(email):
        _refuse("A parent or guardian's email address is needed")
    try:
        guardian.request(db, workspace_id, row, email)
    except guardian.GuardianRateLimited:
        db.rollback()
        raise HTTPException(status_code=429, detail="Too many requests; try again later") from None
    except guardian.GuardianRequestError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except consent.ConsentTextNotApproved:
        db.rollback()
        raise HTTPException(status_code=409, detail="The consent text is not approved yet") from None
    db.commit()
    return success_response({"sent": True, "kind": "agree"})


@router.post("/steps")
def tick_step(body: StepAction, network: str = Query(...), db=Depends(get_db),
              x_workspace_token: str | None = Header(None), authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    # A step of the OS plan is completed in PAI OS, which needs a signed-in student; asked only for those steps.
    return _write(lambda: RouteDecisionService(db).set_step(
        str(workspace.id), body.done, key=body.key, index=body.index,
        is_human=lambda: resolve_human(db, workspace, authorization) is not None), db, str(workspace.id))


@router.post("/withdraw")
def withdraw_route(network: str = Query(...), db=Depends(get_db), x_workspace_token: str | None = Header(None),
                   authorization: str | None = Header(None)):
    workspace = _authorized(db, network, x_workspace_token, authorization)
    return _write(lambda: RouteDecisionService(db).withdraw(str(workspace.id)), db, str(workspace.id))
