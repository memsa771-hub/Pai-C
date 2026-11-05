"use client";
/** The choice screens (R-79, R-10): country, intake, places in order, date of birth if PAI has none, consent,
 * and a parent or guardian email under 18. Shown only when the API says the hand-off is on; with it off the
 * Roadmap keeps its one-click choose. Countries, terms, years, places and the consent text all come from the API.
 * Intake comes before places because the places on offer depend on the intake. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Check, Loader2, X } from "lucide-react";
import { workspaceApi } from "@/lib/api";
import type { ChoiceDetails, ChoiceOptions, ChooseAnswer, FieldCard, OfferedPlace } from "@/lib/roadmap";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/responsive-dialog";
import { DobPicker } from "@/components/onboarding/dob-picker";
import { cn } from "@/lib/utils";
import { GuardianResend } from "./choice-consent";
import { ageOf, apiError, placeName, termLabel, UNDER_18_DETAIL, VAULT_DOB_DETAIL } from "./choice-text";
import { fill } from "./roadmap-text";
import copy from "./copy.json";

const t = copy.roadmap.choice;
const MAX_PLACES = 5;
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
type StepId = "destination" | "intake" | "places" | "dob" | "consent" | "guardian";
type Errors = Partial<Record<"destination" | "term" | "year" | "places" | "dob" | "consent" | "guardian", string>>;
type PlacesState = { status: "loading" | "ready" | "error"; list: OfferedPlace[] };

const FIELD = "h-11 w-full rounded-xl border border-input bg-background px-3 text-sm aria-invalid:border-danger focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/30";
const ROW = "flex min-h-12 cursor-pointer items-center gap-3 rounded-2xl border-2 border-border px-4 py-2 has-[:checked]:border-primary has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60";

function FieldError({ id, message }: { id: string; message?: string }) {
  return message ? <p id={id} role="alert" className="mt-2 text-sm font-medium text-danger-ink">{message}</p> : null;
}

export function ChoiceFlow({ card, options, onSaved, onClose, onOpenVault }: {
  card: FieldCard;
  options: Extract<ChoiceOptions, { handoff: true }>;
  /** The choice is saved: the page reloads. */
  onSaved: (answer: ChooseAnswer) => void | Promise<void>;
  onClose: () => void;
  onOpenVault?: () => void;
}) {
  const [index, setIndex] = useState(0),
    [destination, setDestination] = useState(options.preselected_destination ?? ""),
    [term, setTerm] = useState(""), [year, setYear] = useState(""),
    [selected, setSelected] = useState<string[]>([]),
    [places, setPlaces] = useState<PlacesState>({ status: "loading", list: [] }),
    [dob, setDob] = useState(""), [agreed, setAgreed] = useState(false), [email, setEmail] = useState(""),
    [serverMinor, setServerMinor] = useState(false), [resent, setResent] = useState(false),
    [moved, setMoved] = useState<{ ref: string; dir: "up" | "down" } | null>(null),
    [errors, setErrors] = useState<Errors>({}), [formError, setFormError] = useState(""), [vaultNote, setVaultNote] = useState(false),
    [busy, setBusy] = useState(false), [saved, setSaved] = useState<ChooseAnswer | null>(null),
    [focus, setFocus] = useState<{ field: string; n: number } | null>(null), [retry, setRetry] = useState(0);
  const body = useRef<HTMLDivElement>(null);

  const termOk = (options.intake_terms[destination] ?? []).includes(term);
  const chosen = options.destinations.find((d) => d.code === destination);
  const minorByDob = options.needs_dob && dob !== "" && (ageOf(dob) ?? 99) < 18;
  const guardianNeeded = options.under_18 === true || minorByDob || serverMinor;
  const ids: StepId[] = useMemo(() => ["destination", "intake", "places", ...(options.needs_dob ? ["dob" as const] : []),
    "consent", ...(guardianNeeded ? ["guardian" as const] : [])], [options.needs_dob, guardianNeeded]);
  const step = ids[Math.min(index, ids.length - 1)];
  const last = index >= ids.length - 1;

  const headingRef = useRef<HTMLHeadingElement>(null), firstRender = useRef(true);
  // Next and Back move focus to the new step's heading (declared before the error focus so an error still wins).
  useEffect(() => {
    if (firstRender.current) { firstRender.current = false; return; }
    headingRef.current?.focus();
  }, [index]);
  useEffect(() => {
    if (!focus) return;
    const el = body.current?.querySelector<HTMLElement>(`[data-field="${focus.field}"]`);
    el?.focus();
  }, [focus]);

  // The places on offer depend on the country and the intake.
  useEffect(() => {
    if (step !== "places" || !destination || !termOk || !year) return;
    let alive = true;
    setPlaces({ status: "loading", list: [] });
    workspaceApi.places(destination, options.level, term, Number(year))
      .then((r) => { if (alive) { setPlaces({ status: "ready", list: r.places }); setSelected((s) => s.filter((ref) => r.places.some((p) => p.ref === ref))); } })
      .catch(() => { if (alive) setPlaces({ status: "error", list: [] }); });
    return () => { alive = false; };
  }, [step, destination, term, termOk, year, options.level, retry]);

  const fail = (next: Errors) => {
    setErrors(next);
    const first = Object.keys(next)[0];
    if (first) setFocus({ field: first, n: Date.now() });
    return Object.keys(next).length === 0;
  };

  function check(id: StepId): boolean {
    if (id === "destination") return fail(destination ? {} : { destination: t.destination.required });
    if (id === "intake") return fail({ ...(termOk ? {} : { term: t.intake.termRequired }), ...(year ? {} : { year: t.intake.yearRequired }) });
    if (id === "places") {
      const need = places.status === "ready" && !!chosen?.supported && places.list.length > 0 && selected.length === 0;
      return fail(places.status === "loading" ? { places: t.places.stillLoading } : places.status === "error" ? { places: t.places.error } : need ? { places: t.places.empty } : {});
    }
    if (id === "dob") return fail(dob ? {} : { dob: t.dob.required });
    if (id === "consent") return fail(agreed ? {} : { consent: t.consent.required });
    return fail(EMAIL.test(email.trim()) ? {} : { guardian: t.guardian.required });
  }

  const go = (to: number) => { setErrors({}); setFormError(""); setIndex(to); };
  const next = () => { if (check(step)) go(index + 1); };

  async function submit() {
    if (!check(step)) return;
    setBusy(true); setFormError(""); setVaultNote(false);
    const details: ChoiceDetails = {
      destination, intake: { term, year: Number(year) },
      places: selected.map((ref, i) => ({ ref, rank: i + 1 })), consent: true,
      ...(options.needs_dob && dob ? { date_of_birth: dob } : {}),
      ...(guardianNeeded ? { guardian_email: email.trim() } : {}),
    };
    try {
      const answer = await workspaceApi.chooseRoute(card.field_key!, details);
      try { await onSaved(answer); } catch { /* saved; the page refreshes on its next load */ }
      if (answer.guardian_email_sent === undefined) onClose(); else setSaved(answer);
    } catch (e) {
      const { status, detail } = apiError(e);
      if (status === 422 && detail.includes(UNDER_18_DETAIL) && !guardianNeeded) {
        // Fallback: the age was not known up front; ask for the guardian now.
        setServerMinor(true);
        setErrors({}); setIndex(ids.length); // the guardian step is appended after consent
        setFocus({ field: "guardian", n: Date.now() });
      } else if (status === 409 && detail.includes(VAULT_DOB_DETAIL)) {
        setVaultNote(true); setFormError(detail);
      } else {
        setFormError(status === 422 || status === 409 ? detail || t.error : t.error);
      }
    } finally { setBusy(false); }
  }

  // After a reorder the pressed button may be disabled (first or last): keep focus on a usable one.
  useEffect(() => {
    if (!moved) return;
    const list = body.current;
    const same = list?.querySelector<HTMLButtonElement>(`[data-move="${moved.ref}:${moved.dir}"]`);
    const other = list?.querySelector<HTMLButtonElement>(`[data-move="${moved.ref}:${moved.dir === "up" ? "down" : "up"}"]`);
    (same && !same.disabled ? same : other)?.focus();
  }, [moved]);
  const move = (i: number, by: number) => {
    setMoved({ ref: selected[i], dir: by < 0 ? "up" : "down" });
    setSelected((s) => {
    const to = i + by;
    if (to < 0 || to >= s.length) return s;
    const copyOf = [...s];
    [copyOf[i], copyOf[to]] = [copyOf[to], copyOf[i]];
    return copyOf;
  }); };
  const toggle = useCallback((ref: string, on: boolean) =>
    setSelected((s) => (on ? (s.length < MAX_PLACES && !s.includes(ref) ? [...s, ref] : s) : s.filter((r) => r !== ref))), []);
  const nameOf = (ref: string) => places.list.find((p) => p.ref === ref)?.name ?? ref;
  const stepName = t.steps[step];

  if (saved) {
    const sent = saved.guardian_email_sent === true;
    return (
      <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader className="space-y-2 px-7 pb-2 pt-7 max-lg:px-5 max-lg:pt-1">
            <DialogTitle className="text-xl leading-snug">{t.done.title}</DialogTitle>
            <DialogDescription>{t.done.body}</DialogDescription>
          </DialogHeader>
          <DialogBody className="px-7 py-3 max-lg:px-5">
            {sent
              ? <p role="status" className="flex items-center gap-2 text-sm font-medium"><Check aria-hidden className="size-4" />{t.done.sent}</p>
              : (<>
                  {!resent && <p role="alert" className="text-sm font-medium text-danger-ink">{t.done.notSent} {t.done.notSentAction}</p>}
                  <GuardianResend onSent={() => setResent(true)} />
                </>)}
          </DialogBody>
          <DialogFooter className="flex-col items-stretch gap-2 px-7 pb-7 pt-3 max-lg:px-5 sm:flex-col sm:items-stretch">
            <Button size="tap" onClick={onClose}>{t.done.button}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader className="space-y-2 px-7 pb-2 pt-7 max-lg:px-5 max-lg:pt-1">
          <DialogTitle className="text-xl leading-snug">{fill(t.title, { title: card.title })}</DialogTitle>
          <DialogDescription>{t.intro}</DialogDescription>
          <ol aria-label={t.progress} className="flex flex-wrap gap-x-3 gap-y-1 pt-1 text-xs text-muted-foreground">
            {ids.map((id, i) => (
              <li key={id} aria-current={i === index ? "step" : undefined}
                className={cn("flex items-center gap-1", i === index && "font-semibold text-foreground")}>
                {i < index && <Check aria-hidden className="size-3" />}{t.steps[id]}
              </li>
            ))}
          </ol>
        </DialogHeader>
        <DialogBody className="px-7 py-3 max-lg:px-5">
          <div ref={body}>
            <h3 ref={headingRef} tabIndex={-1} data-testid="choice-step" className="mb-3 text-base font-semibold outline-none">
              {fill(t.stepOf, { n: index + 1, total: ids.length, name: stepName })}
            </h3>

            {step === "destination" && (
              <fieldset aria-describedby={errors.destination ? "choice-destination-error" : undefined}>
                <legend className="mb-2 text-sm font-medium">{t.destination.legend}</legend>
                <div className="space-y-2">
                  {options.destinations.map((d, i) => (
                    <label key={d.code} className={ROW}>
                      <input type="radio" name="choice-destination" value={d.code} checked={destination === d.code}
                        data-field={i === 0 ? "destination" : undefined} aria-invalid={errors.destination ? true : undefined}
                        onChange={() => { setDestination(d.code); setTerm(""); setSelected([]); setErrors({}); }} className="size-[18px] accent-[var(--brand)]" />
                      <span className="min-w-0">
                        <span className="block font-medium">{placeName(d.code, d.name)}</span>
                        <span className="block text-xs text-muted-foreground">{d.supported ? t.destination.supported : t.destination.unsupported}</span>
                      </span>
                    </label>
                  ))}
                </div>
                <FieldError id="choice-destination-error" message={errors.destination} />
              </fieldset>
            )}

            {step === "intake" && (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">{t.intake.hint}</p>
                <div>
                  <label htmlFor="choice-term" className="text-sm font-medium">{t.intake.term}</label>
                  <select id="choice-term" data-field="term" value={termOk ? term : ""} className={cn(FIELD, "mt-1")}
                    aria-invalid={errors.term ? true : undefined} aria-describedby={errors.term ? "choice-term-error" : undefined}
                    onChange={(e) => { setTerm(e.target.value); setSelected([]); }}>
                    <option value="" />
                    {(options.intake_terms[destination] ?? []).map((v) => <option key={v} value={v}>{termLabel(v)}</option>)}
                  </select>
                  <FieldError id="choice-term-error" message={errors.term} />
                </div>
                <div>
                  <label htmlFor="choice-year" className="text-sm font-medium">{t.intake.year}</label>
                  <select id="choice-year" data-field="year" value={year} className={cn(FIELD, "mt-1")}
                    aria-invalid={errors.year ? true : undefined} aria-describedby={errors.year ? "choice-year-error" : undefined}
                    onChange={(e) => { setYear(e.target.value); setSelected([]); }}>
                    <option value="" />
                    {options.years.map((y) => <option key={y} value={y}>{y}</option>)}
                  </select>
                  <FieldError id="choice-year-error" message={errors.year} />
                </div>
              </div>
            )}

            {step === "places" && (
              <fieldset aria-describedby={errors.places ? "choice-places-error" : undefined}>
                <legend className="text-sm font-medium">{fill(t.places.legend, { max: MAX_PLACES })}</legend>
                <p className="mb-2 mt-1 text-sm text-muted-foreground">{t.places.hint}</p>
                {places.status === "loading" && <p role="status" className="flex items-center gap-2 text-sm"><Loader2 aria-hidden className="size-4 animate-spin" />{t.places.loading}</p>}
                {places.status === "error" && (
                  <div>
                    <p role="alert" className="text-sm font-medium text-danger-ink">{t.places.error}</p>
                    <Button size="tap" variant="soft" className="mt-2" onClick={() => setRetry((n) => n + 1)}>{t.places.retry}</Button>
                  </div>
                )}
                {places.status === "ready" && places.list.length === 0 && <p className="text-sm text-muted-foreground">{t.places.none}</p>}
                <div className="space-y-2">
                  {places.list.map((p, i) => {
                    const on = selected.includes(p.ref);
                    return (
                      <label key={p.ref} className={ROW}>
                        <input type="checkbox" checked={on} disabled={!on && selected.length >= MAX_PLACES}
                          data-field={i === 0 ? "places" : undefined} aria-invalid={errors.places ? true : undefined}
                          onChange={(e) => toggle(p.ref, e.target.checked)} className="size-[18px] accent-[var(--brand)]" />
                        <span className="min-w-0 break-words font-medium">{p.name}</span>
                      </label>
                    );
                  })}
                </div>
                {selected.length >= MAX_PLACES && <p className="mt-2 text-xs text-muted-foreground">{fill(t.places.full, { max: MAX_PLACES })}</p>}
                <FieldError id="choice-places-error" message={errors.places} />
                {selected.length > 0 && (
                  <>
                    <h4 className="mb-1 mt-4 text-sm font-semibold">{t.places.ranking}</h4>
                    <ol aria-label={t.places.ranking} className="space-y-2">
                      {selected.map((ref, i) => (
                        <li key={ref} className="flex min-w-0 items-center gap-2 rounded-2xl bg-muted/60 px-3 py-1.5">
                          <span className="min-w-0 flex-1 break-words text-sm font-medium">{fill(t.places.rank, { rank: i + 1, name: nameOf(ref) })}</span>
                          <Button type="button" size="icon" variant="ghost" data-move={`${ref}:up`} aria-label={fill(t.places.up, { name: nameOf(ref) })} disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp aria-hidden /></Button>
                          <Button type="button" size="icon" variant="ghost" data-move={`${ref}:down`} aria-label={fill(t.places.down, { name: nameOf(ref) })} disabled={i === selected.length - 1} onClick={() => move(i, 1)}><ArrowDown aria-hidden /></Button>
                          <Button type="button" size="icon" variant="ghost" aria-label={fill(t.places.remove, { name: nameOf(ref) })} onClick={() => toggle(ref, false)}><X aria-hidden /></Button>
                        </li>
                      ))}
                    </ol>
                  </>
                )}
              </fieldset>
            )}

            {step === "dob" && (
              <div>
                <label htmlFor="choice-dob" className="text-sm font-medium">{t.dob.label}</label>
                <p id="choice-dob-hint" className="mb-2 text-sm text-muted-foreground">{t.dob.hint}</p>
                <DobPicker id="choice-dob" field="dob" value={dob} onChange={(v) => { setDob(v); setErrors({}); }}
                  invalid={!!errors.dob} describedBy={errors.dob ? "choice-dob-error" : "choice-dob-hint"} />
                <FieldError id="choice-dob-error" message={errors.dob} />
              </div>
            )}

            {step === "consent" && (
              options.consent_text == null
                ? <p role="alert" className="text-sm font-medium text-danger-ink">{t.consent.unavailable}</p>
                : (
                  <fieldset aria-describedby={errors.consent ? "choice-consent-error" : undefined}>
                    <legend className="mb-2 text-sm font-medium">{t.consent.legend}</legend>
                    <p className="whitespace-pre-line rounded-2xl bg-muted/60 p-4 text-sm leading-relaxed">{options.consent_text}</p>
                    {options.consent_version != null && <p className="mt-1 text-xs text-muted-foreground">{fill(t.consent.version, { version: options.consent_version })}</p>}
                    <label className={cn(ROW, "mt-3")}>
                      <input type="checkbox" checked={agreed} data-field="consent" aria-invalid={errors.consent ? true : undefined}
                        onChange={(e) => { setAgreed(e.target.checked); setErrors({}); }} className="size-[18px] accent-[var(--brand)]" />
                      <span className="font-medium">{t.consent.agree}</span>
                    </label>
                    <FieldError id="choice-consent-error" message={errors.consent} />
                  </fieldset>
                )
            )}

            {step === "guardian" && (
              <div>
                <label htmlFor="choice-guardian" className="text-sm font-medium">{t.guardian.label}</label>
                <p id="choice-guardian-hint" className="mb-2 text-sm text-muted-foreground">{t.guardian.hint}</p>
                <input id="choice-guardian" data-field="guardian" type="email" autoComplete="off" value={email} className={FIELD}
                  aria-invalid={errors.guardian ? true : undefined}
                  aria-describedby={errors.guardian ? "choice-guardian-error" : "choice-guardian-hint"}
                  onChange={(e) => setEmail(e.target.value)} />
                <FieldError id="choice-guardian-error" message={errors.guardian} />
              </div>
            )}

            {formError && <p role="alert" className="mt-3 text-sm font-medium text-danger-ink">{formError}</p>}
            {vaultNote && onOpenVault && (
              <Button size="tap" variant="soft" className="mt-2" onClick={onOpenVault}>{t.dob.vault}</Button>
            )}
          </div>
        </DialogBody>
        <DialogFooter className="flex-col items-stretch gap-2 px-7 pb-7 pt-3 max-lg:px-5 sm:flex-col sm:items-stretch">
          {index > 0 && <Button size="tap" variant="ghost" disabled={busy} onClick={() => go(index - 1)}>{t.back}</Button>}
          {step === "consent" && options.consent_text == null ? null : last
            ? <Button size="tap" disabled={busy} onClick={submit}>{busy ? <Loader2 aria-hidden className="animate-spin" /> : null}{busy ? t.saving : t.submit}</Button>
            : <Button size="tap" onClick={next}>{t.next}</Button>}
          <Button size="tap" variant="ghost" onClick={onClose}>{t.cancel}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
