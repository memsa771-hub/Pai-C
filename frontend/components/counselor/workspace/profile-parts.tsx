"use client";
import { useId } from "react";
import {
  FileText, Gauge, Gem, GraduationCap, Heart, Home, Lightbulb, MessageCircle,
  Scale, Signpost, Sparkles, Target, Users, type LucideIcon,
} from "lucide-react";
import type { LivingPicture } from "@/lib/counselor-workspace";
import type { Tone } from "@/components/pai";
import layout from "./profile-layout.json";

export const text = layout.copy;
export const ICONS: Record<string, LucideIcon> = {
  home: Home, graduation: GraduationCap, heart: Heart, lightbulb: Lightbulb, users: Users, gem: Gem,
  scale: Scale, gauge: Gauge, target: Target, signpost: Signpost, message: MessageCircle, file: FileText,
};
export const areaIcon = (area: string) => ICONS[layout.areaMeta[area as keyof typeof layout.areaMeta]?.icon] || Sparkles;
export const areaTone = (area: string) => (layout.areaMeta[area as keyof typeof layout.areaMeta]?.tone || "blue") as Tone;
const fill = (template: string, values: Record<string, string | number>) =>
  Object.entries(values).reduce((out, [key, value]) => out.replaceAll(`{${key}}`, String(value)), template);
export { fill };

/** A smooth line of real certainty ratings only. Never invents a point. */
export function CertaintyChart({ ratings }: { ratings: NonNullable<LivingPicture["ratings"]> }) {
  const gradient = useId();
  const points = ratings.flatMap((row) => [
    row.before === null ? null : { label: fill(text.before, { version: row.version }), value: row.before },
    row.after === null ? null : { label: fill(text.after, { version: row.version }), value: row.after },
  ]).filter((p): p is { label: string; value: number } => p !== null);
  if (!points.length) return <p className="text-sm text-muted-foreground">{text.certaintyEmpty}</p>;
  const W = 320, H = 150, L = 26, R = 12, T = 14, B = 18;
  const x = (i: number) => L + (points.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (points.length - 1));
  const y = (v: number) => T + ((10 - v) * (H - T - B)) / 10;
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i)} ${y(p.value)}`).join(" ");
  const latest = points.at(-1)!;
  return (
    <div>
      <p className="flex items-baseline gap-1.5">
        <span className="text-4xl font-bold tracking-tight text-brand-ink">{latest.value}</span>
        <span className="text-sm text-muted-foreground">/ 10 · {latest.label}</span>
      </p>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" className="mt-2 h-40 w-full overflow-visible"
        aria-label={`${text.certaintyTitle}. ${points.map((p) => fill(text.certaintyPoint, p)).join(". ")}`}>
        <defs>
          <linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--brand)" stopOpacity="0.28" />
            <stop offset="100%" stopColor="var(--brand)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 5, 10].map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--border)" strokeDasharray={v ? "4 4" : undefined} />
            <text x={L - 8} y={y(v) + 4} textAnchor="end" fontSize="10" fill="var(--muted-foreground)">{v}</text>
          </g>
        ))}
        {points.length > 1 && <path d={`${line} L${x(points.length - 1)} ${y(0)} L${x(0)} ${y(0)} Z`} fill={`url(#${gradient})`} />}
        <path d={line} fill="none" stroke="var(--brand)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        {points.map((p, i) => (
          <g key={i}>
            <circle cx={x(i)} cy={y(p.value)} r="6" fill="var(--card)" stroke="var(--brand)" strokeWidth="3"><title>{fill(text.certaintyPoint, p)}</title></circle>
          </g>
        ))}
      </svg>
      <p className="sr-only">{text.certaintyAxis}</p>
    </div>
  );
}
