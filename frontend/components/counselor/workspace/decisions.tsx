"use client";
import { useCallback, useState } from "react";
import { ArrowRight, CalendarCheck, Check, Columns2, Compass, Flag, ListChecks, Map as MapIcon, MessageCircle, Scale, Users } from "lucide-react";
import { workspaceApi } from "@/lib/api";
import type { Possibility } from "@/lib/possibilities";
import type { DecisionRecord, Roadmap } from "@/lib/roadmaps";
import { RoadmapsView } from "@/components/roadmaps/roadmaps-view";
import { TryItFeedback } from "@/components/roadmaps/try-it-feedback";
import { Button } from "@/components/ui/button";
import { EmptyState, SectionCard, StatChip, Timeline, toneClass, tonesByOrder } from "@/components/pai";
import { useWorkspace } from "@/lib/workspace-context";
import { cn } from "@/lib/utils";
import { Heading, LoadState, useResource, human } from "./resource";
import copy from "./copy.json";
import { FamilyTalk } from "./family-talk";
import familyCopy from "./family-talk.json";

const fill = (template: string, values: Record<string, string | number>) =>
  Object.entries(values).reduce((out, [key, value]) => out.replaceAll(`{${key}}`, String(value)), template);
const settle = <T,>(read: () => Promise<T>, fallback: T) => Promise.resolve().then(read).catch(() => fallback);
/** Paths, their reviewed roadmaps, and the current decision, read together. */
const loadDecision = async () => {
  const [paths, roadmaps, decision] = await Promise.all([
    workspaceApi.getPossibilities(),
    settle(() => workspaceApi.getRoadmaps(), [] as Roadmap[]),
    settle(() => workspaceApi.getCurrentDecision(), null as DecisionRecord | null),
  ]);
  return { paths, roadmaps: roadmaps || [], decision };
};
const FIT_TONE = { strong: "success", partial: "blue", weak: "warning", not_possible_yet: "warning", unconfirmed: "neutral" } as const;

/** One column per path; the same rows in the same order so the eye can read
 * across. Rows align on wide screens through a subgrid. */
function CompareColumns({ paths, roadmaps, onOpen }: { paths: Possibility[]; roadmaps: Roadmap[]; onOpen: (id: string) => void }) {
  const tones = tonesByOrder(paths.map((p) => p.id));
  const rows = Object.entries(copy.compareRows);
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" style={{ gridTemplateRows: `repeat(${rows.length + 1}, auto)` }}>
      {paths.map((path) => {
        const tone = tones[path.id];
        const roadmap = roadmaps.find((r) => r.id === path.roadmap_id);
        const cells: Record<string, React.ReactNode> = {
          why: <p className="text-sm leading-relaxed">{path.why}</p>,
          words: path.evidence.length
            ? <ul className="space-y-1.5">{path.evidence.slice(0, 2).map((e, i) => <li key={i} className="text-sm italic text-muted-foreground">“{e.text}”</li>)}</ul>
            : <p className="text-sm text-muted-foreground">{copy.nothingRecorded}</p>,
          fit: roadmap
            ? <StatChip size="sm" tone={FIT_TONE[(roadmap.fit_level || "unconfirmed") as keyof typeof FIT_TONE] || "neutral"}>{copy.fitLabels[(roadmap.fit_level || "unconfirmed") as keyof typeof copy.fitLabels] || copy.fitLabels.unconfirmed}</StatChip>
            : <p className="text-sm text-muted-foreground">{copy.noRoadmapYet}</p>,
          risks: roadmap?.risks.length
            ? <ul className="space-y-1 text-sm">{roadmap.risks.slice(0, 2).map((risk, i) => <li key={i}>{risk}</li>)}</ul>
            : <p className="text-sm text-muted-foreground">{copy.nothingRecorded}</p>,
          next: roadmap?.steps[0]
            ? <p className="text-sm">{human(roadmap.steps[0].action ?? roadmap.steps[0])}</p>
            : <p className="text-sm text-muted-foreground">{copy.nothingRecorded}</p>,
        };
        return (
          <article key={path.id} className="row-span-6 grid min-w-0 grid-rows-subgrid gap-0 overflow-hidden rounded-3xl border bg-card shadow-card">
            <header className={cn("flex items-center justify-between gap-3 p-5", toneClass[tone].soft)}>
              <h2 className="min-w-0 break-words text-lg font-bold">{path.title}</h2>
              <Button size="tap" variant="outline" onClick={() => onOpen(path.id)} aria-label={`${copy.openPath}: ${path.title}`}>
                <Compass aria-hidden /><span className="max-sm:sr-only">{copy.openPath}</span>
              </Button>
            </header>
            {rows.map(([key, label]) => (
              <section key={key} className="border-t px-5 py-4">
                <h3 className={cn("mb-1.5 text-xs font-bold uppercase tracking-wider", toneClass[tone].ink)}>{label}</h3>
                {cells[key]}
              </section>
            ))}
          </article>
        );
      })}
    </div>
  );
}

/** The decision itself: what was chosen (never chosen for the student) and a
 * certainty slider whose value is only shared when the student says so. */
function DecisionCard({ roadmaps, decision }: { roadmaps: Roadmap[]; decision: DecisionRecord | null }) {
  const { currentUser } = useWorkspace();
  const chosen = roadmaps.find((r) => r.chosen_at);
  const [value, setValue] = useState(5), [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false), [sent, setSent] = useState(false), [error, setError] = useState(false);
  async function share() {
    if (!currentUser) return;
    setBusy(true); setError(false);
    try {
      const template = chosen ? copy.decisionCertaintyReply : copy.certaintyReply;
      await workspaceApi.sendMessage("pai-counselor", fill(template, { value, max: 10 }), currentUser.name, undefined, undefined, currentUser.id);
      setSent(true);
    } catch { setError(true); } finally { setBusy(false); }
  }
  const question = chosen ? copy.decisionCertainty : copy.decisionCertaintyNone;
  return (
    <section aria-labelledby="decision-title" className={cn("rounded-3xl p-5 sm:p-7", chosen ? "bg-success-soft" : "bg-brand-soft")}>
      <div className="flex flex-wrap items-start gap-4">
        <span aria-hidden className={cn("flex size-12 shrink-0 items-center justify-center rounded-2xl bg-card shadow-soft", chosen ? "text-success-ink" : "text-brand-ink")}>
          {chosen ? <Flag className="size-6" /> : <Scale className="size-6" />}
        </span>
        <div className="min-w-0 flex-1">
          <h2 id="decision-title" className="text-xs font-bold uppercase tracking-wider text-muted-foreground">{copy.decisionTitle}</h2>
          <p className="mt-1 text-pretty text-xl font-bold">{chosen ? fill(copy.decisionChosen, { title: chosen.title }) : copy.decisionNone}</p>
          {chosen && decision?.real_objective && (
            <p className="mt-2 text-sm"><span className="font-semibold">{copy.decisionWhy}: </span>{decision.real_objective}</p>
          )}
        </div>
      </div>
      <div className="mt-5 rounded-2xl bg-card p-4 shadow-soft">
        {sent ? (
          <p role="status" className="flex items-center gap-2 text-sm font-medium text-success-ink"><Check aria-hidden className="size-4" />{copy.decisionShared}</p>
        ) : (
          <>
            <label htmlFor="decision-certainty" className="text-sm font-semibold">{question}</label>
            <div className="mt-2 flex items-center gap-3">
              <input id="decision-certainty" type="range" min={0} max={10} step={1} value={value}
                onChange={(e) => { setValue(Number(e.target.value)); setTouched(true); }}
                onPointerDown={() => setTouched(true)}
                onKeyDown={(e) => { if ([" ", "Enter"].includes(e.key)) setTouched(true); }}
                aria-valuetext={`${value} / 10`} className="h-11 flex-1 accent-[var(--brand)]" />
              <span aria-hidden className="w-14 text-right text-lg font-bold tabular-nums">{value}/10</span>
            </div>
            <div aria-hidden className="flex justify-between text-xs text-muted-foreground"><span>{copy.ratingLow}</span><span>{copy.ratingHigh}</span></div>
            <p className="mt-2 text-xs text-muted-foreground">{copy.decisionHint}</p>
            {error && <p role="alert" className="mt-2 text-sm font-medium text-danger-ink">{copy.error}</p>}
            <Button size="tap" className="mt-3" disabled={busy || !touched} onClick={share}><MessageCircle aria-hidden />{copy.decisionShare}</Button>
          </>
        )}
      </div>
    </section>
  );
}

export function Compare({
  onChat,
  onOpen,
}: {
  onChat: (text: string) => void;
  onOpen: (id: string) => void;
}) {
  const load = useCallback(loadDecision, []);
  const resource = useResource(load);
  const [familyOpen, setFamilyOpen] = useState(false);
  const live = resource.data?.paths.filter((p) => p.status !== "dismissed") || [];
  return (
    <>
      <Heading title={copy.compare} description={copy.chooseHelp} icon={Columns2} tone="amber" />
      {!resource.data || resource.error ? (
        <LoadState error={resource.error} busy={resource.busy} retry={resource.refresh} />
      ) : (
        <div className="space-y-6">
          {live.length ? (
            <CompareColumns paths={live} roadmaps={resource.data.roadmaps} onOpen={onOpen} />
          ) : (
            <EmptyState icon={Columns2} tone="amber" title={copy.compareEmptyTitle} description={copy.compareEmptyBody}
              action={<Button size="tap" onClick={() => onChat("")}><MessageCircle aria-hidden />{copy.openChat}</Button>} />
          )}
          <DecisionCard roadmaps={resource.data.roadmaps} decision={resource.data.decision} />
          <SectionCard title={familyCopy.title} description={copy.familyIntro} icon={Users} tone="teal"
            action={<Button size="tap" variant={familyOpen ? "ghost" : "soft"} aria-expanded={familyOpen} onClick={() => setFamilyOpen(!familyOpen)}>
              {familyOpen ? copy.cancel : copy.family}</Button>}>
            {familyOpen && <FamilyTalk />}
          </SectionCard>
          <SectionCard title={copy.roadmapsTitle} description={copy.roadmapsIntro} icon={MapIcon} tone="violet">
            <p className="mb-4 rounded-2xl bg-muted/60 px-4 py-3 text-sm text-muted-foreground">{copy.decisionPending}</p>
            <RoadmapsView pathOnly onChanged={resource.refresh} />
          </SectionCard>
        </div>
      )}
    </>
  );
}

export function Plan({ onChat, onNavigate }: { onChat: (text: string) => void; onNavigate?: (view: string) => void }) {
  const load = useCallback(loadDecision, []);
  const resource = useResource(load);
  const chosen = resource.data?.roadmaps.find((r) => r.chosen_at);
  return (
    <>
      <Heading title={copy.planTitle} description={copy.planIntro} icon={ListChecks} tone="sky" />
      <section className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-3xl bg-gradient-to-br from-tone-sky-soft to-tone-blue-soft p-6 sm:p-7">
        <div className="flex min-w-0 max-w-xl items-start gap-3">
          <span aria-hidden className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-card text-tone-sky-ink shadow-soft"><CalendarCheck className="size-5" /></span>
          <div>
            <h2 className="text-lg font-bold">{copy.checkin}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{copy.checkinHelp}</p>
          </div>
        </div>
        <Button size="tap" onClick={() => onChat(copy.checkin)}><MessageCircle aria-hidden />{copy.moment}</Button>
      </section>
      {!resource.data || resource.error ? (
        <LoadState error={resource.error} busy={resource.busy} retry={resource.refresh} skeleton="list" />
      ) : chosen ? (
        <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
          <SectionCard title={fill(copy.decisionChosen, { title: chosen.title })} icon={Flag} tone="blue">
            {chosen.steps.length ? (
              <Timeline label={copy.planStepsTitle} items={chosen.steps.map((step, i) => ({
                id: String(i), marker: i + 1, state: i === 0 ? "now" : "next",
                title: <h3 className="text-base"><span className="sr-only">{fill(copy.stepLabel, { n: i + 1 })}: </span>{human(step.action ?? step)}</h3>,
              }))} />
            ) : <p className="text-sm text-muted-foreground">{copy.nothingRecorded}</p>}
          </SectionCard>
          <div className="space-y-5">
            {chosen.risks.length > 0 && (
              <SectionCard title={copy.planRisks} icon={Scale} tone="amber">
                <ul className="space-y-2 text-sm">{chosen.risks.map((risk, i) => <li key={i} className="rounded-xl bg-warning-soft px-3 py-2 text-warning-ink">{risk}</li>)}</ul>
              </SectionCard>
            )}
            {chosen.try_it && <TryItFeedback roadmap={chosen} headingLevel={2} />}
          </div>
        </div>
      ) : (
        <EmptyState icon={Flag} tone="sky" title={copy.planNoRouteTitle} description={copy.planNoRouteBody}
          action={onNavigate && <Button size="tap" onClick={() => onNavigate("compare")}>{copy.planGoCompare}<ArrowRight aria-hidden /></Button>} />
      )}
    </>
  );
}
