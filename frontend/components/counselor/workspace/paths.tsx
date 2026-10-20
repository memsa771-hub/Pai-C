"use client";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft, ArrowRight, Bookmark, BookOpen, Briefcase, Compass, DoorOpen, ExternalLink, FlaskConical, GraduationCap,
  HelpCircle, Info, Loader2, MapPin, MessageCircle, RefreshCw, ShieldCheck, Sparkles, Sun, Telescope, ThumbsUp,
  Wallet, Wrench, X, type LucideIcon,
} from "lucide-react";
import { workspaceApi } from "@/lib/api";
import type { Possibility } from "@/lib/possibilities";
import type { Program } from "@/lib/counselor-workspace";
import { Button } from "@/components/ui/button";
import { EmptyState, SectionCard, Skeletons, StatChip, toneClass, toneFor, tonesByOrder, type Tone } from "@/components/pai";
import { PathCardView } from "@/components/counselor/path-card";
import { cn } from "@/lib/utils";
import { Heading, LoadState, useResource, human, evidenceLabel, shortDate } from "./resource";
import { DEFAULT_LOCALE } from "@/lib/i18n/locales";
import copy from "./copy.json";

const list = () => workspaceApi.getPossibilities();
const statusTone = { suggested: "blue", exploring: "blue", saved: "success", dismissed: "neutral", chosen: "success" } as const;
const SECTION_ICONS: Record<string, LucideIcon> = {
  book: BookOpen, graduation: GraduationCap, sun: Sun, wrench: Wrench, thumbs: ThumbsUp, flask: FlaskConical,
  door: DoorOpen, help: HelpCircle, briefcase: Briefcase, telescope: Telescope,
};
const fill = (template: string, values: Record<string, string | number>) =>
  Object.entries(values).reduce((out, [key, value]) => out.replaceAll(`{${key}}`, String(value)), template);

/** "Needs checking" is a calm information state, never an error. */
function NeedsChecking({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-start gap-2.5 rounded-2xl bg-info-soft px-4 py-3 text-sm text-info-ink">
      <Info aria-hidden className="mt-0.5 size-4 shrink-0" />
      <p><span className="font-semibold">{copy.needsChecking}{!compact && "."}</span>{!compact && <> {copy.needsCheckingBody}</>}</p>
    </div>
  );
}

function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <Button size="tap" variant="ghost" className="-ms-3 mb-4" onClick={onClick}>
      <ArrowLeft aria-hidden />{copy.back}
    </Button>
  );
}

export function PathCard({
  path,
  onOpen,
  onChange,
  tone,
}: {
  path: Possibility;
  tone?: Tone;
  onOpen: () => void;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(false);
  async function act(action: "save" | "dismiss") {
    setBusy(true);
    try {
      await workspaceApi.changePossibility(path.id, action);
      onChange();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <PathCardView id={path.id} tone={tone} title={path.title} whyLabel={copy.why} why={path.why} quote={path.evidence[0]?.text}
      status={human(path.status)} statusTone={statusTone[path.status]} error={error ? copy.error : null}
      actions={<>
        <Button size="tap" onClick={onOpen}><Compass aria-hidden />{copy.explore}</Button>
        {["suggested", "dismissed"].includes(path.status) && (
          <Button size="tap" variant="soft" disabled={busy} onClick={() => act("save")}><Bookmark aria-hidden />{copy.save}</Button>
        )}
        {!["dismissed", "chosen"].includes(path.status) && (
          <Button size="tap" variant="ghost" disabled={busy} onClick={() => act("dismiss")}><X aria-hidden />{copy.notForMe}</Button>
        )}
      </>} />
  );
}

export function Paths({ onOpen, onChat }: { onOpen: (id: string) => void; onChat?: (topic?: string) => void }) {
  const resource = useResource(list);
  const live = resource.data?.filter((p) => p.status !== "dismissed") || [];
  const dismissed = resource.data?.filter((p) => p.status === "dismissed") || [];
  const tones = tonesByOrder((resource.data || []).map((p) => p.id));
  return (
    <>
      <Heading title={copy.pathsTitle} description={copy.pathsIntro} icon={Compass} tone="teal" />
      {!resource.data || resource.error ? (
        <LoadState error={resource.error} busy={resource.busy} retry={resource.refresh} />
      ) : !resource.data.length ? (
        <EmptyState icon={Compass} tone="teal" title={copy.pathsEmptyTitle} description={copy.pathsEmptyBody}
          action={onChat && <Button size="tap" onClick={() => onChat()}><MessageCircle aria-hidden />{copy.openChat}</Button>} />
      ) : (
        <>
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            {live.map((path) => (
              <PathCard path={path} tone={tones[path.id]} key={path.id} onOpen={() => onOpen(path.id)} onChange={resource.refresh} />
            ))}
          </div>
          {dismissed.length > 0 && (
            <details className="group mt-8">
              <summary className="inline-flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-xl px-1 font-semibold text-muted-foreground">
                <ArrowRight aria-hidden className="size-4 transition-transform group-open:rotate-90" />
                {fill(copy.dismissedTitle, { count: dismissed.length })}
              </summary>
              <div className="mt-4 grid gap-5 opacity-80 md:grid-cols-2 xl:grid-cols-3">
                {dismissed.map((path) => (
                  <PathCard path={path} tone={tones[path.id]} key={path.id} onOpen={() => onOpen(path.id)} onChange={resource.refresh} />
                ))}
              </div>
            </details>
          )}
        </>
      )}
    </>
  );
}

/** A section's content in readable form: sentences, bullet lists, and
 * observations paired with the student's own words. */
function SectionBody({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    return (
      <ul className="space-y-2">
        {value.map((item, i) => {
          const row = item && typeof item === "object" ? item as Record<string, unknown> : null;
          return (
            <li key={i} className="flex gap-2.5 text-sm leading-relaxed">
              <span aria-hidden className="mt-2 size-1.5 shrink-0 rounded-full bg-current opacity-50" />
              <span className="min-w-0">
                {row?.observation ? <>{human(row.observation)}{row.evidence ? <span className="mt-1 block text-muted-foreground">“{human(row.evidence)}”</span> : null}</> : human(item)}
              </span>
            </li>
          );
        })}
      </ul>
    );
  }
  return <p className="whitespace-pre-line text-sm leading-relaxed text-muted-foreground">{human(value)}</p>;
}

export function PathPage({
  id,
  onBack,
  onPlaces,
  onChat,
}: {
  id: string;
  onBack: () => void;
  onPlaces: () => void;
  onChat: (text: string) => void;
}) {
  const load = useCallback(() => workspaceApi.getPath(id), [id]);
  const resource = useResource(load);
  const order = useResource(list);
  const [activityScheduled, setActivityScheduled] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(false);
  useEffect(() => {
    if (
      !resource.data ||
      !["pending", "queued", "executing", "planning", "verifying", "running"].includes(
        resource.data.status,
      )
    )
      return;
    const timer = setInterval(resource.refresh, 5000);
    return () => clearInterval(timer);
  }, [resource.data?.status, resource.refresh]);
  async function start() {
    setBusy(true);
    setError(false);
    try {
      await workspaceApi.changePossibility(id, "explore");
      await resource.refresh();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  if (!resource.data || resource.error)
    return (
      <>
        <BackButton onClick={onBack} />
        <LoadState busy={resource.busy} error={resource.error} retry={resource.refresh} />
      </>
    );
  const result = resource.data;
  const tone = (order.data && tonesByOrder(order.data.map((p) => p.id))[id]) || toneFor(result.possibility.id);
  const waiting = !["not_started", "failed"].includes(result.status);
  return (
    <>
      <BackButton onClick={onBack} />
      <header className={cn("relative mb-6 overflow-hidden rounded-3xl p-5 sm:p-7", toneClass[tone].soft)}>
        <div className="flex flex-wrap items-start gap-4">
          <span aria-hidden className={cn("flex size-14 shrink-0 items-center justify-center rounded-2xl", toneClass[tone].solid)}>
            <Compass className="size-7" />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="text-balance text-2xl font-bold tracking-tight sm:text-3xl">{result.possibility.title}</h1>
            <p className={"mt-3 text-xs font-semibold text-muted-foreground"}>{copy.why}</p>
            <p className="mt-1 max-w-2xl text-pretty leading-relaxed">{result.possibility.why}</p>
          </div>
        </div>
        <p className="mt-4 text-sm text-muted-foreground">{copy.pathIntro}</p>
      </header>
      {result.status === "stale" && (
        <section className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-warning-soft px-5 py-4 text-warning-ink">
          <p className="flex items-start gap-2 text-sm font-medium"><Info aria-hidden className="mt-0.5 size-4 shrink-0" />{copy.stalePath}</p>
          <Button size="tap" variant="outline" disabled={busy} onClick={start}><RefreshCw aria-hidden />{copy.refresh}</Button>
          {error && <p role="alert" className="w-full text-sm font-medium text-danger-ink">{copy.error}</p>}
        </section>
      )}
      {!result.path ? (
        <section className="rounded-3xl border bg-card p-6 shadow-card sm:p-8">
          {waiting ? (
            <>
              <p role="status" className="flex items-center gap-2.5 font-medium"><Loader2 aria-hidden className="size-5 animate-spin text-brand" />{copy.pathLoading}</p>
              <div className="mt-6"><Skeletons variant="list" count={3} label={copy.pathLoading} /></div>
            </>
          ) : (
            <EmptyState icon={Compass} tone={tone} title={result.possibility.title} description={copy.pathEmpty}
              action={<Button size="tap" disabled={busy} onClick={start}><Compass aria-hidden />{copy.explore}</Button>} />
          )}
          {error && <p role="alert" className="mt-3 text-sm font-medium text-danger-ink">{copy.error}</p>}
        </section>
      ) : (
        <>
          <div className="grid gap-5 md:grid-cols-2">
            {Object.entries(copy.pathSections).map(([key, label]) => {
              const value = result.path?.[key];
              const facts = result.facts.filter((f) => f.field === key);
              const Icon = SECTION_ICONS[copy.pathSectionIcons[key as keyof typeof copy.pathSectionIcons]] || BookOpen;
              const sectionTone = key === "fit_for" ? "teal" : key === "fit_against" ? "amber" : tone;
              return (
                <SectionCard key={key} title={label} icon={Icon} tone={sectionTone}>
                  {human(value).trim() ? (
                    <SectionBody value={value} />
                  ) : facts.length ? (
                    <div className="space-y-3">
                      {facts.map((fact, i) => (
                        <div key={i}>
                          <p className="text-sm">{human(fact.value)}</p>
                          <Source fact={fact} />
                        </div>
                      ))}
                    </div>
                  ) : (
                    <NeedsChecking compact />
                  )}
                </SectionCard>
              );
            })}
          </div>
          <section className="my-6 rounded-3xl border border-primary/15 bg-brand-soft/60 p-6 sm:p-7">
            <h2 className="flex items-center gap-2.5 text-lg font-bold">
              <span aria-hidden className="flex size-10 items-center justify-center rounded-xl bg-card text-tone-violet-ink shadow-soft"><Sparkles className="size-5" /></span>
              {copy.tryIt}
            </h2>
            <p className="my-4 max-w-2xl text-pretty leading-relaxed">{human(result.path.try_it)}</p>
            <div className="flex flex-wrap gap-2">
              <Button size="tap" disabled={busy || activityScheduled} onClick={async () => {
                setBusy(true); setError(false);
                try { await workspaceApi.acceptPathActivity(id); setActivityScheduled(true); } catch { setError(true); } finally { setBusy(false); }
              }}>{activityScheduled ? copy.activityScheduled : copy.acceptActivity}</Button>
              <Button size="tap" variant="outline" onClick={() => onChat(copy.reflection)}>
                <MessageCircle aria-hidden />{copy.reflection}
              </Button>
            </div>
            {error && <p role="alert" className="mt-3 text-sm font-medium text-danger-ink">{copy.error}</p>}
          </section>
          <section className="flex flex-wrap items-center justify-between gap-4 rounded-3xl border bg-card p-6 shadow-card sm:p-7">
            <div className="flex min-w-0 max-w-xl items-start gap-3">
              <span aria-hidden className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-tone-blue-soft text-tone-blue-ink"><MapPin className="size-5" /></span>
              <div>
                <p className="text-xs font-semibold text-primary">{copy.placesCta}</p>
                <h2 className="text-lg font-bold">{copy.places}</h2>
                <p className="mt-1 text-sm text-muted-foreground">{copy.placesIntro}</p>
              </div>
            </div>
            <Button size="tap" onClick={onPlaces}>{copy.placesOpen}<ArrowRight aria-hidden /></Button>
          </section>
        </>
      )}
    </>
  );
}

function Source({ fact }: { fact: Record<string, unknown> }) {
  const url = String(fact.source_url || "");
  let host = "";
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "https:") host = parsed.hostname;
  } catch {}
  const verified = fact.status === "verified";
  return (
    <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      {host && (
        <a href={url} target="_blank" rel="noopener noreferrer"
          className="inline-flex min-h-11 items-center gap-1 font-semibold text-brand-ink underline-offset-4 hover:underline">
          <ExternalLink aria-hidden className="size-3.5" />{host}
        </a>
      )}
      {fact.checked_at ? <span>{copy.sourceDate}: {shortDate(String(fact.checked_at).slice(0, 10))}</span> : null}
      <StatChip size="sm" tone={verified ? "success" : "neutral"}>{verified ? copy.verified : copy.unconfirmed}</StatChip>
    </p>
  );
}

const ELIGIBILITY_TONE: Record<string, "success" | "blue" | "warning" | "neutral"> = {
  safe: "success", eligible: "success", realistic: "blue", stretch: "warning", not_yet: "neutral",
};
function EligibilityPill({ label }: { label: string }) {
  const known = label in copy.eligibility && label !== "unknown";
  if (!known) return <StatChip size="sm" tone="blue" icon={Info} variant="outline">{copy.eligibility.unknown}</StatChip>;
  return <StatChip tone={ELIGIBILITY_TONE[label] || "neutral"}>{copy.eligibility[label as keyof typeof copy.eligibility]}</StatChip>;
}

function ProgramCard({ program }: { program: Program }) {
  const tone = toneFor(program.opportunity_id);
  return (
    <article className="flex min-w-0 flex-col rounded-3xl border bg-card p-5 shadow-card sm:p-6">
      <div className="flex items-start gap-3">
        <span aria-hidden className={cn("flex size-11 shrink-0 items-center justify-center rounded-2xl", toneClass[tone].soft, toneClass[tone].ink)}>
          <GraduationCap className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="break-words text-lg font-bold leading-snug">{program.title}</h2>
          <Source fact={program as unknown as Record<string, unknown>} />
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{copy.eligibilityTitle}</span>
        <EligibilityPill label={program.eligibility.label} />
      </div>
      {program.fees && Object.keys(program.fees).length > 0 && (
        <section className="mt-4 rounded-2xl bg-muted/60 px-4 py-3 text-sm">
          <h3 className="flex items-center gap-1.5 font-semibold"><Wallet aria-hidden className="size-4" />{copy.fees}</h3>
          {/* Each fee is a sourced fact: its label, its value, and where it came from. */}
          <ul className="mt-2 space-y-2">
            {Object.entries(program.fees).map(([key, fee]) => {
              const fact = fee && typeof fee === "object" ? fee as Record<string, unknown> : { value: fee };
              return (
                <li key={key}>
                  <p><span className="text-muted-foreground">{evidenceLabel(key)}: </span><span className="font-medium">{human(fact.value ?? fact.quote)}</span></p>
                  {fact.source_url ? <Source fact={fact} /> : null}
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {program.rules.length > 0 && (
        <section className="mt-4">
          <h3 className="text-sm font-semibold">{copy.rulesTitle}</h3>
          <ul className="mt-2 space-y-3">
            {program.rules.map((rule, i) => (
              <li key={i} className="border-t pt-3 text-sm first:border-t-0 first:pt-0">
                <p>{human(rule.value)}</p>
                <Source fact={rule} />
              </li>
            ))}
          </ul>
        </section>
      )}
      {program.eligibility.route.length > 0 && (
        <section className="mt-4 rounded-2xl bg-tone-teal-soft px-4 py-3">
          <h3 className="text-sm font-semibold text-tone-teal-ink">{copy.route}</h3>
          <ul className="mt-2 space-y-2">
            {program.eligibility.route.map((route, i) => (
              <li key={i} className="text-sm">
                <p>{human(route.action)}</p>
                <Source fact={route} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}

export function ProgramPage({
  id,
  onBack,
  onCompare,
}: {
  id: string;
  onBack: () => void;
  onCompare?: () => void;
}) {
  const load = useCallback(() => workspaceApi.getPrograms(id), [id]);
  const resource = useResource(load);
  const [consent, setConsent] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(false);
  useEffect(() => {
    if (
      !resource.data ||
      ["not_started", "completed", "failed", "stale"].includes(resource.data.status)
    )
      return;
    const timer = setInterval(resource.refresh, 5000);
    return () => clearInterval(timer);
  }, [resource.data?.status, resource.refresh]);
  async function prepare() {
    setBusy(true);
    setError(false);
    try {
      await workspaceApi.preparePathRoadmap(id);
      onCompare?.();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  async function search() {
    setBusy(true);
    setError(false);
    try {
      await workspaceApi.searchPrograms(id);
      await resource.refresh();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <BackButton onClick={onBack} />
      <Heading title={copy.places} description={copy.placesIntro} icon={MapPin} tone="blue" />
      {!resource.data || resource.error ? (
        <LoadState busy={resource.busy} error={resource.error} retry={resource.refresh} />
      ) : (
        <>
          {resource.data.status === "not_started" ||
          ["failed", "stale"].includes(resource.data.status) ? (
            <section className="mx-auto max-w-2xl rounded-3xl border bg-card p-6 shadow-card sm:p-8">
              <span aria-hidden className="flex size-12 items-center justify-center rounded-2xl bg-success-soft text-success-ink"><ShieldCheck className="size-6" /></span>
              <h2 className="mt-4 text-xl font-bold">{copy.consentTitle}</h2>
              <p className="mt-2 text-pretty text-muted-foreground">{copy.consentBody}</p>
              {resource.data.status === "stale" && <div className="mt-4"><NeedsChecking /></div>}
              <label className={cn("mt-5 flex min-h-14 cursor-pointer items-center gap-3 rounded-2xl border-2 px-4 py-3 font-semibold transition-colors",
                consent ? "border-foreground bg-secondary text-foreground ring-1 ring-foreground" : "border-border hover:border-foreground/30")}>
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                  className="size-5 shrink-0 accent-[var(--brand)]"
                />
                {copy.placesConsent}
              </label>
              <Button size="tap" disabled={!consent || busy} onClick={search} className="mt-5 h-12 w-full sm:w-auto">
                <MapPin aria-hidden />{copy.search}
              </Button>
              {error && (
                <p role="alert" className="mt-3 text-sm font-medium text-danger-ink">
                  {copy.error}
                </p>
              )}
            </section>
          ) : resource.data.status !== "completed" ? (
            <section className="rounded-3xl border bg-card p-6 shadow-card">
              <p role="status" className="flex items-center gap-2.5 font-medium"><Loader2 aria-hidden className="size-5 animate-spin text-brand" />{copy.programsLoading}</p>
              <div className="mt-6"><Skeletons count={2} label={copy.programsLoading} /></div>
            </section>
          ) : !resource.data.programs.length ? (
            <EmptyState icon={Info} tone="sky" title={copy.needsChecking} description={copy.noPrograms} />
          ) : (
            <>
              <p className="mb-4 text-sm font-medium text-muted-foreground">{fill(
                new Intl.PluralRules(DEFAULT_LOCALE).select(resource.data.programs.length) === "one" ? copy.programsFound.one : copy.programsFound.other,
                { count: resource.data.programs.length })}</p>
              <div className="grid gap-5 md:grid-cols-2">
                {resource.data.programs.map((program) => <ProgramCard key={program.opportunity_id} program={program} />)}
              </div>
            </>
          )}
          {resource.data.status === "completed" && (
            <section className="mt-6 flex flex-wrap items-center justify-between gap-4 rounded-3xl border bg-card p-6 shadow-soft sm:p-7">
              <div className="max-w-xl">
                <h2 className="text-lg font-extrabold tracking-tight">{copy.nextStepTitle}</h2>
                <p className="mt-1 text-sm text-muted-foreground">{copy.decisionPending}</p>
              </div>
              <Button size="tap" disabled={busy} onClick={prepare}>
                {copy.prepareRoadmap}<ArrowRight aria-hidden />
              </Button>
              {error && <p role="alert" className="w-full text-sm font-medium text-danger-ink">{copy.error}</p>}
            </section>
          )}
        </>
      )}
    </>
  );
}
