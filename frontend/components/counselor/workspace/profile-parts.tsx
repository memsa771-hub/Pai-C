"use client";
import { useEffect, useId, useState } from "react";
import {
  CircleAlert, Eye, FileText, Gauge, Gem, GraduationCap, Heart, Home, Lightbulb, MessageCircle,
  Scale, Signpost, Sparkles, Target, UserRound, Users, type LucideIcon,
} from "lucide-react";
import { workspaceApi } from "@/lib/api";
import type { EvidenceItem, LivingPicture, ProfileCard } from "@/lib/counselor-workspace";
import type { CounselorMirrorDraft } from "@/lib/counselor-mirror";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  EmptyState, EvidenceBadge, QuadrantCard, SectionCard, StatChip, Timeline, evidenceLevel,
  toneClass, toneFor, type EvidenceLevel, type Quadrant, type Tone,
} from "@/components/pai";
import { cn } from "@/lib/utils";
import { human, evidenceLabel, shortDate } from "./resource";
import copy from "./copy.json";
import layout from "./profile-layout.json";

export const text = layout.copy;
export const ICONS: Record<string, LucideIcon> = {
  home: Home, graduation: GraduationCap, heart: Heart, lightbulb: Lightbulb, users: Users, gem: Gem,
  scale: Scale, gauge: Gauge, target: Target, signpost: Signpost, message: MessageCircle, file: FileText,
};
export const areaIcon = (area: string) => ICONS[layout.areaMeta[area as keyof typeof layout.areaMeta]?.icon] || Sparkles;
export const areaTone = (area: string) => (layout.areaMeta[area as keyof typeof layout.areaMeta]?.tone || "blue") as Tone;
/** Notebook evidence kinds map onto the public evidence ladder. */
export const kindLevel = (kind?: string): EvidenceLevel =>
  kind === "said" ? "stated" : kind && ["shown", "document", "action"].includes(kind) ? "shown" : "stated";
const fill = (template: string, values: Record<string, string | number>) =>
  Object.entries(values).reduce((out, [key, value]) => out.replaceAll(`{${key}}`, String(value)), template);
export { fill };

/** A smooth line of real certainty ratings only. Never invents a point. */
export function CertaintyChart({ ratings }: { ratings: LivingPicture["ratings"] }) {
  const gradient = useId();
  const points = ratings.flatMap((row) => [
    row.before === null ? null : { label: fill(text.before, { version: row.version }), value: row.before },
    row.after === null ? null : { label: fill(text.after, { version: row.version }), value: row.after },
  ]).filter((p): p is { label: string; value: number } => p !== null);
  if (!points.length) return <p className="text-sm text-muted-foreground">{text.certaintyEmpty}</p>;
  const W = 320, H = 150, L = 26, R = 12, T = 14, B = 18;
  const x = (i: number) => L + (points.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (points.length - 1));
  const y = (v: number) => T + ((10 - v) * (H - T - B)) / 10;
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i)} ${y(p.value)}`).join(" ");
  const latest = points.at(-1)!;
  return (
    <div>
      <p className="flex items-baseline gap-1.5">
        <span className="text-4xl font-bold tracking-tight text-brand-ink">{latest.value}</span>
        <span className="text-sm text-muted-foreground">/ 10 · {latest.label}</span>
      </p>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" className="mt-2 h-40 w-full overflow-visible"
        aria-label={`${text.certaintyTitle}. ${points.map((p) => fill(text.certaintyPoint, p)).join(". ")}`}>
        <defs>
          <linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--brand)" stopOpacity="0.28" />
            <stop offset="100%" stopColor="var(--brand)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 5, 10].map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--border)" strokeDasharray={v ? "4 4" : undefined} />
            <text x={L - 8} y={y(v) + 4} textAnchor="end" fontSize="10" fill="var(--muted-foreground)">{v}</text>
          </g>
        ))}
        {points.length > 1 && <path d={`${line} L${x(points.length - 1)} ${y(0)} L${x(0)} ${y(0)} Z`} fill={`url(#${gradient})`} />}
        <path d={line} fill="none" stroke="var(--brand)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        {points.map((p, i) => (
          <g key={i}>
            <circle cx={x(i)} cy={y(p.value)} r="6" fill="var(--card)" stroke="var(--brand)" strokeWidth="3"><title>{fill(text.certaintyPoint, p)}</title></circle>
          </g>
        ))}
      </svg>
      <p className="sr-only">{text.certaintyAxis}</p>
    </div>
  );
}

/** Chips with an evidence icon; tapping one shows the student's own words. */
export function ChipCloud({ items, tone }: { items: EvidenceItem[]; tone: Tone }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!items.length) return <p className="text-sm text-muted-foreground">{text.chipsEmpty}</p>;
  const quote = open === null ? null : items[open];
  return (
    <div>
      <ul className="flex flex-wrap gap-2">
        {items.map((item, i) => {
          const status = item.capability_status
            ? copy.capabilityLabels[item.capability_status as keyof typeof copy.capabilityLabels] : null;
          return (
            <li key={item.id || i}>
              <button type="button" aria-pressed={open === i} onClick={() => setOpen(open === i ? null : i)}
                className={cn("inline-flex min-h-11 max-w-full items-center gap-2 rounded-full border-2 border-transparent px-4 py-2 text-left text-sm font-semibold transition-colors",
                  toneClass[tone].soft, toneClass[tone].ink, open === i && "border-current")}>
                <span className="break-words">{human(item.value)}</span>
                <EvidenceBadge level={kindLevel(item.kind)} className="bg-card/80 text-foreground" />
                {status && <span className="rounded-full bg-card/80 px-2 py-0.5 text-xs font-medium text-foreground">{status}</span>}
              </button>
            </li>
          );
        })}
      </ul>
      <div aria-live="polite">
        {quote?.evidence && (
          <blockquote className="mt-3 rounded-xl border-l-4 bg-muted/60 px-4 py-3 text-sm" style={{ borderLeftColor: `var(--tone-${tone})` }}>
            <span className="block text-xs font-semibold text-muted-foreground">{text.fromYourWords}</span>
            “{quote.evidence}”
          </blockquote>
        )}
      </div>
    </div>
  );
}

/** You in the middle, the people who matter around you, with their hopes
 * and worries in the student's own framing. Worries can be hidden. */
export function PeopleMap({ people, showPrivate, initials }: { people: EvidenceItem[]; showPrivate: boolean; initials: string }) {
  if (!people.length) return <p className="text-sm text-muted-foreground">{text.peopleEmpty}</p>;
  return (
    <div className="flex flex-col items-center">
      <span className="flex size-14 items-center justify-center rounded-full bg-gradient-to-br from-[var(--hero-from)] to-[var(--hero-via)] text-lg font-bold text-white shadow-lift" aria-hidden>
        {initials || <UserRound className="size-6" />}
      </span>
      <span className="mt-1 text-xs font-semibold text-muted-foreground">{text.you}</span>
      <span aria-hidden className="h-5 w-0.5 bg-border" />
      <ul className="flex w-full flex-wrap justify-center gap-3 border-t-2 border-dashed border-border pt-5">
        {people.map((person, i) => {
          const role = String(person.role || human(person.value) || "");
          const tone = toneFor(role);
          const worry = person.worry || person.concern;
          return (
            <li key={person.id || i} className="w-full rounded-2xl border bg-card p-4 shadow-soft sm:w-[calc(50%-0.375rem)] lg:w-72">
              <div className="flex items-center gap-3">
                <span aria-hidden className={cn("flex size-10 shrink-0 items-center justify-center rounded-full text-sm font-bold", toneClass[tone].solid)}>
                  {role.charAt(0).toUpperCase()}
                </span>
                <p className="min-w-0 font-semibold">{role}</p>
              </div>
              {person.wish && (
                <p className="mt-3 flex gap-2 text-sm"><Heart aria-hidden className="mt-0.5 size-4 shrink-0 text-tone-teal" />
                  <span><span className="font-medium text-muted-foreground">{text.wish}: </span>{person.wish}</span></p>
              )}
              {worry && (
                <p className="mt-2 flex gap-2 text-sm"><CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-tone-amber" />
                  <span><span className="font-medium text-muted-foreground">{text.worry}: </span>
                    {showPrivate ? worry : <span className="italic text-muted-foreground">{text.sensitiveHidden}</span>}</span></p>
              )}
              {person.evidence && showPrivate && <p className="mt-2 text-xs italic text-muted-foreground">“{person.evidence}”</p>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

const record = (card: ProfileCard) => (card.value && typeof card.value === "object" ? card.value as Record<string, unknown> : {});
export const cardTitle = (card: ProfileCard) => {
  const value = record(card);
  const field = layout.titleFields.find((key) => typeof value[key] === "string" && value[key]);
  return field ? String(value[field]) : evidenceLabel(card.key);
};
const HIDDEN_IN_TIMELINE = new Set(["academic_status", ...layout.titleFields]);
const percent = (value: Record<string, unknown>) => {
  const p = Number(value.percentage);
  if (Number.isFinite(p) && p > 0 && p <= 100) return p;
  const got = Number(value.obtained_marks ?? value.marks_obtained), total = Number(value.total_marks ?? value.marks_total);
  return Number.isFinite(got) && Number.isFinite(total) && total > 0 ? Math.round((got / total) * 100) : null;
};

/** Qualifications and tests in order, with marks as a bar and a Shown badge
 * when the student uploaded a document for it. */
export function EducationTimeline({ cards }: { cards: ProfileCard[] }) {
  if (!cards.length) return <p className="text-sm text-muted-foreground">{text.educationEmpty}</p>;
  return (
    <Timeline items={cards.map((card) => {
      const value = record(card);
      const marks = percent(value);
      const status = String(value.academic_status || "");
      const fields = Object.entries(value).filter(([key, v]) => !HIDDEN_IN_TIMELINE.has(key) && human({ [key]: v }) && !/marks|percentage/.test(key));
      return {
        id: card.id,
        icon: GraduationCap,
        state: status === "current" ? "now" : "done",
        title: <h3 className="text-base">{cardTitle(card)}</h3>,
        meta: <EvidenceBadge level={evidenceLevel(card.evidence_level)} />,
        children: (
          <>
            {fields.length > 0 && (
              <dl className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                {fields.map(([key, v]) => (
                  <div key={key} className="flex gap-1"><dt className="text-muted-foreground">{evidenceLabel(key)}:</dt><dd className="font-medium">{human(v)}</dd></div>
                ))}
              </dl>
            )}
            {status && <StatChip size="sm" tone={status === "current" ? "blue" : "success"} className="mt-2">{human(status)}</StatChip>}
            {marks !== null && (
              <div className="mt-3">
                <div className="flex justify-between text-xs text-muted-foreground"><span>{evidenceLabel("percentage")}</span><span className="font-semibold text-foreground">{marks}%</span></div>
                <div className="mt-1 h-2 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${evidenceLabel("percentage")}: ${marks}%`}>
                  <div className="h-full rounded-full bg-tone-violet" style={{ width: `${marks}%` }} />
                </div>
              </div>
            )}
          </>
        ),
      };
    })} />
  );
}

const QUADRANTS: { key: "you_say" | "life_shows" | "pressure" | "you_want"; icon: LucideIcon; tone: Tone }[] = [
  { key: "you_say", icon: MessageCircle, tone: "blue" },
  { key: "life_shows", icon: Eye, tone: "teal" },
  { key: "pressure", icon: Scale, tone: "amber" },
  { key: "you_want", icon: Target, tone: "violet" },
];
const loadSummary = async (): Promise<CounselorMirrorDraft | null> => {
  try { return await workspaceApi.getCounselorSummary(); } catch { return null; }
};

/** The Mirror at the top of the profile. A draft can be agreed or changed;
 * an agreed Mirror asks once how understood the student felt. */
export function MirrorPanel({ picture, onChat, onChanged }: { picture: LivingPicture; onChat: (topic?: string) => void; onChanged: () => void }) {
  const [draft, setDraft] = useState<CounselorMirrorDraft | null>(null);
  const [editing, setEditing] = useState(false), [note, setNote] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState(false);
  useEffect(() => { let alive = true; void loadSummary().then((d) => { if (alive) setDraft(d); }); return () => { alive = false; }; }, []);
  const core = draft?.mirror?.core_picture;
  const status = draft?.status ?? (picture.picture ? "confirmed" : null);
  const lines: Record<string, string> | null = core
    ? Object.fromEntries(QUADRANTS.map(({ key }) => [key, core[key]?.text || ""]))
    : picture.picture ? Object.fromEntries(QUADRANTS.map(({ key }) => [key, picture.picture?.[key]?.text || ""])) : null;
  const version = draft?.version ?? picture.ratings.at(-1)?.version ?? null;
  const rated = picture.ratings.find((r) => r.version === version);
  async function act(edit: boolean) {
    if (version === null) return;
    setBusy(true); setError(false);
    try {
      if (edit) await workspaceApi.editCounselorMirror(version, note.trim());
      else await workspaceApi.confirmCounselorMirror(version);
      setDraft((d) => d ? { ...d, status: edit ? "needs_changes" : "confirmed" } : d);
      setEditing(false); setNote(""); onChanged();
    } catch { setError(true); } finally { setBusy(false); }
  }
  if (!lines) {
    return (
      <SectionCard title={text.mirrorTitle} icon={Sparkles} tone="violet">
        {draft?.mirror?.intro ? (
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-brand-ink">{text.firstPicture}</p>
            <p className="mt-2 text-pretty text-lg leading-relaxed">{draft.mirror.intro}</p>
            <Button size="tap" variant="soft" className="mt-4" onClick={() => onChat()}><MessageCircle aria-hidden />{text.openChat}</Button>
          </div>
        ) : (
          <EmptyState icon={Sparkles} tone="violet" title={text.gettingToKnow} description={text.gettingToKnowBody}
            action={<Button size="tap" onClick={() => onChat()}><MessageCircle aria-hidden />{text.openChat}</Button>} />
        )}
      </SectionCard>
    );
  }
  const quadrants: Quadrant[] = QUADRANTS.filter(({ key }) => lines[key]).map(({ key, icon, tone }) => ({
    key, icon, tone, text: lines[key], label: copy.pictureLabels[key],
  }));
  return (
    <SectionCard title={text.mirrorTitle} description={text.mirrorIntro} icon={Sparkles} tone="violet"
      action={<StatChip size="sm" tone={status === "confirmed" ? "success" : status === "needs_changes" ? "warning" : "blue"}>
        {status === "confirmed" ? text.mirrorConfirmed : status === "needs_changes" ? text.mirrorChanged : text.mirrorWaiting}
      </StatChip>}>
      <QuadrantCard quadrants={quadrants} />
      {error && <p role="alert" className="mt-3 text-sm font-medium text-danger-ink">{copy.error}</p>}
      {status === "awaiting_confirmation" && (editing ? (
        <form className="mt-4 space-y-3" onSubmit={(e) => { e.preventDefault(); void act(true); }}>
          <label className="block text-sm font-semibold">{text.mirrorEditHint}
            <Textarea className="mt-2 min-h-24 rounded-xl" value={note} maxLength={8000} disabled={busy} onChange={(e) => setNote(e.target.value)} />
          </label>
          <div className="flex flex-wrap gap-2">
            <Button size="tap" type="submit" disabled={busy || !note.trim()}>{text.mirrorSend}</Button>
            <Button size="tap" type="button" variant="ghost" onClick={() => setEditing(false)}>{copy.cancel}</Button>
          </div>
        </form>
      ) : (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="tap" disabled={busy} onClick={() => void act(false)}>{text.mirrorAgree}</Button>
          <Button size="tap" variant="outline" disabled={busy} onClick={() => setEditing(true)}>{text.mirrorEdit}</Button>
        </div>
      ))}
      {status === "confirmed" && (rated
        ? <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <FeltValue value={rated.understood} />
            <Button size="tap" variant="ghost" onClick={() => onChat(text.mirrorTalk)}><MessageCircle aria-hidden />{text.mirrorTalk}</Button>
          </div>
        : version !== null && <FeltUnderstood version={version} onSaved={onChanged} />)}
    </SectionCard>
  );
}

function FeltValue({ value }: { value: number }) {
  return (
    <p className="flex items-center gap-2 text-sm font-medium">
      <span aria-hidden className="flex gap-1">{[1, 2, 3, 4, 5].map((n) => (
        <span key={n} className={cn("h-2 w-5 rounded-full", n <= value ? "bg-success" : "bg-muted")} />
      ))}</span>
      {fill(text.feltUnderstoodValue, { value })}
    </p>
  );
}

type FeltLabels = { legend: string; certainty: string; send: string; saved: string; skip?: string };
/** One rating per Mirror version: 1-5 understood, optional 0-10 certainty.
 * Shared by the profile and the Mirror card in the conversation. */
export function FeltUnderstood({ version, onSaved, onSkip, labels }: {
  version: number; onSaved: () => void; onSkip?: () => void; labels?: Partial<FeltLabels>;
}) {
  const l: FeltLabels = { legend: text.feltUnderstood, certainty: text.certaintyAfter, send: text.sendRating, saved: text.ratingSaved, ...labels };
  const [understood, setUnderstood] = useState<number | null>(null);
  const [certainty, setCertainty] = useState<number | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(false), [saved, setSaved] = useState(false);
  const name = useId();
  if (saved) return <p role="status" className="mt-4 text-sm font-medium text-success-ink">{l.saved}</p>;
  async function send() {
    if (understood === null) return;
    setBusy(true); setError(false);
    try { await workspaceApi.submitCounselorMirrorFeedback(version, understood, certainty ?? undefined); setSaved(true); onSaved(); }
    catch { setError(true); } finally { setBusy(false); }
  }
  return (
    <form className="mt-5 rounded-2xl bg-muted/60 p-4" onSubmit={(e) => { e.preventDefault(); void send(); }}>
      <fieldset disabled={busy}>
        <legend className="text-sm font-semibold">{l.legend}</legend>
        <div role="radiogroup" aria-label={l.legend} className="mt-3 grid grid-cols-5 gap-2">
          {text.feltScale.map((label, i) => (
            <label key={label} className={cn("flex min-h-14 cursor-pointer flex-col items-center justify-center gap-0.5 rounded-xl border-2 bg-card px-1 text-center text-xs font-medium transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-ring",
              understood === i + 1 ? "border-brand bg-brand-soft text-brand-ink" : "border-transparent hover:border-border")}>
              <input type="radio" name={name} value={i + 1} checked={understood === i + 1} onChange={() => setUnderstood(i + 1)}
                aria-label={`${i + 1}: ${label}`} className="sr-only" />
              <span aria-hidden className="text-base font-bold">{i + 1}</span><span aria-hidden className="leading-tight">{label}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <label className="mt-4 block text-sm font-medium">
        {l.certainty}
        <span className="mt-2 flex items-center gap-3">
          <input type="range" min={0} max={10} step={1} value={certainty ?? 5} disabled={busy} onChange={(e) => setCertainty(Number(e.target.value))}
            className="h-11 flex-1 accent-[var(--brand)]" aria-valuetext={certainty === null ? "-" : `${certainty} / 10`} />
          <span aria-hidden className="w-12 text-right font-bold tabular-nums">{certainty === null ? "–" : `${certainty}/10`}</span>
        </span>
      </label>
      {error && <p role="alert" className="mt-2 text-sm font-medium text-danger-ink">{copy.error}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="tap" type="submit" disabled={busy || understood === null}>{l.send}</Button>
        {onSkip && <Button size="tap" type="button" variant="ghost" disabled={busy} onClick={onSkip}>{l.skip}</Button>}
      </div>
    </form>
  );
}
