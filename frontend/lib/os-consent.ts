/**
 * PAI OS pilot consent (Slice 9a spec §3.2): the current terms and the refusal codes the API sends with a 409.
 * Kept free of React.
 */

export interface OsConsent {
  version: number;
  text: string;
  placeholder: boolean; // the owners have not written the terms yet (accepted only in a rehearsal)
  agreed: boolean;
}

export type ConsentCode = 'consent_needed' | 'consent_version' | 'terms_not_set';

export const CONSENT_NEEDED_TEXT = 'Please agree to the pilot terms first.';

/** The consent refusal in an API error ("API 409: {"detail":{"code":"consent_needed",…}}"), or null. */
export function consentCode(err: unknown): ConsentCode | null {
  const m = err instanceof Error ? /^API 409: ([\s\S]+)$/.exec(err.message) : null;
  if (!m) return null;
  try {
    const code = (JSON.parse(m[1]) as { detail?: { code?: unknown } }).detail?.code;
    return code === 'consent_needed' || code === 'consent_version' || code === 'terms_not_set' ? code : null;
  } catch {
    return null;
  }
}
