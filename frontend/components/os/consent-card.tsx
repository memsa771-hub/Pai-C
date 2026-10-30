'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { workspaceApi } from '@/lib/api';
import { CONSENT_NEEDED_TEXT, consentCode, type OsConsent } from '@/lib/os-consent';

/**
 * The pilot consent card (Slice 9a spec §3.2, §6): the terms text, "This is a pilot", and one "I agree" button.
 * `refused` is set by a page whose start or upload was refused for missing consent.
 * `onChanged` asks the page to load the terms again (they changed while the card was open).
 */
export function ConsentCard({ consent, refused = false, onAgreed, onChanged }: {
  consent: OsConsent; refused?: boolean; onAgreed: () => void; onChanged?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const agree = async () => {
    setBusy(true);
    setError(null);
    try {
      await workspaceApi.agreeOsConsent(consent.version);
      onAgreed();
    } catch (e) {
      const code = consentCode(e);
      if (code === 'consent_version') {
        setError(CONSENT_NEEDED_TEXT);
        onChanged?.();
      } else if (code === 'terms_not_set') {
        setError('The pilot terms are not ready yet. Please try again later.');
      } else {
        setError('Could not save. Please try again.');
      }
    } finally {
      setBusy(false);
    }
  };

  const message = error ?? (refused ? CONSENT_NEEDED_TEXT : null);
  return (
    <section aria-labelledby="os-consent-title" className="rounded-lg border bg-card p-4 text-sm">
      <h2 id="os-consent-title" className="font-semibold">This is a pilot</h2>
      {message && <p role="alert" className="mt-2 break-words text-destructive">{message}</p>}
      <div className="mt-3 max-h-[60vh] overflow-y-auto whitespace-pre-wrap break-words text-muted-foreground">
        {consent.text}
      </div>
      <Button className="mt-4 w-full" disabled={busy} onClick={agree}>I agree</Button>
    </section>
  );
}
