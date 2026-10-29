"use client";
/** Pieces of the Mirror page: the header with the few lines PAI wrote, an
 * area tile, the level bar, and the "Still unknown" list. Words come from
 * copy.json `mirror`; the card comes from backend app/pai_c/mirror. */
import { CalendarClock, GitCompareArrows, MessageCircle, Sparkles } from "lucide-react";
import type { MirrorArea, MirrorCard, MirrorUnknown } from "@/lib/mirror";
import { Button } from "@/components/ui/button";
import { EvidenceBadge, StatChip, toneClass, vaultBadgeLabel } from "@/components/pai";
import { initials } from "@/components/counselor/path-card";
import { cn } from "@/lib/utils";
import { openWorkspaceView } from "../workspace-link";
import { areaIcon, areaTone } from "./profile-parts";
import copy from "./copy.json";

const t = copy.mirror;
export const CARD = "rounded-[22px] bg-card shadow-card ring-1 ring-border/70";
export const fill = (template: string, values: Record<string, unknown>) =>
  template.replace(/\{(\w+)\}/g, (_, key) => String(values[key] ?? ""));

type Question = { question: string; topic: string };
const questionOf = (unknown: MirrorUnknown): Question =>
  (unknown.question_key && (t.questions as Record<string, Question>)[unknown.question_key]) ||
  { question: unknown.label, topic: fill(t.topicFallback, { label: unknown.label }) };
/** The chat draft "Tell PAI" opens with. */
export const topicOf = (unknown: MirrorUnknown) => questionOf(unknown).topic;

/** "This is wrong" opens the entry in the Vault: Details for a fact or a
 * record, the story (Background) for an item. The write goes through the Vault. */
export function openEntryInVault(ref: string) {
  openWorkspaceView("profile", ref.startsWith("item:") ? { entry: ref, tab: "background" } : { entry: ref });
}

/** Three segments: how well PAI knows an area, in the area's own colour, with the word beside it. */
export function LevelBar({ level, tone }: { level: number; tone: keyof typeof toneClass }) {
  const word = t.levels[level] ?? t.levels[0];
  return (
    <div role="meter" aria-valuemin={0} aria-valuemax={3} aria-valuenow={level} aria-label={fill(t.levelLabel, { level: word })}
      className="mt-1 flex items-center gap-2">
      <span aria-hidden className="flex gap-1">
        {[1, 2, 3].map((step) => (
          <span key={step} className={cn("h-1.5 w-6 rounded-full", step <= level ? toneClass[tone].bar : "bg-muted")} />
        ))}
      </span>
      <span aria-hidden className="text-xs font-medium text-muted-foreground">{word}</span>
    </div>
  );
}

/** The top of the page: who this is, the education line, when it changed,
 * a strip of the ten areas, and the few lines PAI wrote. */
export function MirrorHero({ card, updated }: { card: MirrorCard; updated: string }) {
  const name = card.header.name;
  const known = card.areas.filter((area) => area.level > 0).length;
  return (
    <header className={cn(CARD, "relative min-w-0 overflow-hidden p-5 sm:p-7")}>
      <div className="relative flex min-w-0 items-center gap-4">
        <span aria-hidden className="flex size-14 shrink-0 items-center justify-center rounded-full bg-primary font-display text-xl text-primary-foreground shadow-[0_10px_24px_-12px_rgb(21_94_239/0.9)] sm:size-16">
          {name ? initials(name) : <Sparkles className="size-6" />}
        </span>
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">{t.title}</p>
          <h1 className="break-words font-display text-[1.75rem] leading-[1.15] sm:text-[2.1rem]">{name || t.title}</h1>
          {card.header.education_line && <p className="mt-0.5 break-words text-[15px] text-muted-foreground">{card.header.education_line.text}</p>}
        </div>
      </div>
      <div className="relative mt-4 flex flex-wrap items-center gap-2">
        {updated && <StatChip size="sm" icon={CalendarClock}>{fill(t.updated, { date: updated })}</StatChip>}
        <StatChip size="sm" tone="blue">{fill(t.known, { known, total: card.areas.length })}</StatChip>
        <span aria-hidden className="flex gap-1">
          {card.areas.map((area) => (
            <span key={area.key} title={area.label}
              className={cn("size-2.5 rounded-full", area.level ? toneClass[areaTone(area.key)].bar : "bg-muted", area.level === 1 && "opacity-50")} />
          ))}
        </span>
      </div>
      {card.text ? (
        <div className="relative mt-5 rounded-2xl bg-brand-soft/60 p-4 sm:p-5">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">{t.inWords}</p>
          <div className="mt-1.5 space-y-1.5 text-pretty text-[15.5px] leading-relaxed sm:text-base">
            {card.text.sentences.map((sentence, i) => <p key={i}>{sentence}</p>)}
          </div>
        </div>
      ) : card.ready && <p className="relative mt-4 text-sm text-muted-foreground">{t.textPending}</p>}
    </header>
  );
}

/** One area: icon, level bar, the tension note when two views differ, subject
 * marks, and each entry with its badge, source and "This is wrong". */
export function AreaTile({ area, onWrong }: { area: MirrorArea; onWrong: (ref: string) => void }) {
  const Icon = areaIcon(area.key);
  const tone = areaTone(area.key);
  const sides = new Set(area.tension.flatMap((mark) => [mark.a_id, mark.b_id]));
  const notes = [...new Set(area.tension.map((mark) => (t.templates as Record<string, string>)[mark.note_key]).filter(Boolean))];
  return (
    <article aria-labelledby={`mirror-area-${area.key}`} className={cn(CARD, "min-w-0 p-4 sm:p-5")}>
      <div className="flex min-w-0 items-start gap-3">
        <span aria-hidden className={cn("flex size-10 shrink-0 items-center justify-center rounded-full", toneClass[tone].soft, toneClass[tone].ink)}>
          <Icon className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 id={`mirror-area-${area.key}`} className="font-semibold leading-snug">{area.label}</h3>
          <LevelBar level={area.level} tone={tone} />
        </div>
      </div>
      {notes.map((note) => (
        <p key={note} className="mt-3 flex items-start gap-2 rounded-xl bg-warning-soft px-3 py-2 text-[13px] font-medium text-warning-ink">
          <GitCompareArrows aria-hidden className="mt-0.5 size-4 shrink-0" />{note}
        </p>
      ))}
      {!!area.bars?.length && (
        <div className="mt-3 rounded-xl bg-background p-3">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t.marks}</p>
          <ul className="mt-2 space-y-1.5">
            {area.bars.map((bar) => (
              <li key={bar.label} className="flex min-w-0 items-center gap-2.5 text-xs">
                <span className="w-24 shrink-0 truncate text-muted-foreground">{bar.label}</span>
                <span role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={bar.percent} aria-label={`${bar.label}: ${bar.percent}%`}
                  className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-muted">
                  <span className={cn("block h-full rounded-full", toneClass[tone].bar)} style={{ width: `${Math.min(100, bar.percent)}%` }} />
                </span>
                <span aria-hidden className="w-9 shrink-0 text-right font-semibold tabular-nums">{bar.percent}%</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <ul className="mt-2 divide-y divide-border/70">
        {area.entries.map((entry) => (
          <li key={entry.id} className="min-w-0 py-2.5">
            <p data-entry-text className="break-words text-[15px] font-medium leading-snug">
              {sides.has(entry.id) && (
                <span data-tension title={t.tension} className="me-1.5 inline-flex translate-y-0.5 text-warning-ink">
                  <GitCompareArrows aria-hidden className="size-4" /><span className="sr-only">{t.tension}: </span>
                </span>
              )}
              {entry.text}
            </p>
            <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
              <EvidenceBadge level={entry.evidence} label={vaultBadgeLabel(entry.evidence)} />
              <span aria-hidden>·</span>
              <span className="min-w-0 max-w-full truncate">{entry.source_label}</span>
              <button type="button" onClick={() => onWrong(entry.id)} aria-label={fill(t.wrongLabel, { text: entry.text })}
                className="-my-2 ms-auto inline-flex min-h-11 items-center rounded-full px-2 font-semibold text-primary hover:bg-accent hover:underline">
                {t.wrong}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </article>
  );
}

function TellPai({ unknown, onTell, variant = "soft" }: { unknown: MirrorUnknown; onTell: (u: MirrorUnknown) => void; variant?: "soft" | "primary" }) {
  return (
    <Button size="tap" variant={variant} className="mt-2 min-h-11 px-4" onClick={() => onTell(unknown)}
      aria-label={fill(t.tellPaiLabel, { label: unknown.label })}>
      <MessageCircle aria-hidden />{t.tellPai}
    </Button>
  );
}

/** What would complete the picture: each area PAI still does not know, the
 * question it would answer, and a way to tell PAI in chat. */
export function Unknowns({ unknowns, onTell }: { unknowns: MirrorUnknown[]; onTell: (u: MirrorUnknown) => void }) {
  return (
    <section aria-labelledby="mirror-unknown" className={cn(CARD, "min-w-0 p-5 lg:sticky lg:top-4")}>
      <div className="flex items-center gap-2">
        <h2 id="mirror-unknown" className="font-display text-lg leading-tight">{t.unknownTitle}</h2>
        {unknowns.length > 0 && <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-semibold tabular-nums text-muted-foreground">{unknowns.length}</span>}
      </div>
      <p className="mt-0.5 text-sm text-muted-foreground">{unknowns.length ? t.unknownIntro : t.allKnown}</p>
      {unknowns.length > 0 && (
        <ul className="mt-3 space-y-2">
          {unknowns.map((unknown) => {
            const Icon = areaIcon(unknown.area);
            const tone = areaTone(unknown.area);
            return (
              <li key={unknown.area} className="min-w-0 rounded-2xl bg-background p-3 ring-1 ring-border/70">
                <span className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                  <Icon aria-hidden className={cn("size-3.5", toneClass[tone].ink)} />{unknown.label}
                </span>
                <p className="mt-1 break-words text-sm font-medium">{questionOf(unknown).question}</p>
                <TellPai unknown={unknown} onTell={onTell} />
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** Below "ready": say so plainly and start with the first thing PAI needs. */
export function NotReady({ unknown, onTell }: { unknown: MirrorUnknown; onTell: (u: MirrorUnknown) => void }) {
  return (
    <section aria-labelledby="mirror-empty" className="min-w-0 rounded-[22px] bg-powder p-5 text-signal-ink sm:p-6">
      <h2 id="mirror-empty" className="text-balance font-display text-xl leading-tight sm:text-2xl">{t.emptyTitle}</h2>
      <p className="mt-2 text-sm">{t.emptyBody}</p>
      <p className="mt-1 break-words text-[15px] font-semibold">{questionOf(unknown).question}</p>
      <TellPai unknown={unknown} onTell={onTell} variant="primary" />
    </section>
  );
}
