'use client';

import { ExternalLink } from 'lucide-react';
import copy from '@/components/counselor/workspace/copy.json';
import { sourceHost } from '@/lib/os-inbox';
import { checkedOn, formatChecked, sourceLevel, type FactLevel } from '@/lib/os-my-plan';
import { useMyPlan } from './my-plan-context';

const t = copy.connect.myPlan;

/** One line under a fact with My plan on (R-54): `<level> · Checked <date> · Source`. Renders nothing with the part off.
 * The date is the one the plan endpoint gives for the url (or `date`, the fact's own); with none it says so. A source the
 * endpoint marks not confirmed is never shown as confirmed. `level` null leaves the level word out. */
export function FactSource({ level, url, date = null }: { level: FactLevel | null; url?: string | null; date?: string | null }) {
  const { on, plan } = useMyPlan();
  if (!on) return null;
  const shown = level && sourceLevel(plan, url, level);
  const when = checkedOn(plan, url) ?? date;
  return (
    <span data-fact-source className="inline-flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
      {shown && <span data-level={shown} className="font-medium">{t.levels[shown]}</span>}
      {shown && <span aria-hidden>·</span>}
      <span>{when ? t.checked.replace('{date}', formatChecked(when)) : t.checkedUnknown}</span>
      {url && (
        <>
          <span aria-hidden>·</span>
          <a href={url} target="_blank" rel="noopener noreferrer" title={sourceHost(url)}
             className="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline">
            {t.source}<ExternalLink className="size-3" aria-hidden />
          </a>
        </>
      )}
    </span>
  );
}
