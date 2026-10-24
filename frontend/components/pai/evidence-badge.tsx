import { BadgeCheck, Eye, MessageCircle, Circle, CircleHelp, Sparkles } from 'lucide-react';
import { cn } from '@/lib/utils';
import copy from './kit-copy.json';

export type EvidenceLevel = 'none' | 'stated' | 'shown' | 'confirmed';
export const EVIDENCE_LEVELS: EvidenceLevel[] = ['none', 'stated', 'shown', 'confirmed'];
/** Two more badges the Vault uses: a value PAI only guessed, and one waiting
 * on the student's answer. They sit outside the ladder (and the heatmap). */
export type BadgeLevel = EvidenceLevel | 'inferred' | 'question';
const icons = { none: Circle, stated: MessageCircle, shown: Eye, confirmed: BadgeCheck, inferred: Sparkles, question: CircleHelp };
const styles: Record<EvidenceLevel, string> = {
  none: 'bg-evidence-0 text-evidence-0-ink',
  stated: 'bg-evidence-1 text-evidence-1-ink',
  shown: 'bg-evidence-2 text-evidence-2-ink',
  confirmed: 'bg-evidence-3 text-evidence-3-ink',
};

/** Badges stay quiet: a word and an icon in muted ink; only "confirmed"
 * carries colour, because it is the one the student did themselves. */
const quiet: Record<BadgeLevel, string> = {
  none: 'text-muted-foreground',
  inferred: 'text-muted-foreground',
  question: 'text-warning-ink',
  stated: 'text-muted-foreground',
  shown: 'text-foreground',
  confirmed: 'text-success-ink',
};

export function evidenceLevel(value: unknown): EvidenceLevel {
  return EVIDENCE_LEVELS.includes(value as EvidenceLevel) ? value as EvidenceLevel : 'none';
}

/** Evidence is shown with an icon and a word, never by colour alone. */
export function EvidenceBadge({ level, className, label, compact = false }: { level: BadgeLevel; className?: string; label?: string; compact?: boolean }) {
  const Icon = icons[level];
  return (
    <span title={`${label || copy.evidence[level]}: ${copy.evidenceHelp[level]}`}
      className={cn('inline-flex shrink-0 items-center gap-1 py-0.5 text-xs font-semibold', quiet[level], className)}>
      <Icon aria-hidden className={compact ? 'size-4' : 'size-3.5'} />
      <span className={cn(compact && 'sr-only')}>{label || copy.evidence[level]}</span>
    </span>
  );
}
/** The Vault's badge words (VAULT_SPEC: Stated, From document, PAI's guess,
 * Confirmed, In question); "shown" there always means a document. */
export const vaultBadgeLabel = (level: Exclude<BadgeLevel, 'none'>) => copy.vaultEvidence[level];
export const evidenceFill = styles;
export const evidenceIcons = icons;
