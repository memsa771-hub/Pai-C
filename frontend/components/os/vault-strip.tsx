'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ArrowRight, Plane } from 'lucide-react';
import { workspaceApi } from '@/lib/api';
import { OS_UI_ENABLED } from '@/lib/config';
import { docStatusLabel, typeLabel, type OsDocuments } from '@/lib/os-documents';
import { useT } from '@/lib/i18n';

/** The study abroad plan's documents in the Vault (pai-merge hand test: 9 confirmed documents there, and the Vault
 * said "No files yet"). Read only: they are uploaded and checked on the plan's Documents page, one tap away.
 * Nothing shows when the plan is off or has no documents. */
export function OsVaultStrip() {
  return OS_UI_ENABLED ? <OsVaultStripShown /> : null;
}

function OsVaultStripShown() {
  const workspaceId = useParams<{ workspaceId: string }>()?.workspaceId;  // null outside a workspace route
  const t = useT();
  const [data, setData] = useState<OsDocuments | null>(null);
  useEffect(() => {
    let active = true;
    workspaceApi.getOsDocuments().then((d) => { if (active) setData(d); }).catch(() => {});
    return () => { active = false; };
  }, []);
  const docs = (data?.documents ?? []).filter((d) => d.status !== 'deleted');
  if (!data || docs.length === 0 || !workspaceId) return null;
  return (
    <section aria-label={t('nav.studyAbroadPlan')} className="mb-4 shrink-0 rounded-[22px] bg-card p-4 shadow-card ring-1 ring-border/70">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-bold">
          <Plane aria-hidden className="size-4 text-primary" />{t('nav.studyAbroadPlan')}
        </h2>
        <Link href={`/${workspaceId}/os-documents`} className="inline-flex items-center gap-1 text-sm font-semibold text-primary hover:underline">
          {t('nav.osDocuments')}<ArrowRight aria-hidden className="size-4" />
        </Link>
      </div>
      <ul className="mt-3 flex flex-wrap gap-2">
        {docs.map((d) => (
          <li key={d.id} className="rounded-full bg-muted px-3 py-1 text-xs">
            <span className="font-semibold">{typeLabel(d.doc_type, data.doc_types)}</span>
            <span className="text-muted-foreground"> · {docStatusLabel(d)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
