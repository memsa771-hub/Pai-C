import labels from './evidence-labels.json';
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
  return labels.values[String(value) as keyof typeof labels.values] || String(value);
}
