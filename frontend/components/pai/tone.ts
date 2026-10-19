/** Accent tones from the design tokens. Class strings stay literal so
 * Tailwind can see them; components pick a tone, never a raw colour. */
export type Tone = 'blue' | 'violet' | 'teal' | 'amber' | 'rose' | 'sky';
export const TONES: Tone[] = ['blue', 'violet', 'teal', 'amber', 'rose', 'sky'];

export const toneClass: Record<Tone, { solid: string; soft: string; ink: string; ring: string; bar: string }> = {
  blue: { solid: 'bg-tone-blue text-white dark:text-[#0a1028]', soft: 'bg-tone-blue-soft', ink: 'text-tone-blue-ink', ring: 'ring-tone-blue/40', bar: 'bg-tone-blue' },
  violet: { solid: 'bg-tone-violet text-white dark:text-[#0a1028]', soft: 'bg-tone-violet-soft', ink: 'text-tone-violet-ink', ring: 'ring-tone-violet/40', bar: 'bg-tone-violet' },
  teal: { solid: 'bg-tone-teal text-[#04201c]', soft: 'bg-tone-teal-soft', ink: 'text-tone-teal-ink', ring: 'ring-tone-teal/40', bar: 'bg-tone-teal' },
  amber: { solid: 'bg-tone-amber text-[#2b1700]', soft: 'bg-tone-amber-soft', ink: 'text-tone-amber-ink', ring: 'ring-tone-amber/40', bar: 'bg-tone-amber' },
  rose: { solid: 'bg-tone-rose text-[#2b0614]', soft: 'bg-tone-rose-soft', ink: 'text-tone-rose-ink', ring: 'ring-tone-rose/40', bar: 'bg-tone-rose' },
  sky: { solid: 'bg-tone-sky text-[#03263a]', soft: 'bg-tone-sky-soft', ink: 'text-tone-sky-ink', ring: 'ring-tone-sky/40', bar: 'bg-tone-sky' },
};

/** A stable tone for any id (FNV-1a), for things without a list order. */
export function toneFor(seed: string): Tone {
  let hash = 0x811c9dc5;
  for (let i = 0; i < seed.length; i++) hash = Math.imul(hash ^ seed.charCodeAt(i), 0x01000193) >>> 0;
  return TONES[hash % TONES.length];
}

/** Distinct tones for a list (up to six), by position in the student's own
 * list, so two paths side by side never share a colour. */
export function tonesByOrder(ids: string[]): Record<string, Tone> {
  return Object.fromEntries(ids.map((id, i) => [id, TONES[(i + 1) % TONES.length]]));
}
