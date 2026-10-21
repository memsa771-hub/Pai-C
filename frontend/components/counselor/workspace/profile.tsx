"use client";
import { useEffect, useState } from "react";
import { AlertCircle, Lock, MessageCircle, PencilLine } from "lucide-react";
import { workspaceApi } from "@/lib/api";
import type { LivingPicture, ProfileCard } from "@/lib/counselor-workspace";
import type { ProfileIssue } from "@/lib/student-profile";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { AreaHeatmap, EvidenceBadge, evidenceLevel, type HeatmapArea } from "@/components/pai";
import { cn } from "@/lib/utils";
import copy from "./copy.json";
import layout from "./profile-layout.json";
import { missingBasics, resultsToProve } from "./profile-basics";
import labels from "@/lib/evidence-labels.json";
import { LoadState, useResource, human, evidenceLabel } from "./resource";
import { MirrorPanel, areaIcon, fill, text } from "./profile-parts";
import { FactReview, ReadableValue, at, groupOf } from "./profile-details";
export { CertaintyChart } from "./profile-parts";
export { FactRow as EvidenceCard } from "./profile-details";

const load = async () => {
  const [picture, cards, profile] = await Promise.all([
    workspaceApi.getCounselorWorkspace(),
    workspaceApi.getProfileCards(),
    // Open conflicts (what the student said vs. what the profile holds). A
    // failed read only hides the check panel; it never blocks the profile.
    workspaceApi.getStudentProfile().catch(() => null),
  ]);
  return { picture, cards: cards.cards, issues: (profile?.issues || []) as ProfileIssue[] };
};
const EDUCATION = ["education", "course", "test_attempt", "certification"];
type Tab = "details" | "background";

export function heatmapAreas(coverage: LivingPicture["coverage"]): HeatmapArea[] {
  return Object.entries(copy.areas).map(([key, label]) => {
    const area = coverage[key];
    const count = area?.item_count || 0;
    return { key, label, icon: areaIcon(key), count, level: count ? evidenceLevel(area?.evidence || "stated") : "none" };
  });
}

/** Ten areas as a heatmap: fill = strength of evidence, dots = amount. */
export function CoverageHeatmap({ coverage, selected, onSelect }: {
  coverage: LivingPicture["coverage"]; selected?: string | null; onSelect?: (area: string | null) => void;
}) {
  return <AreaHeatmap title={text.heatmapTitle} areas={heatmapAreas(coverage)} selected={selected} onSelect={onSelect} />;
}

/** One open conflict, resolved through the reconciler: keep what the profile
 * holds, or take what the student said. Conflicts whose field may not be
 * named on the profile are offered as a conversation instead. */
function CheckItem({ issue, onDone, onChat }: { issue: ProfileIssue; onDone: () => void; onChat: (topic?: string) => void }) {
  const [busy, setBusy] = useState(false), [failed, setFailed] = useState(false);
  const label = issue.fieldKey ? evidenceLabel(issue.fieldKey) : "";
  const current = human(issue.values?.current), proposed = human(issue.values?.proposed);
  async function resolve(action: "keep_current" | "accept_proposed") {
    setBusy(true); setFailed(false);
    try { await workspaceApi.resolveProfileIssue(issue.id, action); onDone(); }
    catch { setFailed(true); setBusy(false); }
  }
  if (!label || !current || !proposed)
    return (
      <li className="flex flex-wrap items-center justify-between gap-3 py-3">
        <p className="text-sm">{text.checkOther}</p>
        <Button size="tap" variant="outline" onClick={() => onChat(fill(text.checkDraft, { label: label.toLowerCase() || "details" }))}>{text.checkTalk}</Button>
      </li>
    );
  return (
    <li className="py-3">
      <p className="text-xs font-semibold text-muted-foreground">{label}</p>
      <p className="mt-0.5 text-sm">{fill(text.checkLine, { current, proposed })}</p>
      <div className="mt-2.5 flex flex-wrap gap-2">
        <Button size="tap" variant="outline" disabled={busy} onClick={() => resolve("keep_current")}>{fill(text.checkKeep, { value: current })}</Button>
        <Button size="tap" disabled={busy} onClick={() => resolve("accept_proposed")}>{fill(text.checkUse, { value: proposed })}</Button>
      </div>
      {failed && <p role="alert" className="mt-2 text-sm text-danger-ink">{text.checkFailed}</p>}
    </li>
  );
}

/** A record's headline: its title field, then up to two other values. */
function summary(value: unknown): { title: string; sub: string } {
  if (!value || typeof value !== "object" || Array.isArray(value)) return { title: human(value), sub: "" };
  const record = value as Record<string, unknown>;
  const titleKey = layout.titleFields.find((key) => human(record[key]));
  const rest = Object.entries(record)
    .filter(([key, v]) => key !== titleKey && !labels.hidden.includes(key) && human(v))
    .slice(0, 2).map(([, v]) => human(v));
  return { title: titleKey ? human(record[titleKey]) : rest.shift() || "", sub: rest.join(" · ") };
}

/** One saved fact as a form-like field: the label above, the value in a box.
 * Opening it shows the source and the Confirm / Edit / Remove review. */
function FactField({ card, hidden, onOpen }: { card: ProfileCard; hidden: boolean; onOpen: () => void }) {
  const label = evidenceLabel(card.key);
  const { title, sub } = summary(card.value);
  return (
    <div className="min-w-0">
      <p className="mb-1.5 text-sm font-semibold">{label}</p>
      <button type="button" onClick={onOpen} aria-haspopup="dialog"
        aria-label={`${fill(text.expand, { label })}: ${hidden ? text.sensitiveHidden : title}`}
        className="group flex min-h-12 w-full items-center gap-3 rounded-xl border bg-card px-4 py-2.5 text-left shadow-[inset_0_1px_2px_rgb(22_34_75/0.04)] transition-colors hover:border-primary/50">
        <span className="min-w-0 flex-1">
          {hidden ? (
            <span className="flex items-center gap-1.5 text-sm italic text-muted-foreground"><Lock aria-hidden className="size-3.5" />{text.sensitiveHidden}</span>
          ) : (
            <>
              <span className="block truncate text-[15px] font-semibold">{title}</span>
              {sub && <span className="block truncate text-xs text-muted-foreground">{sub}</span>}
            </>
          )}
        </span>
        <EvidenceBadge compact level={evidenceLevel(card.evidence_level)} />
        <PencilLine aria-hidden className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" />
      </button>
    </div>
  );
}

function Ring({ pct }: { pct: number }) {
  const r = 26, c = 2 * Math.PI * r;
  return (
    <span className="relative flex size-16 shrink-0 items-center justify-center sm:size-[72px]" role="img" aria-label={fill(text.complete, { pct })}>
      <svg viewBox="0 0 64 64" className="absolute inset-0 size-full -rotate-90" aria-hidden>
        <circle cx="32" cy="32" r={r} fill="none" stroke="var(--border)" strokeWidth="6" />
        <circle cx="32" cy="32" r={r} fill="none" stroke="var(--primary)" strokeWidth="6" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - pct / 100)} className="transition-[stroke-dashoffset] duration-700" />
      </svg>
      <span className="text-sm font-bold tabular-nums">{pct}%</span>
    </span>
  );
}

/** The student's profile, laid out like a record they own (the founder's
 * Kollegio reference): a header with how complete the basics are, then
 * Details as fields and Background as their story with PAI. */
export function LivingProfile({
  onChat,
  onNavigate,
}: {
  onChat: (topic?: string) => void;
  onNavigate?: (view: string) => void;
  stage?: { id: string; title: string };
}) {
  const resource = useResource(load);
  const [tab, setTab] = useState<Tab>("details");
  const [openId, setOpenId] = useState<string | null>(null);
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("tab") === "background") setTab("background");
  }, []);
  const switchTab = (next: Tab) => {
    setTab(next);
    const q = new URLSearchParams(window.location.search);
    if (next === "background") q.set("tab", "background"); else q.delete("tab");
    window.history.replaceState({}, "", `${window.location.pathname}?${q}`);
  };
  if (!resource.data || resource.error)
    return <LoadState error={resource.error} busy={resource.busy} retry={resource.refresh} skeleton="profile" />;
  const { picture } = resource.data;
  // A preferred name is no longer asked for; older saved ones stay out of view.
  const cards = resource.data.cards.filter((card: ProfileCard) => !layout.hiddenKeys.includes(card.key));
  const value = (key: string) => human(cards.find((c) => c.key === key)?.value) || undefined;
  const education = cards.filter((c) => EDUCATION.includes(c.key));
  const current = education.find((c) => (c.value as Record<string, unknown>)?.academic_status === "current") || education[0];
  const level = human((current?.value as Record<string, unknown>)?.qualification_name) || undefined;
  const name = value("identity.full_name") || copy.nav.profile;
  const missing = missingBasics(cards);
  const toProve = resultsToProve(cards);
  const pct = Math.round(((layout.basics.length - missing.length) / layout.basics.length) * 100);
  const groups = layout.detailGroups
    .map((group) => ({ group, rows: cards.filter((card: ProfileCard) => groupOf(card).id === group.id) }))
    .filter(({ group, rows }) => rows.length || layout.alwaysShow.includes(group.id));
  const opened = cards.find((c) => c.id === openId) || null;
  const tabs: { id: Tab; label: string }[] = [
    { id: "details", label: text.tabDetails },
    { id: "background", label: text.tabBackground },
  ];

  return (
    <div>
      <header className="flex flex-wrap items-center gap-4 sm:gap-5">
        <Ring pct={pct} />
        <div className="min-w-0 basis-48 flex-1">
          <h1 className="break-words text-2xl font-bold leading-tight tracking-tight sm:text-[2rem]">{name}</h1>
          <p className="text-lg font-semibold leading-tight text-muted-foreground sm:text-[1.6rem]">
            {[level || text.statusFallback, value("location.current_city")].filter(Boolean).join(" · ")}
          </p>
        </div>
      </header>

      <div role="tablist" aria-label={text.tabsLabel} className="mt-6 flex gap-6 border-b">
        {tabs.map(({ id, label }) => (
          <button key={id} role="tab" id={`profile-tab-${id}`} aria-selected={tab === id} aria-controls={`profile-panel-${id}`}
            tabIndex={tab === id ? 0 : -1} onClick={() => switchTab(id)}
            onKeyDown={(e) => {
              if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
              e.preventDefault();
              const next = id === "details" ? "background" : "details";
              switchTab(next);
              document.getElementById(`profile-tab-${next}`)?.focus();
            }}
            className={cn("relative min-h-12 text-[15px] transition-colors",
              tab === id ? "font-bold text-foreground after:absolute after:inset-x-0 after:-bottom-px after:h-[3px] after:rounded-t-full after:bg-primary"
                : "font-medium text-muted-foreground hover:text-foreground")}>
            {label}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`profile-panel-${tab}`} aria-labelledby={`profile-tab-${tab}`} className="pt-7">
        {tab === "details" ? (
          <div className="grid items-start gap-8 xl:grid-cols-[minmax(0,1fr)_18rem]">
            <div className="min-w-0 space-y-8">
              {groups.map(({ group, rows }, index) => (
                <section key={group.id} aria-labelledby={`group-${group.id}`} className={cn(index > 0 && "border-t pt-7")}>
                  <h2 id={`group-${group.id}`} className="mb-4 text-xl font-bold tracking-tight">{group.title}</h2>
                  <div className="grid gap-x-4 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
                    {rows.map((card) => (
                      <FactField key={card.id} card={card} hidden={false} onOpen={() => setOpenId(card.id)} />
                    ))}
                    {!rows.length && (
                      <div className="min-w-0">
                        <p className="mb-1.5 text-sm font-semibold">{text.emptyGroup}</p>
                        <button type="button" onClick={() => onChat(layout.copy.emptyDrafts[group.id as keyof typeof layout.copy.emptyDrafts])}
                          className="group flex min-h-12 w-full items-center justify-between gap-3 rounded-xl border border-dashed border-input bg-card/60 px-4 py-2.5 text-left text-[15px] font-semibold text-primary transition-colors hover:border-primary/50 hover:bg-card">
                          {text.emptyGroupAction}<MessageCircle aria-hidden className="size-4 shrink-0" />
                        </button>
                      </div>
                    )}
                  </div>
                </section>
              ))}
            </div>
            <div className="space-y-4 xl:sticky xl:top-4">
            {resource.data.issues.length > 0 && (
              <section aria-labelledby="check-title" className="rounded-2xl border border-warning/40 bg-card p-5 shadow-soft">
                <h2 id="check-title" className="flex items-center gap-2 text-lg font-bold">
                  <AlertCircle aria-hidden className="size-5 text-warning" />{text.checkTitle}
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">{text.checkIntro}</p>
                <ul className="mt-1 divide-y">
                  {resource.data.issues.map((issue) => <CheckItem key={issue.id} issue={issue} onDone={() => void resource.refresh()} onChat={onChat} />)}
                </ul>
              </section>
            )}
            {toProve.length > 0 && onNavigate && (
              <section aria-labelledby="proof-title" className="rounded-2xl border bg-card p-5 shadow-soft">
                <h2 id="proof-title" className="text-lg font-bold">{text.proofTitle}</h2>
                <p className="mt-1 text-sm text-muted-foreground">{text.proofIntro}</p>
                <ul className="mt-2 space-y-1 text-sm font-semibold">
                  {toProve.map((card) => <li key={card.id}>{summary(card.value).title || evidenceLabel(card.key)}</li>)}
                </ul>
                <Button size="tap" className="mt-3" onClick={() => onNavigate("files")}>{text.proofAction}</Button>
              </section>
            )}
            <aside aria-labelledby="missing-title" className="rounded-2xl border bg-card p-5 shadow-soft">
              <h2 id="missing-title" className="flex items-center gap-2 text-lg font-bold">
                <AlertCircle aria-hidden className="size-5 text-warning" />{text.missingTitle}
              </h2>
              {missing.length ? (
                <ul className="mt-2 divide-y">
                  {missing.map((item) => (
                    <li key={item.key}>
                      <button onClick={() => onChat(fill(text.missingDraft, { label: item.label.toLowerCase() }))}
                        className="group flex w-full flex-col items-start py-3 text-left">
                        <span className="text-xs text-muted-foreground">{item.label}</span>
                        <span className="text-[15px] font-semibold group-hover:text-primary">{text.missingAction}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : <p className="mt-2 text-sm text-muted-foreground">{text.missingNone}</p>}
            </aside>
            </div>
          </div>
        ) : (
          <div className="space-y-8">
            <MirrorPanel picture={picture} onChat={onChat} onChanged={resource.refresh} />
            <section aria-labelledby="story-title">
              <h2 id="story-title" className="text-xl font-bold tracking-tight">{text.storyTitle}</h2>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{text.storyIntro}</p>
              <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {layout.sharedGroups.map(({ area, source }) => {
                  const items = at(picture, source);
                  const label = copy.areas[area as keyof typeof copy.areas] || area;
                  return (
                    <article key={area} className="flex flex-col rounded-2xl border bg-card p-5 shadow-soft">
                      <div className="flex items-start justify-between gap-3 border-b pb-3">
                        <h3 className="text-base font-bold leading-snug">{label}</h3>
                        <button onClick={() => onChat(fill(text.storyDraft, { area: label.toLowerCase() }))} aria-label={`${text.storyTalk}: ${label}`}
                          className="flex size-9 shrink-0 items-center justify-center rounded-full border transition-colors hover:border-primary hover:text-primary">
                          <MessageCircle aria-hidden className="size-4" />
                        </button>
                      </div>
                      <p className="mt-3 text-sm text-muted-foreground">{layout.story[area as keyof typeof layout.story]}</p>
                      {items.length > 0 && (
                        <ul className="mt-3 space-y-2 text-sm">
                          {items.slice(0, 3).map((item, i) => (
                            <li key={item.id || i} className="min-w-0">
                              <span className="font-semibold">{human(item.value || item.role)}</span>
                              {item.wish && <span className="block text-muted-foreground">{text.wish}: {human(item.wish)}</span>}
                              {(item.worry || item.concern) && <span className="block text-muted-foreground">{text.worry}: {human(item.worry || item.concern)}</span>}
                            </li>
                          ))}
                        </ul>
                      )}
                      <div className="mt-auto pt-4">
                        <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                          <div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(items.length, 3) / 3 * 100}%` }} />
                        </div>
                        <p className="mt-1.5 text-xs font-semibold text-muted-foreground">{fill(text.sharedCount, { count: items.length })}</p>
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          </div>
        )}
      </div>

      <Dialog open={!!opened} onOpenChange={(open) => { if (!open) setOpenId(null); }}>
        <DialogContent className="max-w-lg">
          {opened && (
            <>
              <DialogHeader>
                <DialogTitle>{evidenceLabel(opened.key)}</DialogTitle>
                <DialogDescription className="sr-only">{fill(text.expand, { label: evidenceLabel(opened.key) })}</DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                <ReadableValue value={opened.value} />
                <FactReview key={opened.id + opened.digest} card={opened}
                  onSaved={() => { setOpenId(null); void resource.refresh(); }} />
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
