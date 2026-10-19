"use client";
import { useEffect, useRef, useState } from "react";
import { Eye, EyeOff, Flag, GraduationCap, LayoutGrid, List, MapPin, MessageCircle, RefreshCw, ShieldCheck, TrendingUp, Users } from "lucide-react";
import { workspaceApi } from "@/lib/api";
import type { LivingPicture, ProfileCard } from "@/lib/counselor-workspace";
import { Button } from "@/components/ui/button";
import { AreaHeatmap, SectionCard, evidenceLevel, toneClass, type HeatmapArea } from "@/components/pai";
import { cn } from "@/lib/utils";
import copy from "./copy.json";
import { LoadState, useResource, human, shortDate } from "./resource";
import {
  CertaintyChart, ChipCloud, EducationTimeline, MirrorPanel, PeopleMap, areaIcon, areaTone, fill, text,
} from "./profile-parts";
import { DetailsView } from "./profile-details";
export { CertaintyChart } from "./profile-parts";
export { FactRow as EvidenceCard } from "./profile-details";

const load = async () => {
  const [picture, cards] = await Promise.all([
    workspaceApi.getCounselorWorkspace(),
    workspaceApi.getProfileCards(),
  ]);
  return { picture, cards: cards.cards };
};
const EDUCATION = ["education", "course", "test_attempt", "certification"];
type Tab = "visual" | "details";

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

function ProfileHeader({ name, level, city, stage, updated }: { name: string; level?: string; city?: string; stage?: { id: string; title: string }; updated?: string }) {
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") || "?";
  const chip = "inline-flex min-h-8 items-center gap-1.5 rounded-full bg-white/20 px-3 text-sm font-medium backdrop-blur";
  return (
    <section className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-[var(--hero-from)] via-[var(--hero-via)] to-[var(--hero-to)] p-5 text-white shadow-lift sm:p-7">
      <span aria-hidden className="absolute -right-10 -top-12 size-48 rounded-full bg-white/10" />
      <span aria-hidden className="absolute -bottom-16 right-24 size-36 rounded-full bg-white/10" />
      <div className="relative flex flex-wrap items-center gap-4 sm:gap-5">
        <span aria-hidden className="flex size-16 shrink-0 items-center justify-center rounded-full bg-white text-xl font-bold text-[#2a3fb8] shadow-lift sm:size-20 sm:text-2xl">{initials}</span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold uppercase tracking-wider text-white/85">{copy.profileTitle}</p>
          <h1 className="mt-0.5 break-words text-2xl font-bold tracking-tight sm:text-3xl">{name}</h1>
          <div className="mt-3 flex flex-wrap gap-2">
            {level && <span className={chip}><GraduationCap aria-hidden className="size-4" />{level}</span>}
            {city && <span className={chip}><MapPin aria-hidden className="size-4" />{city}</span>}
            {stage && <span className={cn(chip, "max-sm:hidden")}><Flag aria-hidden className="size-4" />{copy.shell.stage.replace("{id}", stage.id)} · {stage.title}</span>}
          </div>
        </div>
        {updated && <p className="w-full text-xs text-white/85 sm:w-auto sm:self-start">{fill(text.updated, { date: updated })}</p>}
      </div>
    </section>
  );
}

export function LivingProfile({
  onChat,
  stage,
}: {
  onChat: (topic?: string) => void;
  stage?: { id: string; title: string };
}) {
  const resource = useResource(load);
  const [tab, setTab] = useState<Tab>("visual");
  const [filter, setFilter] = useState<string | null>(null);
  const [showPrivate, setShowPrivate] = useState(false);
  const top = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("tab") === "details") setTab("details");
  }, []);
  const switchTab = (next: Tab) => {
    setTab(next);
    const q = new URLSearchParams(window.location.search);
    if (next === "details") q.set("tab", "details"); else q.delete("tab");
    window.history.replaceState({}, "", `${window.location.pathname}?${q}`);
  };
  if (!resource.data || resource.error)
    return <LoadState error={resource.error} busy={resource.busy} retry={resource.refresh} skeleton="profile" />;
  const { picture, cards } = resource.data;
  const value = (key: string) => human(cards.find((c) => c.key === key)?.value) || undefined;
  const education = cards.filter((c) => EDUCATION.includes(c.key));
  const current = education.find((c) => (c.value as Record<string, unknown>)?.academic_status === "current") || education[0];
  const level = human((current?.value as Record<string, unknown>)?.qualification_name) || undefined;
  const name = value("identity.preferred_name") || value("identity.full_name") || copy.nav.profile;
  const dates = [...cards.map((c) => c.updated_at), ...Object.values(picture.coverage).map((c) => c.last_confirmed || "")].filter(Boolean).sort();
  const skills = Array.isArray(picture.capabilities) ? picture.capabilities : Object.values(picture.capabilities).flat();
  const datedEducation = [...education].sort((a, b) => {
    const date = (card: ProfileCard) => {
      const v = card.value as Record<string, unknown> | null;
      return String(v?.start_date || v?.end_date || v?.completion_date || "9999");
    };
    return date(a).localeCompare(date(b));
  });
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("");
  const missing = Object.entries(copy.areas).filter(([key]) => !picture.coverage[key]?.covered);
  const selectArea = (area: string | null) => {
    setFilter(area);
    if (area) { switchTab("details"); top.current?.scrollIntoView?.({ block: "start" }); }
  };
  const tabs: { id: Tab; label: string; icon: typeof LayoutGrid }[] = [
    { id: "visual", label: text.visual, icon: LayoutGrid },
    { id: "details", label: text.details, icon: List },
  ];
  return (
    <div className="space-y-5">
      <ProfileHeader name={name} level={level} city={value("location.current_city")} stage={stage} updated={shortDate(dates.at(-1))} />
      <div ref={top} className="flex scroll-mt-4 flex-wrap items-center justify-between gap-3">
        <div role="tablist" aria-label={text.viewLabel} className="inline-flex rounded-2xl bg-muted p-1">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button key={id} role="tab" id={`profile-tab-${id}`} aria-selected={tab === id} aria-controls={`profile-panel-${id}`}
              onClick={() => switchTab(id)}
              className={cn("inline-flex min-h-11 items-center gap-2 rounded-xl px-4 text-sm font-semibold transition-colors",
                tab === id ? "bg-card text-foreground shadow-soft" : "text-muted-foreground hover:text-foreground")}>
              <Icon aria-hidden className="size-4" />{label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="tap" variant="ghost" aria-pressed={showPrivate} onClick={() => setShowPrivate(!showPrivate)}>
            {showPrivate ? <EyeOff aria-hidden /> : <Eye aria-hidden />}{showPrivate ? text.hideSensitive : text.showSensitive}
          </Button>
          <Button size="tap" variant="ghost" onClick={resource.refresh} aria-label={copy.refresh} aria-busy={resource.busy}><RefreshCw aria-hidden className={cn(resource.busy && "animate-spin")} /><span className="hidden sm:inline">{copy.refresh}</span></Button>
        </div>
      </div>

      <div role="tabpanel" id={`profile-panel-${tab}`} aria-labelledby={`profile-tab-${tab}`}>
        {tab === "details" ? (
          <DetailsView picture={picture} cards={cards} filter={filter} onFilter={setFilter} showPrivate={showPrivate}
            onSaved={resource.refresh} onChat={onChat} />
        ) : (
          <div className="space-y-5">
            <MirrorPanel picture={picture} onChat={onChat} onChanged={resource.refresh} />
            <div className="grid gap-5 lg:grid-cols-3">
              <SectionCard className="lg:col-span-2" title={text.heatmapTitle} description={text.heatmapIntro} icon={LayoutGrid} tone="blue">
                <CoverageHeatmap coverage={picture.coverage} selected={filter} onSelect={selectArea} />
              </SectionCard>
              <SectionCard title={text.certaintyTitle} icon={TrendingUp} tone="sky">
                <CertaintyChart ratings={picture.ratings} />
              </SectionCard>
            </div>
            <div className="grid gap-5 md:grid-cols-2">
              <SectionCard title={text.interestsTitle} icon={areaIcon("interests")} tone="rose">
                <ChipCloud items={picture.sections?.interests || []} tone="rose" />
              </SectionCard>
              <SectionCard title={text.strengthsTitle} icon={areaIcon("strengths")} tone="amber">
                <ChipCloud items={[...picture.personal.self, ...skills]} tone="amber" />
              </SectionCard>
            </div>
            <SectionCard title={text.peopleTitle} icon={Users} tone="teal">
              <PeopleMap people={picture.personal.world.people || []} showPrivate={showPrivate} initials={initials} />
            </SectionCard>
            <div className="grid gap-5 lg:grid-cols-3">
              <SectionCard className="lg:col-span-2" title={text.educationTitle} icon={GraduationCap} tone="violet">
                <EducationTimeline cards={datedEducation} />
              </SectionCard>
              <SectionCard title={text.stillWants} description={text.stillWantsIntro} icon={MessageCircle} tone="blue" variant="dashed">
                {missing.length ? (
                  <div className="flex flex-wrap gap-2">
                    {missing.map(([key, label]) => {
                      const Icon = areaIcon(key);
                      const tone = areaTone(key);
                      return (
                        <button key={key} onClick={() => onChat(label)}
                          className={cn("inline-flex min-h-11 items-center gap-2 rounded-full px-4 text-left text-sm font-semibold transition-transform hover:-translate-y-0.5", toneClass[tone].soft, toneClass[tone].ink)}>
                          <Icon aria-hidden className="size-4 shrink-0" />
                          {label}{picture.coverage[key]?.item_count ? ` · ${copy.partialArea}` : ""}
                        </button>
                      );
                    })}
                  </div>
                ) : <p className="text-sm text-muted-foreground">{copy.empty}</p>}
              </SectionCard>
            </div>
            <p className="flex items-start gap-2 text-xs text-muted-foreground"><ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-success" />{text.privacyNote}</p>
          </div>
        )}
      </div>
    </div>
  );
}
