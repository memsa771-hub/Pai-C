"use client";
import { useCallback } from "react";
import { workspaceApi } from "@/lib/api";
import type { LivingPicture } from "@/lib/counselor-workspace";
import type { Possibility } from "@/lib/possibilities";
import type { RoadmapPage } from "@/lib/roadmap";
import type { Roadmap } from "@/lib/roadmaps";
import { useResource } from "./resource";
import copy from "./copy.json";

export type Stage = (typeof copy.stages)[number];
export type JourneySignals = {
  picture: LivingPicture;
  possibilities: Possibility[];
  roadmaps: Roadmap[];
  roadmap: RoadmapPage | null;
};

/** Whether a stage's signal (named in copy.json) is satisfied. Signals only
 * read data the student already has; nothing here decides for them. */
export function signalMet(signal: string, data: JourneySignals): boolean {
  if (signal === "onboarded") return true;
  if (signal.startsWith("moment:")) return !!data.picture.moments?.[signal.slice(7)];
  if (signal === "mirror_confirmed") return data.picture.mirror_status === "confirmed";
  const live = data.possibilities.filter((p) => p.status !== "dismissed");
  if (signal === "paths_found") return live.length > 0;
  if (signal === "path_explored") return live.some((p) => p.status === "exploring" || p.status === "chosen");
  if (signal === "roadmap_prepared") return data.roadmaps.length > 0;
  // The Roadmap page: a route the student chose, then a first step ticked.
  // Cards alone reach nothing: they exist as soon as paths do.
  if (signal === "route_chosen") return !!data.roadmap?.chosen;
  if (signal === "route_step_done") return !!data.roadmap?.chosen?.steps_done.some(Boolean);
  return false;
}

/** The current stage is the one after the furthest stage reached; every
 * stage before it counts as done, so the path reads as progress. */
export function journeyProgress(data: JourneySignals) {
  let reached = -1;
  copy.stages.forEach((stage, index) => { if (signalMet(stage.signal, data)) reached = index; });
  // The server's own stage bounds how far the view may go: a planned move
  // (a moment) is not proof the student saw it, so without this the view
  // jumped from B to E after a few messages.
  const cap = (copy.stageCaps as Record<string, number | string>)[data.picture.stage || ""];
  const limit = typeof cap === "number" ? cap : copy.stages.length - 1;
  const current = Math.min(reached + 1, limit, copy.stages.length - 1);
  return {
    current,
    stage: copy.stages[current],
    state: (index: number) => (index < current ? "done" : index === current ? "now" : "next") as "done" | "now" | "next",
  };
}

/** Optional signals: a failed read leaves that stage unreached, never broken. */
const settle = <T,>(read: () => Promise<T>, fallback: T) => Promise.resolve().then(read).catch(() => fallback);
const loadJourney = async (): Promise<JourneySignals> => {
  const [picture, possibilities, roadmaps, roadmap] = await Promise.all([
    workspaceApi.getCounselorWorkspace(),
    settle(() => workspaceApi.getPossibilities(), [] as Possibility[]),
    settle(() => workspaceApi.getRoadmaps(), [] as Roadmap[]),
    settle(() => workspaceApi.getRoadmapPage(), null as RoadmapPage | null),
  ]);
  return { picture, possibilities, roadmaps, roadmap };
};

export function useJourney() {
  const load = useCallback(loadJourney, []);
  const resource = useResource(load);
  return { ...resource, progress: resource.data ? journeyProgress(resource.data) : null };
}
