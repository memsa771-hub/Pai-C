'use client';

import { Button } from '@/components/ui/button';
import {
  GATE_NAMES, itemLabel, listProgress, workloadLine, type OsCoverage, type OsGateItem, type OsGateReading,
} from '@/lib/os-coverage';

/** The coverage dashboard of one intake (P2-T9, spec §4.9): the four gate readings, the table per institution type and
 *  the review workload. "Make current" is offered only while the intake is open; the server refuses it while red. */
export function CoverageReport({ report, busy, refused, onMakeCurrent }: {
  report: OsCoverage; busy: boolean; refused: OsGateItem[] | null; onMakeCurrent: () => void;
}) {
  const open = report.intake.state === 'open';
  return (
    <div className="flex flex-col gap-4 text-sm">
      <p className={report.green ? 'font-medium text-emerald-700' : 'font-medium text-destructive'}
         data-testid="gate-overall">
        {report.green ? 'Gate green: every reading passes.' : 'Gate red: some readings fail.'}
      </p>
      <ul className="flex flex-col gap-2">
        {report.readings.map((r) => <Reading key={r.gate} reading={r} />)}
      </ul>
      {open && (
        <div>
          <Button size="sm" disabled={busy || !report.green} onClick={onMakeCurrent}>Make this intake current</Button>
          {!report.green && <p className="mt-1 text-xs text-muted-foreground">Available when the gate is green.</p>}
        </div>
      )}
      {refused && refused.length > 0 && (
        <p role="alert" className="text-destructive">
          The server refused: {refused.length} item(s) still fail.
        </p>
      )}
      <section aria-label="By institution type" className="flex flex-col gap-2">
        <h2 className="font-semibold">By institution type</h2>
        {report.rows.length === 0 && <p className="text-muted-foreground">No institution of this region and family yet.</p>}
        {report.rows.map((row) => (
          <div key={row.institution_type || 'none'} className="rounded-2xl border bg-card p-3">
            <p className="font-medium">{row.institution_type || '(no type)'} · {row.institutions} institutions</p>
            <p className="text-xs text-muted-foreground">
              Listed {row.listed} · researched {row.researched} · verified {row.verified}
              {row.not_readable > 0 && ` · no online information ${row.not_readable}`}
            </p>
            <p className="text-xs text-muted-foreground">
              High-stakes facts: verified {row.hs_verified} · not confirmed {row.hs_not_confirmed} · missing {row.hs_missing}
            </p>
            {row.lists.map((l) => (
              <p key={l.list_id} className="break-words text-xs">{l.name}: {listProgress(l)}</p>
            ))}
          </div>
        ))}
      </section>
      <section aria-label="Other" className="text-xs text-muted-foreground">
        <p>Suspect domains: {report.suspect_domains.length ? report.suspect_domains.join(', ') : 'none'}</p>
        <p>Open review items: {Object.entries(report.open_review_items).map(([k, n]) => `${k} ${n}`).join(', ') || 'none'}</p>
        <p data-testid="workload">Workload: {workloadLine(report.workload)}</p>
      </section>
    </div>
  );
}

function Reading({ reading }: { reading: OsGateReading }) {
  return (
    <li className="rounded-2xl border bg-card p-3" data-gate={reading.gate}>
      <p className="font-medium">
        <span className={reading.green ? 'text-emerald-700' : 'text-destructive'}>{reading.green ? 'Green' : 'Red'}</span>
        {' '}· ({reading.gate}) {GATE_NAMES[reading.gate]} · {reading.checked} checked
      </p>
      <p className="text-xs text-muted-foreground">{reading.title}</p>
      {reading.items.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-xs">
          {reading.items.slice(0, 50).map((i, n) => (
            <li key={n} className="break-words">{itemLabel(i.code)}: {i.subject}{i.detail && ` (${i.detail})`}</li>
          ))}
          {reading.items.length > 50 && <li>and {reading.items.length - 50} more</li>}
        </ul>
      )}
    </li>
  );
}
