import { BadgeCheck, Eye, MessageCircle, Circle } from 'lucide-react';
import { cn } from '@/lib/utils';
import copy from './kit-copy.json';

export type EvidenceLevel = 'none' | 'stated' | 'shown' | 'confirmed';
export const EVIDENCE_LEVELS: EvidenceLevel[] = ['none', 'stated', 'shown', 'confirmed'];
const icons = { none: Circle, stated: MessageCircle, shown: Eye, confirmed: BadgeCheck };
const styles: Record<EvidenceLevel, string> = {
  none: 'bg-evidence-0 text-evidence-0-ink',
  stated: 'bg-evidence-1 text-evidence-1-ink',
  shown: 'bg-evidence-2 text-evidence-2-ink',
  confirmed: 'bg-evidence-3 text-evidence-3-ink',
};

export function evidenceLevel(value: unknown): EvidenceLevel {
  return EVIDENCE_LEVELS.includes(value as EvidenceLevel) ? value as EvidenceLevel : 'none';
}

/** Evidence is shown with an icon and a word, never by colour alone. */
export function EvidenceBadge({ level, className, label }: { level: EvidenceLevel; className?: string; label?: string }) {
  const Icon = icons[level];
  return (
    <span title={copy.evidenceHelp[level]}
      className={cn('inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold', styles[level], className)}>
      <Icon aria-hidden className="size-3.5" />
      {label || copy.evidence[level]}
    </span>
  );
}
export const evidenceFill = styles;
