"use client";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Check, MessageCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatChip } from "@/components/pai";
import { cn } from "@/lib/utils";
import { Heading, LoadState } from "./resource";
import { useJourney } from "./use-journey";
import { HerePill } from "./shell-parts";
import copy from "./copy.json";

const stateTone = { done: "success", now: "blue", next: "neutral" } as const;
type State = "done" | "now" | "next";
const fill = (text: string, values: Record<string, string | number>) =>
  text.replace(/\{(\w+)\}/g, (_, key) => String(values[key] ?? ""));

type JourneyProps = {
  navigate: (view: string, event?: string) => void;
  journey?: ReturnType<typeof useJourney>;
  onChat?: (topic?: string) => void;
};
/** Uses the shell's journey data when given, so the page does not refetch. */
export function Journey({ navigate, journey, onChat }: JourneyProps) {
  return journey ? <JourneyBody navigate={navigate} onChat={onChat} resource={journey} /> : <OwnJourney navigate={navigate} onChat={onChat} />;
}
function OwnJourney({ navigate, onChat }: JourneyProps) {
  return <JourneyBody navigate={navigate} onChat={onChat} resource={useJourney()} />;
}

function JourneyBody({ navigate, onChat, resource }: {
  navigate: JourneyProps["navigate"];
  onChat?: JourneyProps["onChat"];
  resource: ReturnType<typeof useJourney>;
}) {
  const progress = resource.progress;
  const [picked, setPicked] = useState<number | null>(null);
  const trail = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const current = progress?.current ?? 0;
  const selected = picked ?? current;
  // Keep the current stage in view on a phone, where the trail scrolls sideways.
  useEffect(() => {
    const box = scroller.current;
    const here = trail.current?.querySelector<HTMLElement>('[aria-current="step"]');
    if (box && here) box.scrollLeft = here.offsetLeft - box.clientWidth / 2 + here.clientWidth / 2;
  }, [current, !!progress]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!resource.data || resource.error || !progress)
    return (
      <>
        <Heading title={copy.journeyTitle} description={copy.journeyIntro} />
        <LoadState error={resource.error} busy={resource.busy} retry={resource.refresh} skeleton="list" />
      </>
    );

  const total = copy.stages.length;
  const stages = copy.stages.map((stage, index) => ({
    ...stage,
    index,
    state: progress.state(index) as State,
    moment: "action" in stage ? resource.data?.picture.moments[stage.action!] : undefined,
  }));
  const here = stages[current];
  const pick = stages[selected];
  const action = (stage: (typeof stages)[number], primary: boolean) =>
    (stage.state !== "next" || stage.moment) && (
      <Button size="tap" variant={primary ? "primary" : "soft"} onClick={() => navigate(stage.view, stage.moment)}>
        {stage.moment ? <MessageCircle aria-hidden /> : null}
        {stage.moment ? copy.moment : copy.nav[stage.view as keyof typeof copy.nav]}
        {!stage.moment && <ArrowRight aria-hidden />}
      </Button>
    );
  const move = (event: React.KeyboardEvent, index: number) => {
    const next = event.key === "ArrowRight" ? index + 1 : event.key === "ArrowLeft" ? index - 1 : -1;
    if (next < 0 || next >= total) return;
    event.preventDefault();
    setPicked(next);
    trail.current?.querySelectorAll<HTMLElement>("button")[next]?.focus();
  };

  return (
    <>
      <Heading title={copy.journeyTitle} description={copy.journeyIntro} />

      {/* Where you are, said plainly, with PAI beside you. */}
      <section className="relative overflow-hidden rounded-[28px] border bg-card shadow-card">
        <div className="relative">
          <div className="p-6 sm:p-8">
            <div className="flex items-center gap-2.5">
              <HerePill>{copy.shell.stage.replace("{id}", here.id)}</HerePill>
              <h2 className="text-sm font-bold uppercase tracking-[0.12em] text-muted-foreground">{copy.journeyStates.now}</h2>
            </div>
            <p className="mt-1 text-balance text-3xl font-extrabold tracking-[-0.02em] sm:text-[2.75rem] sm:leading-[1.05]">{here.title}</p>
            <p className="mt-3 max-w-lg text-pretty leading-relaxed text-muted-foreground">
              {copy.stageDescriptions[here.id as keyof typeof copy.stageDescriptions]}
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              {action(here, true)}
              {onChat && (
                <Button size="tap" variant="soft" onClick={() => onChat(fill(copy.journey.askDraft, { title: here.title }))}>
                  {copy.journey.ask}
                </Button>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* The trail: every stage, grouped by phase. Tap one to read about it. */}
      <section className="mt-8" aria-labelledby="journey-trail">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="journey-trail" className="text-lg font-extrabold tracking-tight">{copy.journey.trailLabel}</h2>
          <p className="text-sm text-muted-foreground">{copy.journey.pick}</p>
        </div>
        <div ref={scroller} className="relative -mx-4 overflow-x-auto px-4 pb-2 sm:mx-0 sm:px-0">
          <div ref={trail} className="flex min-w-[720px] gap-2">
            {copy.journey.phases.map((phase) => {
              const from = stages.findIndex((s) => s.id === phase.from);
              const to = stages.findIndex((s) => s.id === phase.to);
              const items = stages.slice(from, to + 1);
              const phaseDone = items.every((s) => s.state === "done");
              const phaseNow = items.some((s) => s.state === "now");
              return (
                <div key={phase.label} style={{ flexGrow: items.length }} className="min-w-0 basis-0">
                  <p className={cn("mb-2 truncate px-1 text-xs font-bold uppercase tracking-[0.1em]",
                    phaseNow ? "text-foreground" : phaseDone ? "text-foreground/70" : "text-muted-foreground")}>{phase.label}</p>
                  <ol className={cn("flex gap-1.5 rounded-2xl p-1.5", phaseNow ? "bg-highlight/10 ring-1 ring-inset ring-highlight/30 dark:bg-highlight/[0.08] dark:ring-highlight/25" : "bg-muted")}>
                    {items.map((s) => {
                      const on = s.index === selected;
                      return (
                        <li key={s.id} aria-current={s.state === "now" ? "step" : undefined} className="min-w-0 flex-1">
                          <button onClick={() => setPicked(s.index)} onKeyDown={(e) => move(e, s.index)}
                            aria-pressed={on} aria-label={fill(copy.journey.selected, { id: s.id, title: s.title, state: copy.journeyStates[s.state] })}
                            className={cn("group relative flex h-20 w-full flex-col items-center justify-center gap-1.5 rounded-xl text-sm font-extrabold transition-all",
                              on ? "bg-card shadow-card ring-[1.5px] ring-foreground" : "hover:bg-card/70")}>
                            <span className={cn("flex size-8 items-center justify-center rounded-full transition-transform group-hover:scale-105",
                              s.state === "done" && "bg-foreground text-background",
                              s.state === "now" && "bg-highlight text-highlight-ink ring-[1.5px] ring-highlight-ink",
                              s.state === "next" && "border-[1.5px] border-dashed border-input bg-card text-muted-foreground")}>
                              {s.state === "done" ? <Check aria-hidden className="size-4" strokeWidth={3} /> : s.id}
                            </span>
                            <span className={cn("text-[11px] font-bold", s.state === "next" ? "text-muted-foreground" : "text-foreground")}>{s.id}</span>
                            {s.state === "now" && (
                              <span aria-hidden className="absolute right-2 top-2 size-2 rounded-full bg-foreground motion-safe:animate-pulse" />
                            )}
                          </button>
                        </li>
                      );
                    })}
                  </ol>
                </div>
              );
            })}
          </div>
        </div>

        <div aria-live="polite" className="mt-4">
          <AnimatePresence mode="wait" initial={false}>
            <motion.article key={pick.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.16 }}
              className="flex flex-wrap items-center gap-5 rounded-3xl border bg-card p-5 shadow-soft sm:p-6">
              <span aria-hidden className={cn("flex size-14 shrink-0 items-center justify-center rounded-2xl text-2xl font-extrabold",
                pick.state === "done" ? "bg-foreground text-background" : pick.state === "now" ? "bg-highlight text-highlight-ink" : "bg-muted text-muted-foreground")}>
                {pick.id}
              </span>
              <div className="min-w-0 flex-1 basis-64">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-lg font-extrabold tracking-tight">
                    <span className="sr-only">{copy.shell.stage.replace("{id}", pick.id)}: </span>{pick.title}
                  </h3>
                  <StatChip size="sm" tone={stateTone[pick.state]}>{copy.journeyStates[pick.state]}</StatChip>
                </div>
                <p className="mt-1 max-w-xl text-pretty text-sm leading-relaxed text-muted-foreground">
                  {copy.stageDescriptions[pick.id as keyof typeof copy.stageDescriptions]}
                </p>
              </div>
              <div className="flex shrink-0 flex-wrap gap-2">{action(pick, pick.state === "now")}</div>
            </motion.article>
          </AnimatePresence>
        </div>
      </section>
    </>
  );
}
