/** What the study abroad plan takes from the student's PAI profile (pai-merge hand test: the pack asked again for an
 * email, city and country PAI already had, and showed "Computer Science" from a document beside a profile that says
 * "Computer Engineering" with no word about it). Suggestions only: the student still checks and saves them. */
import type { VaultEntry, VaultView } from './vault';

function entries(view: VaultView | null): VaultEntry[] {
  return view ? Object.values(view.details).flatMap((s) => s.entries) : [];
}

function text(entry: VaultEntry | undefined): string | null {
  if (!entry) return null;
  const v = entry.value;
  if (typeof v === 'string' && v.trim()) return v.trim();
  if (v && typeof v === 'object' && typeof (v as { value?: unknown }).value === 'string') return (v as { value: string }).value.trim() || null;
  return entry.display?.trim() || null;
}

/** Contact fields a pack asks for, filled from the profile where PAI knows them (data-sheet keys). */
export function profileDefaults(view: VaultView | null, email: string | null): Record<string, string> {
  const all = entries(view);
  const of = (type: string) => text(all.find((e) => e.type === type));
  const out: Record<string, string> = {};
  if (email) out.email = email;
  const city = of('location.current_city');
  const country = of('location.current_country');
  if (city) out.city = city;
  if (country) out.country_of_residence = country;
  return out;
}

/** The field of the student's latest degree in the profile, in words ("computer_engineering" -> "Computer Engineering"). */
export function profileDegreeField(view: VaultView | null): string | null {
  const degrees = entries(view).filter((e) => e.type === 'education' && e.value && typeof e.value === 'object');
  for (const e of degrees.reverse()) {
    const field = (e.value as { field_of_study?: unknown }).field_of_study;
    if (typeof field === 'string' && field.trim()) {
      return field.trim().replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
    }
  }
  return null;
}

const STOP = new Set(['of', 'in', 'and', 'the', 'bachelor', 'master', 'science', 'arts', 'bs', 'bsc', 'ms', 'msc', 'be', 'b', 'degree']);
const words = (s: string) => s.toLowerCase().split(/[^a-z0-9]+/).filter((w) => w && !STOP.has(w));

/** True when a document's degree title names a different field than the profile ("Computer Science" against
 * "Computer Engineering"). Unknown on either side is not a mismatch. */
export function degreeMismatch(profileField: string | null, degreeTitle: string | null): boolean {
  if (!profileField || !degreeTitle) return false;
  const doc = new Set(words(degreeTitle));
  const want = words(profileField);
  return want.length > 0 && !want.every((w) => doc.has(w));
}
