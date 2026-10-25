"use client";
import { useEffect, useRef, useState } from "react";
import { AlertCircle, MessageCircle, PencilLine } from "lucide-react";
import { workspaceApi } from "@/lib/api";
import type { LivingPicture } from "@/lib/counselor-workspace";
import { badgeLevel, conflictFor, vaultEntries, type VaultCatalog, type VaultCatalogType, type VaultEntry } from "@/lib/vault";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { AreaHeatmap, evidenceLevel, vaultBadgeLabel, type HeatmapArea } from "@/components/pai";
import { cn } from "@/lib/utils";
import copy from "./copy.json";
import layout from "./profile-layout.json";
import { missingBasics, resultsToProve } from "./profile-basics";
import labels from "@/lib/evidence-labels.json";
import { LoadState, useResource, human } from "./resource";
import { MirrorPanel, areaIcon, fill, text } from "./profile-parts";
import {
  DocumentLink, EntryBadge, FactReview, ReadableValue, StaleMarker, ValueEditor, readable, useOpenDocument,
} from "./profile-details";
import { StoryArea, areaOf } from "./profile-story";
import { ConflictBanner, ConflictReview, ConflictSummary } from "./vault-conflicts";
export { CertaintyChart } from "./profile-parts";

const load = async () => {
  const [picture, vault, catalog] = await Promise.all([
    // The Mirror still comes from the counselor picture; a failed read only
    // hides it, never the Vault.
    workspaceApi.getCounselorWorkspace().catch(() => null),
    workspaceApi.getVault(),
    // Without the catalog the page still reads; only Add and Edit step back.
    workspaceApi.getVaultCatalog().catch((): VaultCatalog => ({ types: [] })),
  ]);
  return { picture, vault, catalog };
};
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

/** A record's headline: its title field, then up to two other values. */
function summary(value: unknown): { title: string; sub: string } {
  if (!value || typeof value !== "object" || Array.isArray(value)) return { title: human(value), sub: "" };
  const record = value as Record<string, unknown>;
  const titleKey = layout.titleFields.find((key) => human(record[key]));
  const rest = Object.entries(record)
    .filter(([key, v]) => key !== titleKey && !labels.hidden.includes(key) && typeof v !== "object" && human(v))
    .slice(0, 2).map(([, v]) => human(v));
  return { title: titleKey ? human(record[titleKey]) : rest.shift() || "", sub: rest.join(" · ") };
}

/** One Vault entry as a form-like field: the label above, the value in a
 * box with its badge, a file link when a document backs it, and a quiet
 * re-check marker when it may be out of date. */
function FactField({ entry, type, onOpen, openDocument, questioned }: {
  entry: VaultEntry; type: VaultCatalogType | null; onOpen: () => void; openDocument: ((fileId: string) => void) | null;
  /** An open conflict asks about this entry: tapping it reviews that conflict. */
  questioned?: boolean;
}) {
  const { title, sub } = summary(readable(entry, type));
  const shown = title || entry.display;
  const aria = questioned ? fill(text.conflictFieldAria, { label: entry.label, value: shown })
    : fill(entry.stale ? text.fieldAriaStale : text.fieldAria, { label: entry.label, value: shown, badge: vaultBadgeLabel(badgeLevel(entry)) });
  return (
    <div className="min-w-0">
      <p className="mb-1.5 text-sm font-semibold">{entry.label}</p>
      <div className="flex min-h-12 w-full items-center rounded-xl border bg-card shadow-[inset_0_1px_2px_rgb(22_34_75/0.04)] transition-colors focus-within:border-primary/50 hover:border-primary/50">
        <button type="button" onClick={onOpen} aria-haspopup="dialog"
          aria-label={aria}
          className="group flex min-h-12 min-w-0 flex-1 items-center gap-3 rounded-xl px-4 py-2.5 text-left">
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[15px] font-semibold">{shown}</span>
            {sub && <span className="block truncate text-xs text-muted-foreground">{sub}</span>}
          </span>
          <EntryBadge entry={entry} compact />
          <PencilLine aria-hidden className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-primary" />
        </button>
        {entry.document && openDocument && <DocumentLink document={entry.document} open={openDocument} className="me-2" />}
      </div>
      {entry.stale && <StaleMarker />}
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
 * Details as fields and Background as their story with PAI. Everything but
 * the Mirror reads the Vault (`/v1/vault`). */
export function LivingProfile({
  onChat,
  onNavigate,
}: {
  onChat: (topic?: string) => void;
  onNavigate?: (view: string) => void;
  stage?: { id: string; title: string };
}) {
  const resource = useResource(load);
  const openDocument = useOpenDocument(onNavigate);
  const [tab, setTab] = useState<Tab>("details");
  const [openId, setOpenId] = useState<string | null>(null);
  // The conflict review: open with the card to start at (null: the first).
  const [review, setReview] = useState<{ start: string | null } | null>(null);
  const answered = useRef(false);
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
  const { picture, vault, catalog } = resource.data;
  const typeOf = (key: string) => catalog.types.find((t) => t.key === key) || null;
  // A preferred name is no longer asked for; older saved ones stay out of view.
  const visible = (entry: VaultEntry) => !layout.hiddenKeys.includes(entry.type);
  const entries = vaultEntries(vault).filter(visible);
  const first = (type: string) => entries.find((e) => e.type === type);
  const education = entries.filter((e) => e.type === "education");
  const current = education.find((e) => (e.value as Record<string, unknown>)?.academic_status === "current") || education[0];
  const level = current ? summary(readable(current, typeOf("education"))).title || current.display : undefined;
  const name = first("identity.full_name")?.display || copy.nav.profile;
  const missing = missingBasics(entries);
  const toProve = resultsToProve(entries);
  const pct = Math.round(((layout.basics.length - missing.length) / layout.basics.length) * 100);
  const sections = layout.vaultSections as Record<string, string>;
  const groups = Object.entries(vault.details)
    .map(([id, section]) => ({ id, title: sections[id] || section.label, rows: section.entries.filter(visible) }))
    .filter(({ id, rows }) => rows.length || layout.alwaysShow.includes(id));
  const opened = entries.find((e) => e.id === openId) || null;
  const refresh = () => void resource.refresh();
  const conflicts = vault.conflicts;
  // An entry "In question" opens the review on its own conflict, not the entry dialog.
  const openEntry = (id: string) => {
    const entry = entries.find((e) => e.id === id);
    const conflict = entry && conflictFor(conflicts, entry);
    if (conflict) setReview({ start: conflict.id }); else setOpenId(id);
  };
  const closeReview = () => {
    setReview(null);
    if (answered.current) { answered.current = false; refresh(); }
  };
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
            {[level || text.statusFallback, first("location.current_city")?.display].filter(Boolean).join(" · ")}
          </p>
        </div>
      </header>

      <ConflictBanner count={conflicts.length} onReview={() => setReview({ start: null })} />

      {/* The tabs stay in view while the page scrolls, so the student can always switch. */}
      <div role="tablist" aria-label={text.tabsLabel} className="sticky top-0 z-10 -mx-4 mt-6 flex gap-6 border-b bg-background/95 px-4 backdrop-blur sm:-mx-8 sm:px-8">
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
              {groups.map(({ id, title, rows }, index) => (
                <section key={id} aria-labelledby={`group-${id}`} className={cn(index > 0 && "border-t pt-7")}>
                  <h2 id={`group-${id}`} className="mb-4 text-xl font-bold tracking-tight">{title}</h2>
                  <div className="grid gap-x-4 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
                    {rows.map((entry) => (
                      <FactField key={entry.id} entry={entry} type={typeOf(entry.type)} openDocument={openDocument}
                        questioned={!!conflictFor(conflicts, entry)} onOpen={() => openEntry(entry.id)} />
                    ))}
                    {!rows.length && (
                      <div className="min-w-0">
                        <p className="mb-1.5 text-sm font-semibold">{text.emptyGroup}</p>
                        <button type="button" onClick={() => onChat(layout.copy.emptyDrafts[id as keyof typeof layout.copy.emptyDrafts])}
                          className="group flex min-h-12 w-full items-center justify-between gap-3 rounded-xl border border-dashed border-input bg-card/60 px-4 py-2.5 text-left text-[15px] font-semibold text-primary transition-colors hover:border-primary/50 hover:bg-card">
                          {text.emptyGroupAction}<MessageCircle aria-hidden className="size-4 shrink-0" />
                        </button>
                      </div>
                    )}
                  </div>
                </section>
              ))}
            </div>
            <div className="space-y-4">
            <ConflictSummary conflicts={conflicts} onReview={(start) => setReview({ start })} />
            {toProve.length > 0 && onNavigate && (
              <section aria-labelledby="proof-title" className="rounded-2xl border bg-card p-5 shadow-soft">
                <h2 id="proof-title" className="text-lg font-bold">{text.proofTitle}</h2>
                <p className="mt-1 text-sm text-muted-foreground">{text.proofIntro}</p>
                <ul className="mt-2 space-y-1 text-sm font-semibold">
                  {toProve.map((entry) => <li key={entry.id}>{summary(readable(entry, typeOf(entry.type))).title || entry.label}</li>)}
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
            {picture && <MirrorPanel picture={picture} onChat={onChat} onChanged={resource.refresh} />}
            <section aria-labelledby="story-title">
              <h2 id="story-title" className="text-xl font-bold tracking-tight">{text.storyTitle}</h2>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{text.storyIntro}</p>
              <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {Object.keys(layout.storyAreas).map((area) => {
                  const cards = vault.story.filter((card) => areaOf(card.type) === area)
                    .map((card) => ({ ...card, entries: card.entries.filter(visible) }));
                  const types = cards.map((card) => typeOf(card.type)).filter((t): t is VaultCatalogType => t !== null);
                  return <StoryArea key={area} area={area} cards={cards} types={types} onChat={onChat} onOpen={openEntry} onSaved={refresh} />;
                })}
              </div>
            </section>
          </div>
        )}
      </div>

      <ConflictReview conflicts={conflicts} startId={review?.start ?? null} open={!!review} typeOf={typeOf}
        openDocument={openDocument} onAnswered={() => { answered.current = true; }} onClose={closeReview} />

      <Dialog open={!!opened} onOpenChange={(open) => { if (!open) setOpenId(null); }}>
        <DialogContent className="max-w-lg">
          {opened && (
            <>
              <DialogHeader>
                <DialogTitle>{opened.label}</DialogTitle>
                <DialogDescription className="sr-only">{fill(text.expand, { label: opened.label })}</DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                <ReadableValue value={readable(opened, typeOf(opened.type))} />
                <FactReview key={`${opened.id}:${opened.level}:${opened.display}`} entry={opened} type={typeOf(opened.type)}
                  openDocument={openDocument && ((fileId) => { setOpenId(null); openDocument(fileId); })}
                  onSaved={() => { setOpenId(null); refresh(); }} />
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
