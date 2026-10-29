"use client";
/** A route's steps, coloured from the Vault (backend roadmap/steps.py): green
 * done, yellow partly done, red not yet. Colour never stands alone: every step
 * also says its status in words and shows its evidence badge, its source, the
 * rule behind it and when it happens. */
import { CalendarClock, Check, CircleDot, ExternalLink, Hourglass } from "lucide-react";
import type { RouteStep, RouteTime, StepStatus } from "@/lib/roadmap";
import { EvidenceBadge, vaultBadgeLabel } from "@/components/pai";
import { cn } from "@/lib/utils";
import { fill, stepLabel, stepWhen, timeText } from "./roadmap-text";
import copy from "./copy.json";

const t = copy.roadmap;
const STYLE: Record<StepStatus, { dot: string; ink: string; bar: string; icon: typeof Check }> = {
  done: { dot: "bg-success text-white dark:text-[#04201c]", ink: "text-success-ink", bar: "bg-success", icon: Check },
  half: { dot: "bg-warning text-[#2b1700]", ink: "text-warning-ink", bar: "bg-warning", icon: Hourglass },
  not: { dot: "bg-danger text-white dark:text-[#2a0710]", ink: "text-danger-ink", bar: "bg-danger", icon: CircleDot },
};
export const statusWord = (status: StepStatus) => t.templates[`status_${status}`];

export function StepDot({ status, size = "md" }: { status: StepStatus; size?: "sm" | "md" }) {
  const { dot, icon: Icon } = STYLE[status] || STYLE.not;
  return (
    <span aria-hidden className={cn("relative z-10 flex shrink-0 items-center justify-center rounded-full ring-4 ring-card", dot,
      size === "md" ? "size-7" : "size-6")}>
      <Icon className={size === "md" ? "size-4" : "size-3.5"} strokeWidth={2.5} />
    </span>
  );
}

const host = (url: string) => {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
};

/** Status word, evidence badge and source, when, and the rule link. */
export function StepMeta({ step, time, showStatus = true }: { step: RouteStep; time?: RouteTime | null; showStatus?: boolean }) {
  const when = stepWhen(step, time);
  return (
    <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-muted-foreground">
      {showStatus && <span data-status-word className={cn("font-semibold", STYLE[step.status]?.ink)}>{statusWord(step.status)}</span>}
      {step.evidence && (
        <span className="inline-flex min-w-0 max-w-full items-center gap-1.5">
          <EvidenceBadge level={step.evidence.level} label={vaultBadgeLabel(step.evidence.level)} />
          <span className="truncate">{step.evidence.source_label}</span>
        </span>
      )}
      {when && <span className="inline-flex items-center gap-1"><CalendarClock aria-hidden className="size-3.5 shrink-0" /><span>{when}</span></span>}
      {step.rule?.source && (
        <a href={step.rule.source} target="_blank" rel="noopener noreferrer" aria-label={fill(t.steps.ruleLabel, { host: host(step.rule.source) })}
          className="inline-flex min-h-6 min-w-0 max-w-full items-center gap-1 font-medium text-primary hover:underline">
          <span className="shrink-0">{t.steps.rule}</span><span aria-hidden>·</span>
          <span className="truncate">{host(step.rule.source)}</span><ExternalLink aria-hidden className="size-3 shrink-0" />
        </a>
      )}
    </div>
  );
}

/** The route sheet's timeline: one card per step on a coloured line. */
export function RouteSteps({ steps, time, label }: { steps: RouteStep[]; time?: RouteTime | null; label: string }) {
  if (!steps.length) return <p className="text-sm text-muted-foreground">{t.steps.none}</p>;
  return (
    <ol aria-label={label} className="relative">
      {steps.map((step, i) => (
        <li key={step.key} data-status={step.status} className="relative flex min-w-0 gap-3 pb-3 last:pb-0">
          {i < steps.length - 1 && <span aria-hidden className={cn("absolute left-3.5 top-7 -bottom-0 w-0.5 -translate-x-1/2 rounded-full opacity-40", STYLE[step.status]?.bar)} />}
          <span className="pt-2.5"><StepDot status={step.status} /></span>
          <div className="min-w-0 flex-1 rounded-2xl bg-background px-3.5 py-2.5 ring-1 ring-border/70">
            <h3 className="break-words text-sm font-semibold leading-snug">{stepLabel(step)}</h3>
            <StepMeta step={step} time={time} />
          </div>
        </li>
      ))}
    </ol>
  );
}

/** The route as one coloured bar: a segment per step. */
export function StepBar({ steps, className }: { steps: RouteStep[]; className?: string }) {
  return (
    <span aria-hidden className={cn("flex gap-1", className)}>
      {steps.map((step) => <span key={step.key} className={cn("h-2 min-w-0 flex-1 rounded-full", STYLE[step.status]?.bar)} />)}
    </span>
  );
}

/** "About 11 months to entry · about 4.9 years to finish" and how sure the dates are. */
export function TimeLine({ time, className }: { time?: RouteTime | null; className?: string }) {
  const { main, note } = timeText(time);
  if (!main) return null;
  return (
    <div className={cn("min-w-0", className)}>
      <p className="flex items-start gap-1.5 text-sm font-semibold"><CalendarClock aria-hidden className="mt-0.5 size-4 shrink-0 text-primary" /><span>{main}</span></p>
      {note && <p className="mt-0.5 ps-[22px] text-xs text-muted-foreground">{note}</p>}
    </div>
  );
}
