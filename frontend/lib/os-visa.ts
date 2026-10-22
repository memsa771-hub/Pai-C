/**
 * PAI OS visa file: types and pure helpers. Data comes from GET /v1/os/visa (backend/app/os/api/packs.py, Slice 6b
 * spec §4-5). Kept free of React. Nothing here knows a country or a currency: the amount's label, the steps and the
 * checklist come from the API.
 */

import type { OsPack } from './os-packs';

export interface OsFunds {
  required: number | null; // null: the route's amount is not known yet
  base: number | null;
  months: number;
  reduction: number;
  currency_label: string;
  status: string; // confirmed, unconfirmed, stale, or missing
  quote: string | null;
  url: string | null;
}

export interface OsVisaChoice {
  programme_ref: string | null; // what the student chose
  reduction: number;
  preselected: string | null; // the programme the student said admitted them
}

export interface OsVisaProgramme {
  programme_ref: string;
  name: string | null;
  university: string | null;
}

export interface OsVisa extends Omit<OsPack, 'programme_ref' | 'status'> {
  programme_ref: string | null;
  status: OsPack['status'] | 'no_choice';
  funds: OsFunds | null;
  choice: OsVisaChoice;
  programmes: OsVisaProgramme[];
}

/** "11904 EUR", or "not confirmed yet" when the route's amount is missing. */
export function fundsLine(f: OsFunds | null): string {
  if (f === null || f.required === null) return 'not confirmed yet';
  return `${Number.isInteger(f.required) ? f.required : f.required.toFixed(2)} ${f.currency_label}`;
}

export function programmeLabel(p: OsVisaProgramme): string {
  return [p.university, p.name ?? p.programme_ref].filter(Boolean).join(' · ');
}

/** The visa file as a pack, for PackView (it is built and shown the same way: Slice 6b S6b-D2). */
export function asPack(v: OsVisa): OsPack {
  return { ...v, programme_ref: v.programme_ref ?? '', status: v.status === 'no_choice' ? 'incomplete' : v.status };
}
