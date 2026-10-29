"use client";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft, ArrowRight, Bookmark, BookOpen, Briefcase, Compass, DoorOpen, ExternalLink, FlaskConical, GraduationCap,
  HelpCircle, Info, Loader2, MapPin, MessageCircle, Plus, RefreshCw, ShieldCheck, Sparkles, Sun, Telescope, ThumbsUp,
  Wallet, Wrench, X, type LucideIcon,
} from "lucide-react";
import { workspaceApi } from "@/lib/api";
import type { Possibility } from "@/lib/possibilities";
import type { Program } from "@/lib/counselor-workspace";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/responsive-dialog";
import { EmptyState, Skeletons, StatChip, toneClass, toneFor, tonesByOrder, type Tone } from "@/components/pai";
import { FieldNotes, FitDots, FitList, WhyEvidence, initials } from "@/components/counselor/path-card";
import { cn } from "@/lib/utils";
import { Heading, LoadState, useResource, human, evidenceLabel, shortDate } from "./resource";
import { DEFAULT_LOCALE } from "@/lib/i18n/locales";
import copy from "./copy.json";

const list = () => workspaceApi.getPossibilities();
// async, so a failing call becomes a load error rather than a throw.
const analysisStatus = async () => workspaceApi.getPathAnalysis();
/** The workspace card surface (as on the Overview). */
const CARD = "rounded-[22px] bg-card shadow-card ring-1 ring-border/70";
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

/** One path as a list row: the field, why it fits in a line, how it fits at a
 * glance, and the student's controls. The path page holds the detail. */
export function PathRow({
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
  const accent = toneClass[tone || toneFor(path.id)];
  return (
    <li className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:gap-5 sm:px-5">
      <div className="flex min-w-0 flex-1 items-center gap-3.5">
        <span aria-hidden className={cn("flex size-10 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold", accent.soft, accent.ink)}>
          {initials(path.title)}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <h2 className="font-semibold leading-snug">{path.title}</h2>
            <FitDots items={path.fit || []} summary={copy.overview.fitDots} />
            <FieldNotes field={path.study_field} />
          </div>
          <p className="mt-0.5 line-clamp-2 text-sm text-muted-foreground sm:line-clamp-1">{path.why}</p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5 ps-[3.375rem] sm:ps-0">
        <StatChip size="sm" tone={statusTone[path.status]}>
          {path.source === "student" && path.status === "saved" ? copy.ownPath : human(path.status)}
        </StatChip>
        <Button size="md" variant="soft" className="ms-1.5" onClick={onOpen}><Compass aria-hidden />{copy.explore}</Button>
        {["suggested", "dismissed"].includes(path.status) && (
          <Button size="icon" variant="ghost" disabled={busy} aria-label={copy.save} title={copy.save} onClick={() => act("save")}><Bookmark aria-hidden /></Button>
        )}
        {!["dismissed", "chosen"].includes(path.status) && (path.study_field?.outdated ? (
          <Button size="md" variant="ghost" disabled={busy} onClick={() => act("dismiss")}><X aria-hidden />{copy.pathRemove}</Button>
        ) : (
          <Button size="icon" variant="ghost" disabled={busy} aria-label={copy.notForMe} title={copy.notForMe} onClick={() => act("dismiss")}><X aria-hidden /></Button>
        ))}
      </div>
      {error && <p role="alert" className="text-sm font-medium text-danger-ink sm:basis-full">{copy.error}</p>}
    </li>
  );
}

/** The student's own direction, in their words. PAI then checks it against
 * them like any other path. */
function AddOwnPath({ open, onOpenChange, onAdded }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdded: () => void;
}) {
  const [title, setTitle] = useState(""),
    [why, setWhy] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(false);
  useEffect(() => {
    if (open) { setTitle(""); setWhy(""); setError(false); }
  }, [open]);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    setError(false);
    try {
      await workspaceApi.addOwnPath(title.trim(), why.trim());
      onOpenChange(false);
      onAdded();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={submit}>
          <DialogHeader className="space-y-2 px-7 pb-2 pt-7">
            <DialogTitle className="text-xl">{copy.addOwnTitle}</DialogTitle>
            <DialogDescription>{copy.addOwnIntro}</DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4 px-7 py-3">
            <div className="space-y-2">
              <Label htmlFor="own-path-title">{copy.addOwnName}</Label>
              <Input id="own-path-title" required maxLength={120} value={title} autoFocus
                placeholder={copy.addOwnPlaceholder} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="own-path-why">{copy.addOwnWhy}</Label>
              <Textarea id="own-path-why" maxLength={600} rows={3} value={why} onChange={(e) => setWhy(e.target.value)} />
            </div>
            {error && <p role="alert" className="text-sm font-medium text-danger-ink">{copy.error}</p>}
          </DialogBody>
          <DialogFooter className="px-7 pb-7 pt-2">
            <Button type="button" size="tap" variant="ghost" onClick={() => onOpenChange(false)}>{copy.addOwnCancel}</Button>
            <Button type="submit" size="tap" disabled={busy || !title.trim()}><Plus aria-hidden />{copy.addOwnSave}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const LIST = cn(CARD, "divide-y divide-border/70 overflow-hidden");

/** How often the page looks again while PAI works out the paths. */
const FINDING_EVERY_MS = 5000;

export function Paths({ onOpen, onChat }: { onOpen: (id: string) => void; onChat?: (topic?: string) => void }) {
  const resource = useResource(list);
  const analysis = useResource(analysisStatus);
  const [adding, setAdding] = useState(false),
    [polls, setPolls] = useState(0);
  const live = resource.data?.filter((p) => p.status !== "dismissed") || [];
  const dismissed = resource.data?.filter((p) => p.status === "dismissed") || [];
  const tones = tonesByOrder((resource.data || []).map((p) => p.id));
  const { refresh } = resource;
  const refreshAnalysis = analysis.refresh;
  // PAI works the paths out on its own (education, Mirror, chat); the page
  // only shows a run in progress and picks up its paths when it ends.
  const finding = analysis.data ? !analysis.data.done : false;
  const needsEducation = analysis.data?.done && analysis.data.outcome === "needs_education";
  useEffect(() => {
    if (!finding) return;
    // Counted, not keyed on the response, so an unchanged answer still looks again.
    const timer = setTimeout(() => {
      void Promise.all([refresh(), refreshAnalysis()]).then(() => setPolls((n) => n + 1));
    }, FINDING_EVERY_MS);
    return () => clearTimeout(timer);
  }, [finding, polls, refresh, refreshAnalysis]);
  const added = () => { void refresh(); void refreshAnalysis(); };
  const actions = (
    <Button size="tap" variant="outline" onClick={() => setAdding(true)}><Plus aria-hidden />{copy.addOwn}</Button>
  );
  return (
    <>
      <Heading title={copy.pathsTitle} description={copy.pathsIntro} icon={Compass} tone="teal"
        action={resource.data?.length ? actions : undefined} />
      <AddOwnPath open={adding} onOpenChange={setAdding} onAdded={added} />
      {finding && (
        <p role="status" className="mb-5 flex items-start gap-2.5 rounded-2xl bg-info-soft px-4 py-3 text-sm text-info-ink">
          <Loader2 aria-hidden className="mt-0.5 size-4 shrink-0 animate-spin" />{copy.findingPaths}
        </p>
      )}
      {needsEducation && !finding && (
        <p role="status" className="mb-5 flex items-start gap-2.5 rounded-2xl bg-info-soft px-4 py-3 text-sm text-info-ink">
          <Info aria-hidden className="mt-0.5 size-4 shrink-0" />{copy.pathsNeedEducation}
        </p>
      )}
      {!resource.data || resource.error ? (
        <LoadState error={resource.error} busy={resource.busy} retry={resource.refresh} />
      ) : !resource.data.length ? (
        <EmptyState icon={Compass} tone="teal" title={copy.pathsEmptyTitle} description={copy.pathsEmptyBody}
          action={<div className="flex flex-wrap justify-center gap-2">
            {actions}
            {onChat && <Button size="tap" variant="ghost" onClick={() => onChat()}><MessageCircle aria-hidden />{copy.openChat}</Button>}
          </div>} />
      ) : (
        <>
          <ul className={LIST}>
            {live.map((path) => (
              <PathRow path={path} tone={tones[path.id]} key={path.id} onOpen={() => onOpen(path.id)} onChange={resource.refresh} />
            ))}
          </ul>
          {dismissed.length > 0 && (
            <details className="group mt-8">
              <summary className="inline-flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-xl px-1 font-semibold text-muted-foreground">
                <ArrowRight aria-hidden className="size-4 transition-transform group-open:rotate-90" />
                {fill(copy.dismissedTitle, { count: dismissed.length })}
              </summary>
              <ul className={cn(LIST, "mt-4 opacity-80")}>
                {dismissed.map((path) => (
                  <PathRow path={path} tone={tones[path.id]} key={path.id} onOpen={() => onOpen(path.id)} onChange={resource.refresh} />
                ))}
              </ul>
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
      <header className="mb-6">
        <div className="flex items-center gap-3.5">
          <span aria-hidden className={cn("flex size-12 shrink-0 items-center justify-center rounded-full text-sm font-semibold", toneClass[tone].soft, toneClass[tone].ink)}>
            {initials(result.possibility.title)}
          </span>
          <h1 className="min-w-0 text-balance font-display text-[1.85rem] leading-[1.15] sm:text-[2.1rem]">{result.possibility.title}</h1>
        </div>
        <FieldNotes field={result.possibility.study_field} className="mt-3" />
        <p className="mt-4 max-w-3xl text-pretty text-[15px] leading-relaxed">
          <span className="font-semibold text-muted-foreground">{copy.why}: </span>{result.possibility.why}
        </p>
        <WhyEvidence evidence={result.possibility.evidence} className="mt-2" />
        <p className="mt-1 text-[13px] text-muted-foreground">{copy.pathIntro}</p>
      </header>
      {result.status === "stale" && (
        <section className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-[14px] bg-warning-soft px-5 py-4 text-warning-ink">
          <p className="flex items-start gap-2 text-sm font-medium"><Info aria-hidden className="mt-0.5 size-4 shrink-0" />{copy.stalePath}</p>
          <Button size="tap" variant="outline" disabled={busy} onClick={start}><RefreshCw aria-hidden />{copy.refresh}</Button>
          {error && <p role="alert" className="w-full text-sm font-medium text-danger-ink">{copy.error}</p>}
        </section>
      )}
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_20rem] xl:grid-cols-[minmax(0,1fr)_23rem]">
        {!result.path ? (
          <section className={cn(CARD, "p-6 sm:p-8")}>
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
          /* One card, one row per topic: easy to read down, nothing competing. */
          <section aria-label={result.possibility.title} className={cn(CARD, "divide-y divide-border/70 px-5 sm:px-6")}>
            {Object.entries(copy.pathSections).map(([key, label]) => {
              const value = result.path?.[key];
              const facts = result.facts.filter((f) => f.field === key);
              const Icon = SECTION_ICONS[copy.pathSectionIcons[key as keyof typeof copy.pathSectionIcons]] || BookOpen;
              return (
                <div key={key} className="grid gap-2 py-5 sm:grid-cols-[10.5rem_minmax(0,1fr)] sm:gap-6">
                  <h2 className="flex items-center gap-2 text-[13px] font-semibold text-muted-foreground">
                    <Icon aria-hidden className="size-4 shrink-0 text-primary" />{label}
                  </h2>
                  <div className="min-w-0">
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
                      <p className="flex items-center gap-1.5 text-sm text-muted-foreground"><Info aria-hidden className="size-3.5 shrink-0" />{copy.needsChecking}</p>
                    )}
                  </div>
                </div>
              );
            })}
          </section>
        )}
        <aside className="space-y-5">
          {!!result.possibility.fit?.length && (
            <section aria-labelledby="path-fit" className={cn(CARD, "p-5")}>
              <h2 id="path-fit" className="font-display text-lg leading-tight">{copy.fitTitle}</h2>
              <p className="mb-4 mt-1 text-[12px] text-muted-foreground">{copy.fitLegend}</p>
              <FitList items={result.possibility.fit} detailed />
            </section>
          )}
          {result.path && (
            <section aria-labelledby="path-try" className="rounded-[22px] bg-powder p-5 text-signal-ink">
              <h2 id="path-try" className="flex items-center gap-2 font-display text-lg leading-tight"><Sparkles aria-hidden className="size-4" />{copy.tryIt}</h2>
              <p className="mt-2 text-pretty text-sm leading-relaxed">{human(result.path.try_it)}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button size="tap" disabled={busy || activityScheduled} onClick={async () => {
                  setBusy(true); setError(false);
                  try { await workspaceApi.acceptPathActivity(id); setActivityScheduled(true); } catch { setError(true); } finally { setBusy(false); }
                }}>{activityScheduled ? copy.activityScheduled : copy.acceptActivity}</Button>
                <Button size="tap" variant="outline" className="bg-white/70" onClick={() => onChat(copy.reflection)}>
                  <MessageCircle aria-hidden />{copy.reflection}
                </Button>
              </div>
              {error && <p role="alert" className="mt-3 text-sm font-medium text-danger-ink">{copy.error}</p>}
            </section>
          )}
          {result.path && (
            <section aria-labelledby="path-places" className={cn(CARD, "p-5")}>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">{copy.placesCta}</p>
              <h2 id="path-places" className="mt-1 font-display text-lg leading-tight">{copy.places}</h2>
              <p className="mt-1 text-[13px] text-muted-foreground">{copy.placesIntro}</p>
              <Button size="tap" className="mt-4 w-full" onClick={onPlaces}><MapPin aria-hidden />{copy.placesOpen}<ArrowRight aria-hidden /></Button>
            </section>
          )}
        </aside>
      </div>
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
    <article className={cn(CARD, "flex min-w-0 flex-col p-5 sm:p-6")}>
      <div className="flex items-start gap-3">
        <span aria-hidden className={cn("flex size-11 shrink-0 items-center justify-center rounded-full", toneClass[tone].soft, toneClass[tone].ink)}>
          <GraduationCap className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="break-words font-display text-lg leading-snug">{program.title}</h2>
          <Source fact={program as unknown as Record<string, unknown>} />
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{copy.eligibilityTitle}</span>
        <EligibilityPill label={program.eligibility.label} />
      </div>
      {program.fees && Object.keys(program.fees).length > 0 && (
        <section className="mt-4 rounded-[14px] bg-background px-4 py-3 text-sm">
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
        <section className="mt-4 rounded-[14px] bg-brand-soft px-4 py-3">
          <h3 className="text-sm font-semibold text-primary">{copy.route}</h3>
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
  onRoadmap,
}: {
  id: string;
  onBack: () => void;
  onRoadmap?: () => void;
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
            <section className={cn(CARD, "mx-auto max-w-2xl p-6 sm:p-8")}>
              <span aria-hidden className="flex size-11 items-center justify-center rounded-full bg-brand-soft text-primary"><ShieldCheck className="size-5" /></span>
              <h2 className="mt-4 font-display text-xl">{copy.consentTitle}</h2>
              <p className="mt-2 text-pretty text-muted-foreground">{copy.consentBody}</p>
              {resource.data.status === "stale" && <div className="mt-4"><NeedsChecking /></div>}
              <label className={cn("mt-5 flex min-h-14 cursor-pointer items-center gap-3 rounded-2xl border-2 px-4 py-3 font-semibold transition-colors",
                consent ? "border-primary bg-brand-soft text-foreground" : "border-border hover:border-primary/40")}>
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
            <section className={cn(CARD, "p-6")}>
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
          {resource.data.status === "completed" && onRoadmap && (
            <section className="mt-6 flex flex-wrap items-center justify-between gap-4 rounded-[22px] bg-powder p-6 text-signal-ink sm:p-7">
              <div className="max-w-xl">
                <h2 className="font-display text-xl leading-tight">{copy.nextStepTitle}</h2>
                <p className="mt-1 text-sm">{copy.decisionPending}</p>
              </div>
              <Button size="tap" onClick={onRoadmap}>
                {copy.openRoadmap}<ArrowRight aria-hidden />
              </Button>
            </section>
          )}
        </>
      )}
    </>
  );
}
