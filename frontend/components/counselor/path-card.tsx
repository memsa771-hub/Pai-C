'use client';
import { CircleCheck, CircleDashed, CircleHelp, CircleX, Compass, ExternalLink, Quote, type LucideIcon } from 'lucide-react';
import { EvidenceBadge, StatChip, toneClass, toneFor, vaultBadgeLabel, type Tone } from '@/components/pai';
import type { FitItem, PathEvidence, StudyField } from '@/lib/possibilities';
import type { VaultLevel } from '@/lib/vault';
import { cn } from '@/lib/utils';
import copy from './workspace/copy.json';

/** The notes a study-field path carries: needs checking for the student's
 * group, the intermediate group a Matric student would need, or an older
 * generic path from before fields of study, or a kept field the student's
 * current group no longer opens. */
export function FieldNotes({ field, className }: { field?: StudyField | null; className?: string }) {
  if (!field) return null;
  const notes = [
    field.outdated && copy.pathOutdated,
    field.out_of_group && copy.pathOutOfGroup,
    field.needs_check && copy.pathNeedsCheck,
    field.needs_group?.length && copy.pathNeedsGroup.replace('{groups}', field.needs_group.map((g) => g.label).join(' / ')),
  ].filter((note): note is string => typeof note === 'string');
  if (!notes.length) return null;
  return (
    <span className={cn('inline-flex flex-wrap gap-1.5', className)}>
      {notes.map((note) => <StatChip key={note} size="sm" tone="warning">{note}</StatChip>)}
    </span>
  );
}

/** The Vault badge behind a path's reason: each distinct evidence level and
 * source the reason cites, worded as the Vault words it ("Stated · Chat").
 * A researched field-note fact the reason uses shows as a "Source" link to
 * its page, once per site. */
export function WhyEvidence({ evidence, className }: { evidence?: PathEvidence[]; className?: string }) {
  const seen = new Set<string>();
  const badges = (evidence || []).filter((item) => {
    if (!item.evidence_level || item.evidence_level === 'source') return false;
    const key = `${item.evidence_level}|${item.source_label || ''}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  const sources = new Map<string, string>();
  for (const item of evidence || []) {
    if (item.evidence_level !== 'source' || !item.source_url) continue;
    try {
      const url = new URL(item.source_url);
      if (url.protocol === 'https:' && !sources.has(url.hostname)) sources.set(url.hostname, item.source_url);
    } catch {}
  }
  if (!badges.length && !sources.size) return null;
  return (
    <span className={cn('inline-flex flex-wrap items-center gap-x-3 gap-y-1', className)}>
      {badges.map((item) => {
        const level = item.evidence_level as VaultLevel;
        const label = vaultBadgeLabel(level);
        return <EvidenceBadge key={`${level}|${item.source_label}`} level={level}
          label={item.source_label ? `${label} · ${item.source_label}` : label} />;
      })}
      {[...sources].map(([host, url]) => (
        <a key={host} href={url} target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs font-semibold text-brand-ink underline-offset-4 hover:underline">
          <ExternalLink aria-hidden className="size-3.5" />{copy.whySource} · {host}
        </a>
      ))}
    </span>
  );
}

/** Shape and colour together, so the verdict never rests on colour alone. */
const FIT: Record<FitItem['status'], { icon: LucideIcon; className: string }> = {
  have: { icon: CircleCheck, className: 'text-success' },
  partial: { icon: CircleDashed, className: 'text-warning' },
  blocker: { icon: CircleX, className: 'text-danger' },
  unknown: { icon: CircleHelp, className: 'text-muted-foreground/70' },
};

/** How a path fits the student, one requirement per row. Detailed rows add
 * the note and the student's own words behind each known verdict. */
export function FitList({ items, detailed = false, limit }: { items: FitItem[]; detailed?: boolean; limit?: number }) {
  const shown = limit ? items.slice(0, limit) : items;
  if (!shown.length) return null;
  return (
    <ul className={cn(detailed ? 'space-y-4' : 'space-y-2')}>
      {shown.map((item, i) => {
        const { icon: Icon, className } = FIT[item.status] || FIT.unknown;
        return (
          <li key={i} className="flex gap-2.5 text-sm">
            <Icon aria-hidden className={cn('mt-0.5 size-4 shrink-0', className)} />
            <div className="min-w-0">
              <p className="leading-snug"><span className="font-medium">{item.label}</span>
                <span className="sr-only">: {copy.fitStatus[item.status]}</span>
                {detailed && <span className="ms-2 text-xs font-semibold text-muted-foreground" aria-hidden>{copy.fitStatus[item.status]}</span>}
              </p>
              {detailed && item.note && <p className="mt-1 text-pretty leading-relaxed text-muted-foreground">{item.note}</p>}
              {detailed && item.evidence.map((quote, j) => (
                <p key={j} className="mt-1.5 break-words text-xs text-muted-foreground">{copy.fitFrom}: “{quote}”</p>
              ))}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** Up to two initials, for a path's avatar. */
export const initials = (title: string) => title.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join('');

const DOT: Record<FitItem['status'], string> = {
  have: 'bg-success', partial: 'bg-warning', blocker: 'bg-danger', unknown: 'bg-muted-foreground/30',
};

/** A path's fit at a glance: one dot per requirement, read out as counts. */
export function FitDots({ items, summary }: { items: FitItem[]; summary: string }) {
  if (!items.length) return null;
  const count = (status: FitItem['status']) => String(items.filter((item) => item.status === status).length);
  const label = summary.replace('{have}', count('have')).replace('{partial}', count('partial'))
    .replace('{blocker}', count('blocker')).replace('{unknown}', count('unknown'));
  return (
    <span role="img" aria-label={label} title={label} className="inline-flex items-center gap-1">
      {items.map((item, i) => <span key={i} className={cn('size-2 rounded-full', DOT[item.status] || DOT.unknown)} />)}
    </span>
  );
}

/** The one path card: a colour accent per path (stable by id), the reason it
 * fits in the student's own words, and the actions the caller provides. */
export function PathCardView({ id, tone: given, title, whyLabel, why, evidence, quote, fit = [], studyField, status, statusTone = 'neutral', actions, error, compact = false, headingLevel = 2 }: {
  id: string;
  /** From tonesByOrder; falls back to a hash of the id. */
  tone?: Tone;
  title: string;
  whyLabel: string;
  why: string;
  /** What the reason cites; Vault entries show their badge next to it. */
  evidence?: PathEvidence[];
  quote?: string;
  /** The analyzer's check of this path against the student, when there is one. */
  fit?: FitItem[];
  studyField?: StudyField | null;
  status?: string;
  statusTone?: 'neutral' | 'success' | 'warning' | 'blue';
  actions: React.ReactNode;
  error?: string | null;
  compact?: boolean;
  headingLevel?: 2 | 3;
}) {
  const tone = given || toneFor(id);
  const Heading = `h${headingLevel}` as const;
  return (
    <article className={cn('relative flex min-w-0 flex-col overflow-hidden rounded-3xl border bg-card shadow-card transition-shadow hover:shadow-lift', compact ? 'my-3 max-w-lg' : 'h-full')}>
      <div aria-hidden className={cn('h-1.5 w-full', toneClass[tone].bar)} />
      <div className={cn('flex flex-1 flex-col', compact ? 'p-4' : 'p-5 sm:p-6')}>
        <div className="flex items-start justify-between gap-3">
          <span aria-hidden className={cn('flex size-11 shrink-0 items-center justify-center rounded-2xl', toneClass[tone].soft, toneClass[tone].ink)}>
            <Compass className="size-5" />
          </span>
          {status && <StatChip size="sm" tone={statusTone}>{status}</StatChip>}
        </div>
        <Heading className={cn('mt-3 break-words font-bold tracking-tight', compact ? 'text-lg' : 'text-xl')}>{title}</Heading>
        <FieldNotes field={studyField} className="mt-2" />
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1">
          <p className="text-xs font-semibold text-muted-foreground">{whyLabel}</p>
          <WhyEvidence evidence={evidence} />
        </div>
        <p className="mt-1 text-pretty text-sm leading-relaxed text-muted-foreground">{why}</p>
        {quote && (
          <blockquote className={cn('mt-4 flex gap-2 rounded-2xl px-4 py-3 text-sm', toneClass[tone].soft)}>
            <Quote aria-hidden className={cn('mt-0.5 size-4 shrink-0', toneClass[tone].ink)} />
            <span className="break-words">“{quote}”</span>
          </blockquote>
        )}
        {fit.length > 0 && (
          <section className="mt-4">
            <p className="mb-2 text-xs font-semibold text-muted-foreground">{copy.fitTitle}</p>
            <FitList items={fit} limit={compact ? 3 : undefined} />
          </section>
        )}
        {error && <p role="alert" className="mt-3 text-sm font-medium text-danger-ink">{error}</p>}
        <div className="mt-auto flex flex-wrap gap-2 pt-5">{actions}</div>
      </div>
    </article>
  );
}
