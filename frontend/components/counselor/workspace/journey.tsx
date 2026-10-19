"use client";
import { ArrowRight, MessageCircle, Route } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatChip, Timeline } from "@/components/pai";
import { Heading, LoadState } from "./resource";
import { useJourney } from "./use-journey";
import copy from "./copy.json";

const stateTone = { done: "success", now: "blue", next: "neutral" } as const;

type JourneyProps = { navigate: (view: string, event?: string) => void; journey?: ReturnType<typeof useJourney> };
/** Uses the shell's journey data when given, so the page does not refetch. */
export function Journey({ navigate, journey }: JourneyProps) {
  return journey ? <JourneyBody navigate={navigate} resource={journey} /> : <OwnJourney navigate={navigate} />;
}
function OwnJourney({ navigate }: JourneyProps) {
  return <JourneyBody navigate={navigate} resource={useJourney()} />;
}
function JourneyBody({ navigate, resource }: { navigate: JourneyProps["navigate"]; resource: ReturnType<typeof useJourney> }) {
  const progress = resource.progress;
  return (
    <>
      <Heading title={copy.journeyTitle} description={copy.journeyIntro} icon={Route} tone="violet" />
      {!resource.data || resource.error || !progress ? (
        <LoadState error={resource.error} busy={resource.busy} retry={resource.refresh} skeleton="list" />
      ) : (
        <div className="mx-auto max-w-3xl">
          <Timeline
            label={copy.journeyTitle}
            items={copy.stages.map((stage, index) => {
              const state = progress.state(index);
              const moment = "action" in stage ? resource.data?.picture.moments[stage.action!] : undefined;
              return {
                id: stage.id,
                marker: stage.id,
                state,
                title: (
                  <h2 className="text-base">
                    <span className="sr-only">{copy.shell.stage.replace("{id}", stage.id)}: </span>
                    {stage.title}
                  </h2>
                ),
                meta: <StatChip size="sm" tone={stateTone[state]}>{copy.journeyStates[state]}</StatChip>,
                children: (
                  <div className="flex flex-wrap items-end justify-between gap-3">
                    <p className="max-w-lg text-sm text-muted-foreground">
                      {copy.stageDescriptions[stage.id as keyof typeof copy.stageDescriptions]}
                    </p>
                    {state !== "next" && (
                      <Button size="tap" variant={state === "now" ? "primary" : "soft"} onClick={() => navigate(stage.view, moment)}>
                        {moment ? <MessageCircle aria-hidden /> : null}
                        {moment ? copy.moment : copy.nav[stage.view as keyof typeof copy.nav]}
                        {!moment && <ArrowRight aria-hidden />}
                      </Button>
                    )}
                  </div>
                ),
              };
            })}
          />
        </div>
      )}
    </>
  );
}
