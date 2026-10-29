"use client";
/** Pieces of the Roadmap page: a field card, the route sheet, the Compare
 * table and the student's chosen route. Words come from copy.json `roadmap`. */
import { useEffect, useRef, useState } from "react";
import {
  BookOpen, Briefcase, CalendarClock, Check, ClipboardCheck, Clock, ExternalLink, FlaskConical, Flag,
  GraduationCap, Info, Laptop, Loader2, MessageCircle, Percent, Ruler, Scale,
  Sprout, Stethoscope, Users, Wrench, type LucideIcon,
} from "lucide-react";
import { workspaceApi } from "@/lib/api";
import type { ChosenRoute, EducationLine, FieldCard, RoadmapStatus, RouteStep } from "@/lib/roadmap";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/responsive-dialog";
import { StatChip, toneClass, type Tone } from "@/components/pai";
import { initials } from "@/components/counselor/path-card";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/i18n/format";
import { DEFAULT_LOCALE } from "@/lib/i18n/locales";
import {
  cardTime, compareTime, doneCount, educationText, fill, intakeText, marksText, render, shortNeed, stepLabel, stepsDoneText,
  testsText, tickable, uncertain, yearsText,
} from "./roadmap-text";
import { RouteSteps, StepBar, StepDot, StepMeta, TimeLine } from "./roadmap-steps";
import { FamilyTalk } from "./family-talk";
import familyCopy from "./family-talk.json";
import copy from "./copy.json";

const t = copy.roadmap;
/** The workspace card surface (as on Paths and the Overview). */
export const CARD = "rounded-[22px] bg-card shadow-card ring-1 ring-border/70";
export const STATUS_TONE: Record<RoadmapStatus, Tone | "success" | "warning" | "neutral"> = {
  open: "success", step: "warning", not_open: "neutral", unknown: "sky",
};
export const CHOOSABLE: RoadmapStatus[] = ["open", "step"];
const FAMILY: Record<string, { icon: LucideIcon; tone: Tone }> = {
  engineering: { icon: Wrench, tone: "blue" }, computing: { icon: Laptop, tone: "violet" },
  health: { icon: Stethoscope, tone: "rose" }, sciences: { icon: FlaskConical, tone: "teal" },
  business: { icon: Briefcase, tone: "amber" }, arts_humanities: { icon: BookOpen, tone: "sky" },
  social_sciences: { icon: Users, tone: "teal" }, law: { icon: Scale, tone: "violet" },
  education: { icon: GraduationCap, tone: "blue" }, agriculture: { icon: Sprout, tone: "teal" },
  architecture_design: { icon: Ruler, tone: "amber" },
};

export function StatusChip({ status }: { status: RoadmapStatus }) {
  return <StatChip size="sm" tone={STATUS_TONE[status]} className="shrink-0">{t.status[status]}</StatChip>;
}

/** The family icon in a soft circle; a field PAI has no family for shows its initials. */
export function FieldMark({ card, size = "md" }: { card: Pick<FieldCard, "family" | "title">; size?: "sm" | "md" }) {
  const family = card.family ? FAMILY[card.family] : undefined;
  const tone = toneClass[family?.tone || "sky"];
  const Icon = family?.icon;
  return (
    <span aria-hidden className={cn("flex shrink-0 items-center justify-center rounded-full font-semibold", tone.soft, tone.ink,
      size === "md" ? "size-11 text-[13px]" : "size-8 text-[11px]")}>
      {Icon ? <Icon className={size === "md" ? "size-5" : "size-4"} /> : initials(card.title)}
    </span>
  );
}

/** The calm information note for a rule that is not official. */
function CheckNote() {
  return (
    <p className="inline-flex items-center gap-1.5 rounded-full bg-info-soft px-2.5 py-1 text-xs font-medium text-info-ink">
      <Info aria-hidden className="size-3.5 shrink-0" />{t.checkUniversity}
    </p>
  );
}

function Fact({ icon: Icon, children }: { icon: LucideIcon; children: React.ReactNode }) {
  return (
    <span className="inline-flex min-w-0 max-w-full items-center gap-1.5">
      <Icon aria-hidden className="size-3.5 shrink-0 text-muted-foreground" /><span className="truncate">{children}</span>
    </span>
  );
}

/** Reasons worth a line on the card: why it is a step, not open or unknown,
 * or the "add your marks" note on an open field. */
const reasonLine = (card: FieldCard) => card.verdict.reasons.map(render).filter(Boolean).join(" · ");

/** One field. The whole card opens the route sheet; the checkbox (its own
 * 44px target, above the card button) picks it for Compare. */
export function FieldCardView({ card, picked, pickDisabled, onPick, onOpen, mine = false }: {
  card: FieldCard;
  mine?: boolean;
  picked: boolean;
  pickDisabled: boolean;
  onPick: (on: boolean) => void;
  onOpen: () => void;
}) {
  const reason = reasonLine(card);
  const tests = testsText(card), years = yearsText(card.verdict.years), marks = marksText(card), time = cardTime(card.time);
  return (
    <article className={cn(CARD, "group relative flex gap-3.5 p-4 transition-shadow hover:shadow-lift sm:p-5",
      picked && "ring-2 ring-primary/60")}>
      <FieldMark card={card} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 pe-8">
          <h3 className="font-semibold leading-snug">{card.title}</h3>
          <StatusChip status={card.status} />
          {mine && <StatChip size="sm" tone="blue" icon={Flag}>{t.yourRouteChip}</StatChip>}
        </div>
        {reason && (
          <p className={cn("mt-1 line-clamp-2 text-sm font-medium",
            card.status === "step" ? "text-warning-ink" : "text-muted-foreground")}>{reason}</p>
        )}
        {(tests || years || marks) && (
          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-foreground/80">
            {tests && <Fact icon={ClipboardCheck}>{tests}</Fact>}
            {years && <Fact icon={CalendarClock}>{years}</Fact>}
            {marks && <Fact icon={Percent}>{marks}</Fact>}
          </p>
        )}
        {(time || !!card.steps?.length) && (
          <div className="mt-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5 text-[13px] font-medium">
            {!!card.steps?.length && <StepBar steps={card.steps} className="w-24 shrink-0" />}
            {time && <Fact icon={Clock}>{time}</Fact>}
          </div>
        )}
        {card.why && <p className="mt-2 line-clamp-2 text-sm text-muted-foreground sm:line-clamp-1">{card.why}</p>}
        {uncertain(card) && <div className="mt-2.5"><CheckNote /></div>}
      </div>
      <button type="button" onClick={onOpen} aria-label={fill(t.open, { title: card.title })}
        className="absolute inset-0 rounded-[22px] outline-none focus-visible:ring-2 focus-visible:ring-primary" />
      <label title={pickDisabled ? fill(t.compareMax, { n: t.compareLimits.max }) : undefined}
        className={cn("absolute right-1.5 top-1.5 z-10 flex size-11 items-center justify-center rounded-full",
          pickDisabled ? "cursor-not-allowed opacity-40" : "cursor-pointer hover:bg-accent")}>
        <input type="checkbox" checked={picked} disabled={pickDisabled} onChange={(e) => onPick(e.target.checked)}
          aria-label={fill(t.compareToggle, { title: card.title })} className="size-[18px] cursor-[inherit] accent-[var(--brand)]" />
      </label>
    </article>
  );
}

const host = (url: string) => {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
};

/** "October 2026" from the rules' "2026-10"; empty when unknown. */
const monthYear = (asOf: string | null | undefined) =>
  asOf ? formatDate(`${asOf}-01`.slice(0, 10), DEFAULT_LOCALE, { month: "long", year: "numeric", timeZone: "UTC" }) : "";

function Sources({ sources, checkedAt }: { sources: string[]; checkedAt?: string | null }) {
  const checked = monthYear(checkedAt);
  return (
    <section className="mt-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t.sheet.sources}</h3>
        {checked && <p className="text-xs text-muted-foreground">{fill(t.sheet.checked, { date: checked })}</p>}
      </div>
      {sources.length ? (
        <ul className="mt-2 flex flex-wrap gap-2">
          {sources.map((url) => (
            <li key={url} className="min-w-0 max-w-full">
              <a href={url} target="_blank" rel="noopener noreferrer"
                className="inline-flex min-h-9 max-w-full items-center gap-1.5 rounded-full bg-background px-3 text-[13px] font-medium text-primary ring-1 ring-border hover:bg-accent">
                <span className="truncate">{host(url)}</span><ExternalLink aria-hidden className="size-3.5 shrink-0" />
              </a>
            </li>
          ))}
        </ul>
      ) : <p className="mt-1 text-sm text-muted-foreground">{t.sheet.noSources}</p>}
    </section>
  );
}

/** The route for one field: Now → What you need → Entry test → Degree, its
 * sources, and the student's own choice. Nothing is chosen for them. */
export function RouteSheet({ card, line, chosen, checkedAt, onClose, onChoose }: {
  card: FieldCard | null;
  line: EducationLine | null;
  checkedAt?: string | null;
  chosen: ChosenRoute | null;
  onClose: () => void;
  onChoose: (card: FieldCard) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false), [error, setError] = useState(false);
  useEffect(() => { setBusy(false); setError(false); }, [card]);
  if (!card) return <Dialog open={false} onOpenChange={onClose} />;
  const v = card.verdict;
  const reasons = v.reasons.map(render).filter(Boolean);
  const choosable = CHOOSABLE.includes(card.status);
  const mine = chosen?.field_key != null && chosen.field_key === card.field_key;
  async function choose() {
    setBusy(true); setError(false);
    try { await onChoose(card!); } catch { setError(true); } finally { setBusy(false); }
  }
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader className="space-y-2 px-7 pb-2 pt-7 max-lg:px-5 max-lg:pt-1">
          <div className="flex items-center gap-3">
            <FieldMark card={card} />
            <div className="min-w-0">
              <DialogTitle className="text-xl leading-snug">{card.title}</DialogTitle>
              <div className="mt-1"><StatusChip status={card.status} /></div>
            </div>
          </div>
          <DialogDescription className={cn(!reasons.length && "sr-only")}>{reasons.join(" · ") || t.status[card.status]}</DialogDescription>
          {line && <p className="text-sm text-muted-foreground">{educationText(line)}</p>}
        </DialogHeader>
        <DialogBody className="px-7 py-3 max-lg:px-5">
          {card.time && (
            <div className="mb-4 rounded-2xl bg-brand-soft/60 px-4 py-3">
              <TimeLine time={card.time} />
            </div>
          )}
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t.steps.title}</h3>
          <RouteSteps steps={card.steps || []} time={card.time} label={card.title} />
          {intakeText(card.time) && (
            <p className="mt-3 flex items-center gap-2 text-sm font-semibold">
              <GraduationCap aria-hidden className="size-4 shrink-0 text-primary" />{intakeText(card.time)}
            </p>
          )}
          {!!card.steps?.length && <p className="mt-2 text-xs text-muted-foreground">{t.steps.legend}</p>}
          {uncertain(card) && <div className="mt-4"><CheckNote /></div>}
          <Sources sources={v.sources} checkedAt={checkedAt} />
        </DialogBody>
        <DialogFooter className="flex-col items-stretch gap-2 px-7 pb-7 pt-3 max-lg:px-5 sm:flex-col sm:items-stretch">
          {!choosable && reasons[0] && <p className="text-sm text-muted-foreground">{reasons[0]}</p>}
          {choosable && chosen && !mine && <p className="text-sm text-muted-foreground">{t.sheet.replaces}</p>}
          {error && <p role="alert" className="text-sm font-medium text-danger-ink">{t.error}</p>}
          <Button size="tap" disabled={!choosable || mine || busy} onClick={choose}>
            {busy ? <Loader2 aria-hidden className="animate-spin" /> : mine ? <Check aria-hidden /> : <Flag aria-hidden />}
            {mine ? t.sheet.chosen : t.sheet.choose}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Same rows for every field so the eye reads across; on a phone the columns
 * scroll under sticky row labels. Short words only, never the rule's prose. */
export function CompareDialog({ cards, open, onOpenChange }: {
  cards: FieldCard[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const rows: [keyof typeof t.compareRows, (card: FieldCard) => React.ReactNode][] = [
    ["status", (card) => <StatusChip status={card.status} />],
    ["marks", (card) => card.verdict.min_percent == null ? t.notKnown : card.verdict.student_percent == null
      ? `${card.verdict.min_percent}%` : fill(t.facts.marksCompare, { min: card.verdict.min_percent, have: card.verdict.student_percent })],
    ["step", (card) => card.status === "not_open" ? render(card.verdict.reasons[0] || { key: "" }) || t.status.not_open
      : card.status === "unknown" ? t.notKnown : (card.verdict.needs.length ? card.verdict.needs.map(shortNeed).join(", ") : shortNeed(undefined))],
    ["stepsDone", (card) => stepsDoneText(card.steps) || t.notKnown],
    ["test", (card) => testsText(card) || t.facts.noTest],
    ["years", (card) => yearsText(card.verdict.years) || t.notKnown],
    ["time", (card) => compareTime(card.time)],
    ["confidence", (card) => card.verdict.confidence ? t.confidence[card.verdict.confidence] : t.notKnown],
  ];
  const label = "sticky left-0 z-10 w-28 min-w-28 bg-card py-3 pe-3 text-left align-top text-xs font-semibold text-muted-foreground sm:w-40 sm:min-w-40";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader className="space-y-2 px-7 pb-2 pt-7 max-lg:px-5 max-lg:pt-1">
          <DialogTitle className="text-xl">{t.compareTitle}</DialogTitle>
          <DialogDescription>{t.compareIntro}</DialogDescription>
        </DialogHeader>
        <DialogBody className="px-7 pb-7 pt-2 max-lg:px-5">
          <div className="-mx-1 overflow-x-auto px-1 pb-1">
            <table className="w-full border-separate border-spacing-0 text-sm">
              <thead>
                <tr>
                  <th className={cn(label, "align-bottom")}><span className="sr-only">{t.compareCorner}</span></th>
                  {cards.map((card) => (
                    <th key={card.possibility_id} scope="col" className="min-w-36 border-b border-border/70 px-3 pb-3 text-left align-bottom font-semibold">
                      <span className="flex items-center gap-2"><FieldMark card={card} size="sm" /><span className="leading-snug">{card.title}</span></span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map(([key, cell]) => (
                  <tr key={key}>
                    <th scope="row" className={cn(label, "border-b border-border/70")}>{t.compareRows[key]}</th>
                    {cards.map((card) => (
                      <td key={card.possibility_id} className="border-b border-border/70 px-3 py-3 align-top">{cell(card)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}

/** The chosen route: its coloured steps (green from the Vault, or ticked by
 * the student where a tick is allowed: applying, and a step not yet done),
 * progress by status, the time to entry, "Change route" behind one confirm,
 * and family-talk preparation (the backend reads the chosen path). A tick is
 * saved at once and undone if the save fails. */
export function YourRoute({ route, onWithdrawn, onTicked, onChat }: {
  route: ChosenRoute;
  onWithdrawn: () => Promise<void> | void;
  onTicked?: () => void;
  onChat?: (topic?: string) => void;
}) {
  const [steps, setSteps] = useState<RouteStep[]>(route.steps);
  const [error, setError] = useState(false), [confirming, setConfirming] = useState(false), [busy, setBusy] = useState(false),
    [savingView, setSavingView] = useState(false), [familyOpen, setFamilyOpen] = useState(false);
  const saving = useRef(false);
  useEffect(() => { setSteps(route.steps); }, [route]);
  // One save at a time: the ticks are disabled while one is saving, so a
  // double click cannot send (key, true) then (key, false) and replies never
  // arrive out of order. A failure undoes only the step that failed.
  async function tick(step: RouteStep, value: boolean) {
    if (saving.current) return;
    saving.current = true;
    setSavingView(true);
    const put = (next: RouteStep) => setSteps((list) => list.map((s) => (s.key === step.key ? next : s)));
    put({ ...step, status: value ? "done" : "not", manual_done: value });
    setError(false);
    try {
      const saved = await workspaceApi.setRouteStep(step.key, value);
      setSteps(saved.steps);
      onTicked?.();
    } catch {
      put(step);
      setError(true);
    } finally {
      saving.current = false;
      setSavingView(false);
    }
  }
  async function withdraw() {
    setBusy(true); setError(false);
    try { await workspaceApi.withdrawRoute(); await onWithdrawn(); } catch { setError(true); } finally { setBusy(false); setConfirming(false); }
  }
  const count = doneCount(steps), total = steps.length;
  const snapshot = route.snapshot_verdict?.status;
  return (
    <section aria-labelledby="your-route-title" className={cn(CARD, "mb-8 overflow-hidden")}>
      <div className="bg-brand-soft/60 px-5 pb-4 pt-5 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <span aria-hidden className="flex size-11 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground"><Flag className="size-5" /></span>
            <div className="min-w-0">
              <h2 id="your-route-title" className="text-[11px] font-semibold uppercase tracking-wide text-primary">{t.route.title}</h2>
              <p className="font-display text-xl leading-snug">{route.title}</p>
            </div>
          </div>
          <p className="text-sm font-semibold tabular-nums">
            <span aria-hidden>{fill(t.route.progress, { done: count, total })}</span>
            <span className="sr-only">{fill(t.route.progressLabel, { done: count, total })}</span>
          </p>
        </div>
        <StepBar steps={steps} className="mt-3" />
        <TimeLine time={route.time} className="mt-3" />
      </div>
      <div className="px-5 py-4 sm:px-6">
        {snapshot && snapshot !== route.live_status && (
          <p role="status" className="mb-3 flex items-start gap-2 rounded-2xl bg-info-soft px-4 py-3 text-sm text-info-ink">
            <Info aria-hidden className="mt-0.5 size-4 shrink-0" />{fill(t.route.changed, { status: t.statusNow[route.live_status] })}
          </p>
        )}
        <ul aria-label={t.steps.title} className="divide-y divide-border/70">
          {steps.map((step) => {
            const label = stepLabel(step);
            return (
              <li key={step.key} data-status={step.status} className="flex min-w-0 items-start gap-3 py-2.5">
                <span className="pt-0.5"><StepDot status={step.status} size="sm" /></span>
                <div className="min-w-0 flex-1">
                  <p className="break-words text-sm font-medium leading-snug">{label}</p>
                  <StepMeta step={step} time={route.time} />
                </div>
                {tickable(step) && (
                  <label title={t.steps.tick} className="-my-1.5 -me-2 flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-full hover:bg-accent">
                    <input type="checkbox" aria-label={label} checked={step.status === "done"} disabled={savingView}
                      onChange={(e) => tick(step, e.target.checked)} className="size-[18px] cursor-[inherit] accent-[var(--brand)]" />
                  </label>
                )}
              </li>
            );
          })}
        </ul>
        {error && <p role="alert" className="mt-2 text-sm font-medium text-danger-ink">{t.error}</p>}
        {confirming ? (
          <div className="mt-4 rounded-2xl bg-background p-4 ring-1 ring-border">
            <p className="text-sm">{fill(t.route.changeConfirm, { title: route.title })}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="tap" variant="destructive" disabled={busy} onClick={withdraw}>{t.route.changeYes}</Button>
              <Button size="tap" variant="ghost" onClick={() => setConfirming(false)}>{t.route.changeNo}</Button>
            </div>
          </div>
        ) : (
          <div className="mt-3 flex flex-wrap gap-2">
            {onChat && <Button size="tap" variant="soft" onClick={() => onChat(copy.checkin)}><MessageCircle aria-hidden />{t.route.checkin}</Button>}
            <Button size="tap" variant="ghost" aria-expanded={familyOpen} onClick={() => setFamilyOpen(!familyOpen)}>
              <Users aria-hidden />{familyOpen ? copy.cancel : t.route.family}</Button>
            <Button size="tap" variant="ghost" onClick={() => setConfirming(true)}>{t.route.change}</Button>
          </div>
        )}
        {familyOpen && (
          <div className="mt-4 rounded-2xl bg-background p-4 ring-1 ring-border">
            <h3 className="font-semibold">{familyCopy.title}</h3>
            <p className="mb-4 mt-1 text-sm text-muted-foreground">{t.route.familyIntro}</p>
            <FamilyTalk />
          </div>
        )}
      </div>
    </section>
  );
}
