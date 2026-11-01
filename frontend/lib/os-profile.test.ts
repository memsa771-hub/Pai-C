import { describe, expect, it } from 'vitest';
import { degreeMismatch, profileDefaults, profileDegreeField } from './os-profile';
import type { VaultEntry, VaultView } from './vault';

// Fictional values only.
function entry(type: string, value: unknown, display = ''): VaultEntry {
  return { kind: 'fact', type, id: type, value, display, label: type, level: 'stated', badge: '', source: null,
           document: null, observed_at: null, confirmed_at: null, fresh_until: null } as unknown as VaultEntry;
}
const view = (...e: VaultEntry[]): VaultView => ({ details: { basics: { label: 'Basics', entries: e } }, story: [], conflicts: [], stale: [] });

describe('profileDefaults', () => {
  it('fills email, city and country from what PAI knows', () => {
    const v = view(entry('location.current_city', { value: 'Lahore' }), entry('location.current_country', 'Pakistan'));
    expect(profileDefaults(v, 'sara@example.test')).toEqual({ email: 'sara@example.test', city: 'Lahore', country_of_residence: 'Pakistan' });
    expect(profileDefaults(null, null)).toEqual({});
  });
});

describe('degree field', () => {
  it('reads the profile field in words', () => {
    expect(profileDegreeField(view(entry('education', { field_of_study: 'computer_engineering' })))).toBe('Computer Engineering');
    expect(profileDegreeField(view())).toBeNull();
  });

  it('flags a document that names another field, not one that agrees or is unknown', () => {
    expect(degreeMismatch('Computer Engineering', 'Bachelor of Science in Computer Science')).toBe(true);
    expect(degreeMismatch('Computer Engineering', 'BSc Computer Engineering')).toBe(false);
    expect(degreeMismatch(null, 'BSc Computer Science')).toBe(false);
    expect(degreeMismatch('Computer Engineering', null)).toBe(false);
  });
});
