import labels from './evidence-labels.json';
import { formatDate } from './i18n/format';
import { DEFAULT_LOCALE } from './i18n/locales';

/** ISO dates read as "30 May 2024", never as a raw timestamp. */
const ISO_DATE = /^\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)?$/;
export function evidenceLabel(key: string): string {
  return labels.labels[key as keyof typeof labels.labels] || labels.fallback;
}
export function evidenceText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '';
  if (Array.isArray(value)) return value.map(evidenceText).filter(Boolean).join(labels.separator);
  if (typeof value === 'object') return Object.entries(value as Record<string,unknown>)
    .filter(([key])=>!labels.hidden.includes(key))
    .map(([key,item])=>{
      const text=evidenceText(item); if(!text) return '';
      const label=labels.labels[key as keyof typeof labels.labels];
      // Unknown keys never expose schema identifiers; their student value remains.
      return label?labels.fieldTemplate.replace('{label}',label).replace('{value}',text):text;
    }).filter(Boolean).join(labels.separator);
  if (typeof value === 'boolean') return value?labels.yes:labels.no;
  if (typeof value === 'string' && ISO_DATE.test(value)) {
    // A date-only value is a calendar day; showing it in UTC keeps it from
    // slipping to the previous day in time zones behind UTC.
    const date = formatDate(value, DEFAULT_LOCALE, { day: 'numeric', month: 'short', year: 'numeric',
      ...(value.length === 10 ? { timeZone: 'UTC' } : {}) });
    if (date) return date;
  }
  return labels.values[String(value) as keyof typeof labels.values] || String(value);
}
