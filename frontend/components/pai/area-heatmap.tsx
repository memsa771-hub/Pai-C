'use client';
import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { EvidenceBadge, evidenceFill, EVIDENCE_LEVELS, type EvidenceLevel } from './evidence-badge';
import copy from './kit-copy.json';

export type HeatmapArea = {
  key: string;
  label: string;
  icon: LucideIcon;
  level: EvidenceLevel;
  /** How many pieces of evidence exist; rendered as up to three dots. */
  count: number;
};

const plural = (count: number) =>
  (count === 1 ? copy.heatmapItems.one : copy.heatmapItems.other).replace('{count}', String(count));

/** Ten understanding areas. Fill = strength of evidence, dots = amount.
 * Tapping an area filters the details; it is never presented as a score. */
export function AreaHeatmap({ areas, selected, onSelect, title }: {
  areas: HeatmapArea[];
  selected?: string | null;
  onSelect?: (key: string | null) => void;
  title: string;
}) {
  return (
    <div>
      <ul aria-label={title} className="grid grid-cols-2 gap-2 sm:grid-cols-5 sm:gap-3">
        {areas.map((area) => {
          const Icon = area.icon;
          const active = selected === area.key;
          const dots = Math.min(3, area.count);
          return (
            <li key={area.key} className="min-w-0">
              <button
                type="button"
                onClick={() => onSelect?.(active ? null : area.key)}
                aria-pressed={active}
                aria-label={`${area.label}: ${copy.evidence[area.level]}, ${plural(area.count)}. ${copy.heatmapFilter.replace('{area}', area.label)}`}
                className={cn(
                  'group flex h-full min-h-[92px] w-full flex-col justify-between gap-2 rounded-2xl p-3 text-left transition-[transform,box-shadow] duration-200',
                  'hover:-translate-y-0.5 hover:shadow-card focus-visible:-translate-y-0.5',
                  evidenceFill[area.level],
                  active && 'ring-2 ring-foreground ring-offset-2 ring-offset-card',
                )}
              >
                <span className="flex items-center justify-between gap-2">
                  <Icon aria-hidden className="size-5 shrink-0" />
                  <span aria-hidden className="flex gap-1">
                    {[0, 1, 2].map((i) => (
                      <span key={i} className={cn('size-1.5 rounded-full bg-current', i < dots ? 'opacity-100' : 'opacity-25')} />
                    ))}
                  </span>
                </span>
                <span className="text-sm font-semibold leading-tight">{area.label}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <div className="mt-4 flex flex-wrap items-center gap-2" aria-hidden>
        {EVIDENCE_LEVELS.map((level) => <EvidenceBadge key={level} level={level} />)}
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{copy.heatmapLegend}</p>
    </div>
  );
}
