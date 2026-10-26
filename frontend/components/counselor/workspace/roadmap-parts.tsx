"use client";
/** Pieces of the Roadmap page: a field card, the route sheet, the Compare
 * table and the student's chosen route. Words come from copy.json `roadmap`. */
import { useEffect, useState } from "react";
import {
  BookOpen, Briefcase, CalendarClock, Check, CircleCheck, ClipboardCheck, ExternalLink, FlaskConical, Flag,
  GraduationCap, Info, Laptop, ListChecks, Loader2, MapPin, MessageCircle, Percent, Ruler, Scale,
  Sprout, Stethoscope, Users, Wrench, type LucideIcon,
} from "lucide-react";
import { workspaceApi } from "@/lib/api";
import type { ChosenRoute, EducationLine, FieldCard, RoadmapStatus } from "@/lib/roadmap";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/responsive-dialog";
import { StatChip, Timeline, toneClass, type Tone } from "@/components/pai";
import { initials } from "@/components/counselor/path-card";
import { cn } from "@/lib/utils";
import {
  educationText, fill, marksText, needItem, render, shortNeed, testsText, uncertain, yearsText,
} from "./roadmap-text";
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
  const tests = testsText(card), years = yearsText(card.verdict.years), marks = marksText(card);
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

function Sources({ sources }: { sources: string[] }) {
  return (
    <section className="mt-5">
      <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t.sheet.sources}</h3>
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
export function RouteSheet({ card, line, chosen, onClose, onChoose }: {
  card: FieldCard | null;
  line: EducationLine | null;
  chosen: ChosenRoute | null;
  onClose: () => void;
  onChoose: (card: FieldCard) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false), [error, setError] = useState(false);
  useEffect(() => { setBusy(false); setError(false); }, [card]);
  if (!card) return <Dialog open={false} onOpenChange={onClose} />;
  const v = card.verdict;
  const needs = v.needs.map((need) => render(needItem(need))).filter(Boolean);
  const reasons = v.reasons.map(render).filter(Boolean);
  const choosable = CHOOSABLE.includes(card.status);
  const mine = chosen?.field_key != null && chosen.field_key === card.field_key;
  async function choose() {
    setBusy(true); setError(false);
    try { await onChoose(card!); } catch { setError(true); } finally { setBusy(false); }
  }
  const h = (text: string) => <h3 className="text-sm">{text}</h3>;
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
        </DialogHeader>
        <DialogBody className="px-7 py-3 max-lg:px-5">
          <Timeline label={card.title} items={[
            { id: "now", icon: MapPin, state: "now", title: h(t.sheet.now),
              children: <p className="text-sm text-muted-foreground">{educationText(line) || t.notKnown}</p> },
            { id: "needs", icon: ListChecks, title: h(t.sheet.needs),
              children: needs.length ? (
                <ul className="space-y-1.5">
                  {needs.map((need, i) => (
                    <li key={i} className="flex gap-2 text-sm"><CircleCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-warning-ink" />{need}</li>
                  ))}
                </ul>
              ) : <p className="text-sm text-muted-foreground">{t.sheet.nothingExtra}</p> },
            { id: "test", icon: ClipboardCheck, title: h(t.sheet.test),
              children: v.tests.length ? (
                <ul className="space-y-1 text-sm">
                  {v.tests.map((test) => (
                    <li key={test.name}>{test.name}{test.pass_percent != null && <span className="text-muted-foreground"> · {fill(t.sheet.pass, { n: test.pass_percent })}</span>}</li>
                  ))}
                </ul>
              ) : <p className="text-sm text-muted-foreground">{t.sheet.noTest}</p> },
            { id: "degree", icon: GraduationCap,
              title: h(v.years == null ? t.sheet.degreeNoYears : fill(t.sheet.degree, { n: v.years })),
              children: <p className="text-sm text-muted-foreground">{card.title}</p> },
          ]} />
          {uncertain(card) && <div className="mt-4"><CheckNote /></div>}
          <Sources sources={v.sources} />
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
      : card.status === "unknown" ? t.notKnown : shortNeed(card.verdict.needs[0])],
    ["test", (card) => testsText(card) || t.facts.noTest],
    ["years", (card) => yearsText(card.verdict.years) || t.notKnown],
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

/** The chosen route: its checklist the student ticks (saved at once, undone
 * if the save fails), and "Change route" behind one confirm. */
export function YourRoute({ route, onWithdrawn, onChat }: {
  route: ChosenRoute;
  onWithdrawn: () => Promise<void> | void;
  onChat?: (topic?: string) => void;
}) {
  const [done, setDone] = useState(route.steps_done);
  const [error, setError] = useState(false), [confirming, setConfirming] = useState(false), [busy, setBusy] = useState(false);
  useEffect(() => { setDone(route.steps_done); }, [route]);
  async function tick(index: number, value: boolean) {
    const before = done;
    setDone(done.map((d, i) => (i === index ? value : d)));
    setError(false);
    try {
      const saved = await workspaceApi.setRouteStep(index, value);
      setDone(saved.steps_done);
    } catch {
      setDone(before);
      setError(true);
    }
  }
  async function withdraw() {
    setBusy(true); setError(false);
    try { await workspaceApi.withdrawRoute(); await onWithdrawn(); } catch { setError(true); } finally { setBusy(false); setConfirming(false); }
  }
  const count = done.filter(Boolean).length, total = route.steps.length;
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
          <p className="text-sm font-semibold tabular-nums" aria-label={fill(t.route.progressLabel, { done: count, total })}>
            {fill(t.route.progress, { done: count, total })}
          </p>
        </div>
        <span aria-hidden className="mt-3 block h-2 overflow-hidden rounded-full bg-card">
          <span className="block h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: `${total ? (count / total) * 100 : 0}%` }} />
        </span>
      </div>
      <div className="px-5 py-4 sm:px-6">
        {snapshot && snapshot !== route.live_status && (
          <p role="status" className="mb-3 flex items-start gap-2 rounded-2xl bg-info-soft px-4 py-3 text-sm text-info-ink">
            <Info aria-hidden className="mt-0.5 size-4 shrink-0" />{fill(t.route.changed, { status: t.statusNow[route.live_status] })}
          </p>
        )}
        <ul className="divide-y divide-border/70">
          {route.steps.map((step, i) => (
            <li key={i}>
              <label className="flex min-h-11 cursor-pointer items-center gap-3 py-1.5 text-sm">
                <input type="checkbox" checked={!!done[i]} onChange={(e) => tick(i, e.target.checked)}
                  className="size-[18px] shrink-0 accent-[var(--brand)]" />
                <span className={cn(done[i] && "text-muted-foreground line-through decoration-muted-foreground/50")}>{render(step)}</span>
              </label>
            </li>
          ))}
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
            <Button size="tap" variant="ghost" onClick={() => setConfirming(true)}>{t.route.change}</Button>
          </div>
        )}
      </div>
    </section>
  );
}


