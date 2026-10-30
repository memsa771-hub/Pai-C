'use client';

import { ExternalLink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { statusLabel } from '@/lib/os-programmes';
import {
  CARD_FOOTER,
  PROVISIONAL_TEXT,
  checkLabel,
  chipLabel,
  chipTone,
  lineText,
  type OsCard,
  type OsSuggestion,
} from '@/lib/os-self-serve';
import { sourceHost } from '@/lib/os-inbox';

interface EligibilityCardProps {
  card: OsCard;
  suggestions?: OsSuggestion[];
  onSwap?: (suggestion: OsSuggestion) => void;
}

/** One programme's eligibility card (Slice 4 spec §5): a line per check, an estimate that never blocks. */
export function EligibilityCard({ card, suggestions = [], onSwap }: EligibilityCardProps) {
  const provisional = card.lines.some((l) => l.provisional);
  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-card p-3 text-sm">
      <ul className="flex flex-col gap-2">
        {card.lines.map((l) => (
          <li key={l.check} className="flex flex-col gap-0.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{checkLabel(l.check)}</span>
              <span className={`rounded px-1.5 py-0.5 text-xs ${chipTone(l.status)}`}>{chipLabel(l.status)}</span>
              {l.provisional && <span className="rounded bg-muted px-1.5 py-0.5 text-xs">provisional</span>}
            </div>
            <p className="break-words text-muted-foreground">{lineText(l)}</p>
            {l.sources.map((s) => (
              <a key={s.url + s.field} href={s.url} target="_blank" rel="noopener noreferrer"
                 className="inline-flex flex-wrap items-center gap-1 break-words text-xs text-primary underline-offset-2 hover:underline">
                source: {sourceHost(s.url)} · {statusLabel(s.status)}
                <ExternalLink className="size-3" aria-hidden />
              </a>
            ))}
          </li>
        ))}
      </ul>
      {provisional && <p className="break-words text-xs text-muted-foreground">{PROVISIONAL_TEXT}</p>}
      {suggestions.length > 0 && (
        <div className="flex flex-col gap-1 border-t pt-2">
          <p className="text-xs font-semibold text-muted-foreground">Programmes that may suit you better</p>
          {suggestions.map((s) => (
            <div key={s.programme_ref} className="flex items-center justify-between gap-2">
              <span className="min-w-0 flex-1 break-words">{s.name} · {s.university}</span>
              {onSwap && <Button size="sm" variant="outline" onClick={() => onSwap(s)}>Swap</Button>}
            </div>
          ))}
        </div>
      )}
      <p className="break-words text-xs text-muted-foreground">{CARD_FOOTER}</p>
    </div>
  );
}
