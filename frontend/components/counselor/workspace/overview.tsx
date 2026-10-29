"use client";
/** The student's overview, in the PAI dashboard design: signal cards, their
 * strongest paths, what PAI understands, and one recommended next step at a
 * time. Every number comes from the student's own data; nothing is a score
 * of the student and nothing here decides for them. */
import { useCallback, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, ChevronLeft, ChevronRight } from "lucide-react";
import { workspaceApi } from "@/lib/api";
import { vaultEntries, type VaultEntry } from "@/lib/vault";
import type { LivingPicture } from "@/lib/counselor-workspace";
import { cn } from "@/lib/utils";
import { LoadState, useResource } from "./resource";
import type { useJourney } from "./use-journey";
import copy from "./copy.json";
import layout from "./profile-layout.json";
import { missingBasics } from "./profile-basics";
import { FitDots, initials } from "@/components/counselor/path-card";

const text = copy.overview;
const fill = (s: string, v: Record<string, string | number>) => s.replace(/\{(\w+)\}/g, (_, k) => String(v[k] ?? ""));

function Metric({ label, value, sub, tone = "white" }: { label: string; value: React.ReactNode; sub: string; tone?: "lime" | "white" | "peach" }) {
  return (
    <div className={cn("flex min-h-[110px] flex-col rounded-[18px] px-4 py-3.5 sm:px-5 [@media(max-height:820px)]:min-h-[96px] [@media(max-height:820px)]:py-2.5",
      tone === "lime" ? "bg-lime text-signal-ink" : tone === "peach" ? "bg-peach text-signal-ink" : "bg-card shadow-card ring-1 ring-border/70")}>
      <p className={cn("text-xs font-medium", tone === "white" ? "text-muted-foreground" : "text-signal-ink/70")}>{label}</p>
      <p className="mt-0.5 text-[32px] font-bold leading-[44px] tabular-nums">{value}</p>
      <p className={cn("text-xs font-medium", tone === "white" ? "text-primary" : "text-[#1249c4]")}>{sub}</p>
    </div>
  );
}

/** The Mirror in brief: who PAI is drawing, the first lines it wrote, how
 * much is still unknown, and the way to the Mirror page. */
function MirrorSummary({ picture, onOpen }: { picture: LivingPicture["picture"]; onOpen: () => void }) {
  const unknowns = picture?.unknowns.length ?? 0;
  const sentences = picture?.ready ? picture.text?.sentences.slice(0, 2) ?? [] : [];
  const who = [picture?.header.name, picture?.header.education_line?.text].filter(Boolean);
  return (
    <section aria-labelledby="ov-mirror" className="flex min-w-0 flex-col">
      <h2 id="ov-mirror" className="font-display text-lg leading-tight">{text.mirrorTitle}</h2>
      <p className="mt-0.5 text-[11px] text-muted-foreground">{text.mirrorNote}</p>
      {who.length > 0 && (
        <p className="mt-3 flex min-w-0 flex-wrap items-baseline gap-x-2 text-sm">
          {picture?.header.name && <span className="font-semibold">{picture.header.name}</span>}
          {picture?.header.education_line && <span className="text-muted-foreground">{picture.header.education_line.text}</span>}
        </p>
      )}
      {sentences.length ? (
        <p className="mt-2 line-clamp-3 text-pretty text-sm leading-relaxed">{sentences.join(" ")}</p>
      ) : <p className="mt-2 text-sm text-muted-foreground">{text.mirrorNotReady}</p>}
      <p className="mt-2 text-xs font-semibold text-primary">
        {unknowns ? fill(unknowns === 1 ? text.mirrorUnknowns.one : text.mirrorUnknowns.other, { count: unknowns }) : text.mirrorAllKnown}
      </p>
      <button onClick={onOpen} className="mt-auto inline-flex min-h-8 items-center gap-1 pt-2 text-xs font-semibold text-primary hover:underline">
        {text.mirrorOpen}<ArrowRight aria-hidden className="size-3.5" />
      </button>
    </section>
  );
}

type Rec = { key: string; title: string; body: string; action: string; run: () => void };

export function Overview({ journey, navigate, openPath, onChat }: {
  journey: ReturnType<typeof useJourney>;
  navigate: (view: string, event?: string) => void;
  openPath: (id: string) => void;
  onChat: (topic?: string) => void;
}) {
  // The Vault metric counts what the Vault holds; a failed read shows a dash, never blocks the overview.
  const loadEntries = useCallback(() => workspaceApi.getVault().then(vaultEntries).catch(() => null as VaultEntry[] | null), []);
  const vault = useResource(loadEntries);
  const [rec, setRec] = useState(0);

  if (!journey.data || journey.error || !journey.progress)
    return <LoadState error={journey.error} busy={journey.busy} retry={journey.refresh} skeleton="cards" />;

  const { picture, possibilities } = journey.data;
  const progress = journey.progress;
  const total = copy.stages.length;
  const live = possibilities.filter((p) => p.status !== "dismissed");
  const facts = (vault.data || []).filter((e) => !layout.hiddenKeys.includes(e.type));
  const missing = missingBasics(facts);
  const stage = progress.stage;
  const moment = "action" in stage ? picture.moments?.[stage.action!] : undefined;

  const recs: Rec[] = [
    {
      key: "stage",
      title: fill(text.recStage, { id: stage.id, title: stage.title }),
      body: copy.stageDescriptions[stage.id as keyof typeof copy.stageDescriptions],
      action: moment ? copy.moment : fill(text.nextOpen, { view: copy.nav[stage.view as keyof typeof copy.nav] }),
      run: () => navigate(stage.view, moment),
    },
    ...(missing.length && vault.data ? [{
      key: "missing",
      title: fill(text.recMissingTitle, { count: missing.length }),
      body: `${text.recMissingBody} ${missing.slice(0, 3).map((m) => m.label).join(", ")}.`,
      action: text.recMissingAction,
      run: () => onChat(fill(text.recMissingDraft, { label: missing[0].label.toLowerCase() })),
    }] : []),
    ...(live[0] ? [{
      key: "path",
      title: fill(text.recPathTitle, { title: live[0].title }),
      body: text.recPathBody,
      action: text.recPathAction,
      run: () => openPath(live[0].id),
    }] : []),
  ];
  const current = recs[Math.min(rec, recs.length - 1)];
  const others = recs.filter((r) => r.key !== current.key);

  return (
    <div className="flex flex-col gap-5 fit:h-full fit:min-h-0 [@media(max-height:820px)]:gap-4">
      <header className="shrink-0">
        <h1 className="text-balance font-display text-[1.85rem] leading-[1.15] sm:text-[2.1rem]">{text.title}</h1>
        <p className="mt-1 text-sm text-muted-foreground sm:text-[15px] [@media(max-height:760px)]:hidden">{text.intro}</p>
      </header>

      <section aria-label={text.title} className="grid shrink-0 grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <Metric tone="lime" label={text.metrics.paths} value={live.length}
          sub={live.length ? fill(text.metrics.pathsSub, { saved: live.filter((p) => p.status === "saved").length, exploring: live.filter((p) => p.status === "exploring" || p.status === "chosen").length }) : text.metrics.pathsNone} />
        <Metric label={text.metrics.journey} value={<>{progress.current}<span className="text-lg font-semibold text-muted-foreground"> / {total}</span></>}
          sub={fill(text.metrics.journeySub, { title: stage.title })} />
        <Metric label={text.metrics.vault} value={vault.data ? facts.length : "–"}
          sub={fill(text.metrics.vaultSub, { confirmed: facts.filter((e) => e.level === "confirmed").length })} />
        <Metric tone="peach" label={text.metrics.attention} value={vault.data ? missing.length : "–"}
          sub={missing.length ? text.metrics.attentionSub : text.metrics.attentionNone} />
      </section>

      <div className="grid items-start gap-5 fit:min-h-0 fit:flex-1 fit:items-stretch lg:grid-cols-[minmax(0,1fr)_minmax(0,19rem)] xl:grid-cols-[minmax(0,1fr)_minmax(0,25rem)] [@media(max-height:820px)]:gap-4">
        <div className="flex min-w-0 flex-col gap-5 fit:min-h-0 [@media(max-height:820px)]:gap-4">
          <section aria-labelledby="ov-paths" className="rounded-[22px] bg-card p-5 shadow-card ring-1 ring-border/70 fit:flex fit:min-h-0 fit:flex-col">
            <div className="flex items-start justify-between gap-3">
              <h2 id="ov-paths" className="font-display text-[22px] leading-tight">{text.pathsTitle}</h2>
              {live.length > 0 && (
                <button onClick={() => navigate("paths")} className="inline-flex min-h-8 shrink-0 items-center gap-1 text-xs font-semibold text-primary hover:underline">
                  {fill(text.viewAll, { count: live.length })}<ArrowRight aria-hidden className="size-3.5" />
                </button>
              )}
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground">{text.pathsNote}</p>
            {live.length ? (
              <ul className="mt-3 space-y-2.5 fit:-me-2 fit:min-h-0 fit:overflow-y-auto fit:pe-2">
                {live.slice(0, 3).map((path) => (
                  <li key={path.id}>
                    <button onClick={() => openPath(path.id)}
                      className="group flex w-full items-center gap-3.5 rounded-xl bg-background px-3 py-2.5 text-left ring-1 ring-transparent transition hover:ring-primary/30">
                      <span aria-hidden className="flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-soft text-[13px] font-semibold text-primary">{initials(path.title)}</span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-2">
                          <span className="truncate text-[13px] font-semibold">{path.title}</span>
                          <FitDots items={path.fit || []} summary={text.fitDots} />
                        </span>
                        <span className="block truncate text-[11px] text-primary">{path.why}</span>
                      </span>
                      <span className="hidden shrink-0 flex-col items-end sm:flex">
                        <span className="text-base font-semibold text-primary">{text.status[path.status]}</span>
                        <span className="text-[10px] text-muted-foreground">{text.statusLabel}</span>
                      </span>
                      <ArrowRight aria-hidden className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                    </button>
                  </li>
                ))}
              </ul>
            ) : <p className="mt-4 rounded-xl bg-background px-4 py-5 text-sm text-muted-foreground">{text.pathsEmpty}</p>}
          </section>

          <section className="grid content-start gap-6 rounded-[22px] bg-card p-5 shadow-card ring-1 ring-border/70 fit:min-h-44 fit:flex-1 fit:overflow-y-auto md:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            <MirrorSummary picture={picture.picture} onOpen={() => navigate("mirror")} />
            <div className="flex flex-col rounded-[14px] bg-brand-soft p-3.5 lg:max-xl:hidden">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-primary">{text.nextLabel}</p>
              <p className="mt-1 text-[15px] font-semibold leading-snug">{stage.title}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{copy.stageDescriptions[stage.id as keyof typeof copy.stageDescriptions]}</p>
              <button onClick={() => navigate(stage.view, moment)} className="mt-auto inline-flex items-center gap-1 pt-2 text-left text-xs font-semibold text-primary hover:underline">
                {moment ? copy.moment : fill(text.nextOpen, { view: copy.nav[stage.view as keyof typeof copy.nav] })}<ArrowRight aria-hidden className="size-3.5" />
              </button>
            </div>
          </section>
        </div>

        <section aria-labelledby="ov-rec" aria-roledescription="carousel" className="flex flex-col rounded-[22px] bg-powder p-6 text-signal-ink fit:min-h-0 fit:overflow-y-auto [@media(max-height:820px)]:p-5">
          <div className="flex items-center justify-between">
            <span id="ov-rec" className="rounded-full bg-white px-3.5 py-2 text-[10px] font-semibold uppercase tracking-wide text-[#155eef]">{text.recommends}</span>
            <div className="flex items-center gap-1">
              <button onClick={() => setRec((rec - 1 + recs.length) % recs.length)} aria-label={text.recPrev} disabled={recs.length < 2}
                className="flex size-8 items-center justify-center rounded-full hover:bg-white/50 disabled:opacity-30"><ChevronLeft aria-hidden className="size-4" /></button>
              <span className="text-xs font-semibold tabular-nums">{String(Math.min(rec, recs.length - 1) + 1).padStart(2, "0")} / {String(recs.length).padStart(2, "0")}</span>
              <button onClick={() => setRec((rec + 1) % recs.length)} aria-label={text.recNext} disabled={recs.length < 2}
                className="flex size-8 items-center justify-center rounded-full hover:bg-white/50 disabled:opacity-30"><ChevronRight aria-hidden className="size-4" /></button>
            </div>
          </div>
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={current.key} aria-live="polite" className="flex flex-1 flex-col"
              initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 }} transition={{ duration: 0.18 }}>
              <h3 className="mt-4 text-balance font-display text-[28px] leading-[34px]">{current.title}</h3>
              <p className="mt-2 text-sm font-semibold">{current.body}</p>
              <div aria-hidden className="mt-5 rounded-2xl bg-white/85 p-4 [@media(max-height:760px)]:hidden">
                <div className="flex gap-1">
                  {copy.stages.map((s, i) => (
                    <span key={s.id} className={cn("flex h-7 flex-1 items-center justify-center rounded-md text-[10px] font-bold",
                      i < progress.current ? "bg-[#155eef] text-white" : i === progress.current ? "bg-white text-[#155eef] ring-2 ring-[#155eef]" : "bg-[#eaf2ff] text-[#155eef]/60")}>{s.id}</span>
                  ))}
                </div>
                <p className="mt-2 text-[11px] font-semibold text-[#155eef]">{fill(text.trackLabel, { done: progress.current, total })}</p>
              </div>
              <div className="mt-auto pt-6">
                <button onClick={current.run}
                  className="flex h-11 w-full items-center justify-center gap-2 rounded-full bg-[#155eef] text-sm font-semibold text-white shadow-[0_10px_24px_-12px_rgb(21_94_239/0.9)] transition hover:bg-[#0f4fd6]">
                  {current.action}<ArrowRight aria-hidden className="size-4" />
                </button>
                {others.length > 0 && <p className="mt-3 text-[11px]">{fill(text.recAlso, { items: others.map((o) => o.title.replace(/\.$/, "")).join(" · ") })}</p>}
              </div>
            </motion.div>
          </AnimatePresence>
        </section>
      </div>

    </div>
  );
}
