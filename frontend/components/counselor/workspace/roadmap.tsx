"use client";
/** The Roadmap page: which fields this student can get into from what PAI
 * knows, and how (spec ROADMAP_ENGINE_SPEC.md §1). The backend engine decides
 * every status from the Vault and the rules; this page only shows it and
 * records the student's own choice. */
import { useState } from "react";
import { ChevronDown, Columns2, Compass, Info, Map as MapIcon, PencilLine, X } from "lucide-react";
import { workspaceApi } from "@/lib/api";
import type { FieldCard, RoadmapStatus } from "@/lib/roadmap";
import { Button } from "@/components/ui/button";
import { EmptyState, StatChip } from "@/components/pai";
import { cn } from "@/lib/utils";
import { Heading, LoadState, useResource } from "./resource";
import { CompareDialog, FieldCardView, RouteSheet, STATUS_TONE, YourRoute } from "./roadmap-parts";
import { educationText, fill } from "./roadmap-text";
import copy from "./copy.json";

const t = copy.roadmap;
const load = () => workspaceApi.getRoadmapPage();
/** Shown open in this order; "not open" sits last, collapsed. */
const SHOWN: RoadmapStatus[] = ["open", "step", "unknown"];
const ORDER: RoadmapStatus[] = ["open", "step", "not_open", "unknown"];
const firstReason = (card: FieldCard) => card.verdict.reasons[0]?.key;

/** A group's title; inside the collapsed <summary> it is a span, since a
 * heading there loses its role in some screen readers. */
function GroupTitle({ id, status, count, as: Tag = "h2" }: { id?: string; status: RoadmapStatus; count: number; as?: "h2" | "span" }) {
  return (
    <Tag id={id} className="flex items-center gap-2.5 font-display text-lg leading-tight">
      {t.groups[status]}
      <span className="rounded-full bg-muted px-2 py-0.5 font-sans text-xs font-semibold tabular-nums text-muted-foreground">{count}</span>
    </Tag>
  );
}

export function Roadmap({ onNavigate, onChat, onChanged }: {
  onNavigate?: (view: string) => void;
  onChat?: (topic?: string) => void;
  /** After a choose, tick or withdraw, so the shell's journey stage follows. */
  onChanged?: () => void;
}) {
  const resource = useResource(load);
  const [picked, setPicked] = useState<string[]>([]),
    [sheet, setSheet] = useState<FieldCard | null>(null),
    [comparing, setComparing] = useState(false);
  const data = resource.data;
  const vault = (
    <Button size="tap" variant="soft" onClick={() => onNavigate?.("profile")}><PencilLine aria-hidden />{t.updateVault}</Button>
  );
  const header = <Heading title={t.title} description={educationText(data?.education_line ?? null) || t.intro}
    icon={MapIcon} tone="violet" action={data ? vault : undefined} />;
  if (!data || resource.error)
    return <>{header}<LoadState error={resource.error} busy={resource.busy} retry={resource.refresh} /></>;

  const fields = data.fields;
  const noEducation = !data.education_line || (fields.length > 0 && fields.every((c) => firstReason(c) === "needs_education"));
  const undergrad = fields.some((c) => c.verdict.reasons.some((r) => r.key === "undergrad_only"));
  const max = t.compareLimits.max, min = t.compareLimits.min;
  const pick = (id: string, on: boolean) =>
    setPicked((list) => (on ? (list.length < max && !list.includes(id) ? [...list, id] : list) : list.filter((x) => x !== id)));
  const choose = async (card: FieldCard) => {
    await workspaceApi.chooseRoute(card.field_key!);
    setSheet(null);
    await resource.refresh();
    onChanged?.();
  };
  const cardsOf = (status: RoadmapStatus) => fields.filter((c) => c.status === status);
  const grid = (cards: FieldCard[]) => (
    <div className="grid gap-3 md:grid-cols-2">
      {cards.map((card) => (
        <FieldCardView key={card.possibility_id} card={card} mine={!!card.field_key && card.field_key === data.chosen?.field_key} picked={picked.includes(card.possibility_id)}
          pickDisabled={picked.length >= max && !picked.includes(card.possibility_id)}
          onPick={(on) => pick(card.possibility_id, on)} onOpen={() => setSheet(card)} />
      ))}
    </div>
  );
  const notOpen = cardsOf("not_open");

  return (
    <>
      {header}
      {data.chosen && <YourRoute route={data.chosen} onWithdrawn={async () => { await resource.refresh(); onChanged?.(); }}
        onTicked={onChanged} onChat={onChat} />}
      {noEducation ? (
        <EmptyState icon={PencilLine} tone="violet" title={t.empty.educationTitle} description={t.empty.educationBody}
          action={<Button size="tap" onClick={() => onNavigate?.("profile")}>{t.empty.educationAction}</Button>} />
      ) : !fields.length ? (
        <EmptyState icon={Compass} tone="teal" title={t.empty.pathsTitle} description={t.empty.pathsBody}
          action={onNavigate && <Button size="tap" variant="soft" onClick={() => onNavigate("paths")}>{t.empty.pathsAction}</Button>} />
      ) : (
        <div className="space-y-8">
          <div>
            <div className="flex flex-wrap gap-2">
              {ORDER.filter((s) => data.counts[s]).map((s) => (
                <StatChip key={s} tone={STATUS_TONE[s]}>{fill(t.counts[s], { n: data.counts[s] })}</StatChip>
              ))}
            </div>
            {fields.length >= min && <p className="mt-3 flex items-center gap-1.5 text-[13px] text-muted-foreground"><Columns2 aria-hidden className="size-3.5" />{t.compareHint}</p>}
          </div>
          {undergrad && (
            <p className="flex items-start gap-2.5 rounded-2xl bg-info-soft px-4 py-3 text-sm text-info-ink">
              <Info aria-hidden className="mt-0.5 size-4 shrink-0" />{t.empty.undergrad}
            </p>
          )}
          {SHOWN.map((status) => {
            const cards = cardsOf(status);
            if (!cards.length) return null;
            return (
              <section key={status} aria-labelledby={`roadmap-${status}`} className="space-y-3">
                <GroupTitle id={`roadmap-${status}`} status={status} count={cards.length} />
                {grid(cards)}
              </section>
            );
          })}
          {notOpen.length > 0 && (
            <details className="group/details">
              <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden">
                <GroupTitle as="span" status="not_open" count={notOpen.length} />
                <ChevronDown aria-hidden className="size-5 text-muted-foreground transition-transform group-open/details:rotate-180" />
              </summary>
              <div className="mt-3">{grid(notOpen)}</div>
            </details>
          )}
        </div>
      )}

      {picked.length > 0 && (
        <div className="pointer-events-none sticky bottom-4 z-20 mt-8 flex justify-center">
          <div className="pointer-events-auto flex max-w-full items-center gap-1.5 rounded-full bg-card p-1.5 shadow-lift ring-1 ring-border">
            <Button size="tap-icon" variant="ghost" className="rounded-full" aria-label={t.compareClear} onClick={() => setPicked([])}>
              <X aria-hidden />
            </Button>
            <Button size="tap" disabled={picked.length < min} onClick={() => setComparing(true)} className={cn(picked.length < min && "opacity-70")}>
              <Columns2 aria-hidden />
              {picked.length < min ? fill(t.comparePickMore, { n: min - picked.length }) : fill(t.compareBar, { n: picked.length })}
            </Button>
          </div>
        </div>
      )}

      <RouteSheet card={sheet} line={data.education_line} chosen={data.chosen} checkedAt={data.rules_as_of} onClose={() => setSheet(null)} onChoose={choose} />
      <CompareDialog open={comparing} onOpenChange={setComparing}
        cards={picked.map((id) => fields.find((c) => c.possibility_id === id)).filter((c): c is FieldCard => !!c)} />
    </>
  );
}
