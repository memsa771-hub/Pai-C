'use client';

import { useEffect, useState } from 'react';
import { workspaceApi } from '@/lib/api';
import { asReportTexts, asReportableUrls, reportOutcome, type OsReportTexts } from '@/lib/os-report';

interface Loaded { texts: OsReportTexts; urls: Set<string> }
let cached: Promise<Loaded | null> | null = null;

/** The approved sentences and the pages that have facts to report, asked for once. An answer that is not the texts (the
 * part is off, OS_REPORTS unset) leaves the link out. */
function load(): Promise<Loaded | null> {
  cached ??= Promise.resolve().then(async () => {
    const texts = asReportTexts(await workspaceApi.getOsReportTexts());
    return texts ? { texts, urls: asReportableUrls(await workspaceApi.getOsReportSources()) } : null;
  }).catch(() => null);
  return cached;
}

/** "Report as wrong" under a source line (R-28): a reason, optional words, one send. The facts behind the page go back to
 * "not confirmed" at once on the server. Renders nothing until the sentences are there. */
export function ReportLink({ url }: { url: string }) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [detail, setDetail] = useState('');
  const [said, setSaid] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    void load().then((l) => { if (live) setLoaded(l); });
    return () => { live = false; };
  }, []);

  if (!loaded || !loaded.urls.has(url)) return null;  // only under a page that has facts to report
  const texts = loaded.texts;
  const t = texts.texts;
  if (said && !open) return <span data-report-said role="status">{said}</span>;
  if (!open) {
    return (
      <button type="button" data-report-link onClick={() => { setOpen(true); setReason(texts.reasons[0].code); }}
              className="text-primary underline-offset-2 hover:underline">{t.report_link}</button>
    );
  }
  async function send() {
    setBusy(true);
    try {
      await workspaceApi.reportOsSource(url, reason, detail.trim() || null);
      setSaid(reportOutcome(t, null));
    } catch (e) {
      setSaid(reportOutcome(t, e));
    } finally {
      setBusy(false);
      setOpen(false);
    }
  }
  return (
    <form data-report-form aria-label={t.report_title} className="mt-1 flex w-full flex-col gap-1.5"
          onSubmit={(e) => { e.preventDefault(); void send(); }}>
      <label className="text-xs font-medium">{t.report_title}
        <select value={reason} onChange={(e) => setReason(e.target.value)}
                className="ml-1 rounded-md border bg-background px-1 py-0.5">
          {texts.reasons.map((r) => <option key={r.code} value={r.code}>{r.label}</option>)}
        </select>
      </label>
      <textarea value={detail} onChange={(e) => setDetail(e.target.value)} rows={2} maxLength={1000}
                aria-label={t.report_detail_label} placeholder={t.report_detail_label}
                className="w-full min-w-0 rounded-md border bg-background px-2 py-1" />
      <button type="submit" disabled={busy} className="self-start rounded-md border px-2 py-0.5">{t.report_submit}</button>
    </form>
  );
}
