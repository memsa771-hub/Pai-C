"use client";
import { useId, useState } from "react";
import { ChevronDown, Lock, MessageCircle, X } from "lucide-react";
import { workspaceApi } from "@/lib/api";
import type { EvidenceItem, LivingPicture, ProfileCard } from "@/lib/counselor-workspace";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState, EvidenceBadge, SectionCard, StatChip, evidenceLevel } from "@/components/pai";
import { cn } from "@/lib/utils";
import { human, evidenceLabel, shortDate } from "./resource";
import { ICONS, areaIcon, areaTone, fill, kindLevel, text } from "./profile-parts";
import copy from "./copy.json";
import layout from "./profile-layout.json";
import labels from "@/lib/evidence-labels.json";

const matches = (key: string, patterns: string[]) =>
  patterns.some((p) => (p.endsWith(".") ? key.startsWith(p) : key === p || key.startsWith(p + ".")));
export const isSensitive = (key: string) => matches(key, layout.sensitive.keys);
export function groupOf(card: ProfileCard) {
  return layout.detailGroups.find((g) => g.keys.length && matches(card.key, g.keys)) || layout.detailGroups.at(-1)!;
}

function ValueEditor({ value, onChange, label }: { value: unknown; onChange: (value: unknown) => void; label: string }) {
  if (value && typeof value === "object")
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        {Object.entries(value).filter(([key]) => !labels.hidden.includes(key)).map(([key, item]) => (
          <ValueEditor key={key} label={evidenceLabel(key)} value={item}
            onChange={(next) => onChange(Array.isArray(value)
              ? value.map((v, i) => (String(i) === key ? next : v))
              : { ...value, [key]: next })} />
        ))}
      </div>
    );
  if (typeof value === "boolean")
    return (
      <label className="flex min-h-11 items-center gap-2 text-sm">
        <input type="checkbox" className="size-5 accent-[var(--brand)]" checked={value} onChange={(e) => onChange(e.target.checked)} />
        {label}
      </label>
    );
  return (
    <label className="block text-sm font-medium">
      {label}
      <Input className="mt-1 h-11 rounded-xl" value={value === null ? "" : String(value)} type={typeof value === "number" ? "number" : "text"}
        onChange={(e) => onChange(typeof value === "number" ? Number(e.target.value) : e.target.value)} />
    </label>
  );
}

/** "Qualification: FSc" rows for an object value; the plain value otherwise. */
function ReadableValue({ value }: { value: unknown }) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const rows = Object.entries(value as Record<string, unknown>).filter(([key, v]) => !labels.hidden.includes(key) && human(v));
    return (
      <dl className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
        {rows.map(([key, v]) => (
          <div key={key} className="min-w-0">
            <dt className="text-xs text-muted-foreground">{evidenceLabel(key)}</dt>
            <dd className="break-words text-sm font-medium">{human(v)}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return <p className="break-words text-sm font-semibold">{human(value)}</p>;
}

function sourceLine(card: ProfileCard) {
  const date = shortDate(card.updated_at);
  const template = card.evidence_level === "confirmed" ? text.sourceConfirmed
    : card.source?.file_id ? text.sourceShown : text.sourceSaid;
  return date ? fill(template, { date }) : text.sourceNoDate;
}

/** One Vault fact as a readable row. Tap for the source and the existing
 * Confirm / Edit / Remove review actions (exact digest, never a guess). */
export function FactRow({ card, onSaved, hidden = false }: { card: ProfileCard; onSaved: () => void; hidden?: boolean }) {
  const [open, setOpen] = useState(false),
    [editing, setEditing] = useState(false),
    [removing, setRemoving] = useState(false),
    [value, setValue] = useState(card.value),
    [note, setNote] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(false);
  const panel = useId();
  const label = evidenceLabel(card.key);
  async function review(action: "confirm" | "edit" | "remove") {
    setBusy(true);
    setError(false);
    try {
      await workspaceApi.reviewProfileCard(card, {
        submission_id: crypto.randomUUID(),
        action,
        expected_digest: card.digest,
        value: action === "edit" ? value : null,
        text: note,
      });
      setEditing(false);
      setRemoving(false);
      onSaved();
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }
  const quote = typeof card.source?.quote === "string" ? card.source.quote : "";
  return (
    <li className="border-b last:border-b-0">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} aria-controls={panel}
        className="flex min-h-14 w-full items-start gap-3 py-3 text-left">
        <span className="sr-only">{fill(text.expand, { label })}: </span>
        <div className="min-w-0 flex-1 sm:grid sm:grid-cols-[minmax(8rem,14rem)_1fr] sm:gap-4">
          <p className="text-sm text-muted-foreground">{label}</p>
          {hidden ? <p className="flex items-center gap-1.5 text-sm italic text-muted-foreground"><Lock aria-hidden className="size-3.5" />{text.sensitiveHidden}</p>
            : <div className="mt-0.5 sm:mt-0"><ReadableValue value={card.value} /></div>}
        </div>
        <EvidenceBadge level={evidenceLevel(card.evidence_level)} />
        <ChevronDown aria-hidden className={cn("mt-0.5 size-5 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      <div id={panel} hidden={!open} className="space-y-3 pb-4 sm:ps-[calc(14rem+1rem)]">
        <div className="rounded-xl bg-muted/60 px-4 py-3 text-sm">
          <p className="text-xs font-semibold text-muted-foreground">{sourceLine(card)}</p>
          {quote && !hidden && <p className="mt-1">“{quote}”</p>}
        </div>
        {editing && (
          <div className="space-y-3">
            <ValueEditor value={value} onChange={setValue} label={label} />
            <label className="block text-sm font-medium">{copy.explainEdit}
              <Textarea className="mt-1 rounded-xl" value={note} onChange={(e) => setNote(e.target.value)} />
            </label>
          </div>
        )}
        {removing && (
          <div className="rounded-xl border border-danger/30 bg-danger-soft p-4 text-sm text-danger-ink">
            <p>{copy.removeHelp}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="tap" variant="destructive" disabled={busy} onClick={() => review("remove")}>{copy.removeConfirm}</Button>
              <Button size="tap" variant="ghost" onClick={() => setRemoving(false)}>{copy.cancel}</Button>
            </div>
          </div>
        )}
        {error && <p role="alert" className="text-sm font-medium text-danger-ink">{copy.error}</p>}
        {!removing && (
          <div className="flex flex-wrap gap-2">
            {editing ? (
              <>
                <Button size="tap" disabled={busy || !note.trim()} onClick={() => review("edit")}>{copy.save}</Button>
                <Button size="tap" variant="ghost" onClick={() => setEditing(false)}>{copy.cancel}</Button>
              </>
            ) : (
              <>
                <Button size="tap" disabled={busy} onClick={() => review("confirm")}>{copy.confirm}</Button>
                <Button size="tap" variant="outline" onClick={() => setEditing(true)}>{copy.edit}</Button>
                <Button size="tap" variant="ghost" onClick={() => setRemoving(true)}>{copy.remove}</Button>
              </>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

const at = (data: unknown, path: string): EvidenceItem[] => {
  const value = path.split(".").reduce<unknown>((node, key) => (node && typeof node === "object" ? (node as Record<string, unknown>)[key] : undefined), data);
  return Array.isArray(value) ? value as EvidenceItem[] : [];
};

/** Read-only rows for what the student shared in conversation (not Vault
 * facts), so every area has a readable home. Changes go through PAI. */
function SharedGroup({ area, items, hidden, onChat }: { area: string; items: EvidenceItem[]; hidden: boolean; onChat: (topic?: string) => void }) {
  const label = copy.areas[area as keyof typeof copy.areas] || evidenceLabel(area);
  return (
    <SectionCard title={fill(text.sharedTitle, { area: label })} description={text.sharedNote} icon={areaIcon(area)} tone={areaTone(area)}
      action={<Button size="tap" variant="soft" onClick={() => onChat(label)}><MessageCircle aria-hidden />{text.tellPai}</Button>}>
      {!items.length ? <p className="text-sm text-muted-foreground">{text.areaEmpty}</p> : (
        <ul className="divide-y">
          {items.map((item, i) => {
            const value = human(item.value || [item.role, item.wish]);
            return (
              <li key={item.id || i} className="flex items-start gap-3 py-3">
                <div className="min-w-0 flex-1">
                  {hidden ? <p className="flex items-center gap-1.5 text-sm italic text-muted-foreground"><Lock aria-hidden className="size-3.5" />{text.sensitiveHidden}</p>
                    : <>
                      <p className="break-words text-sm font-semibold">{value}</p>
                      {item.evidence && <p className="mt-1 text-sm text-muted-foreground">“{item.evidence}”</p>}
                      {item.category && <p className="mt-1 text-xs text-muted-foreground">{copy.whoseWish}: {copy.wishSources[item.category as keyof typeof copy.wishSources] || copy.wishSources.other}</p>}
                    </>}
                </div>
                <EvidenceBadge level={kindLevel(item.kind)} />
              </li>
            );
          })}
        </ul>
      )}
    </SectionCard>
  );
}

export function DetailsView({ picture, cards, filter, onFilter, showPrivate, onSaved, onChat }: {
  picture: LivingPicture;
  cards: ProfileCard[];
  filter: string | null;
  onFilter: (area: string | null) => void;
  showPrivate: boolean;
  onSaved: () => void;
  onChat: (topic?: string) => void;
}) {
  const groups = layout.detailGroups
    .map((group) => ({ group, rows: cards.filter((card) => groupOf(card).id === group.id) }))
    .filter(({ group, rows }) => rows.length && (!filter || group.areas.includes(filter)));
  const shared = layout.sharedGroups.filter((g) => !filter || g.area === filter);
  const filterLabel = filter ? copy.areas[filter as keyof typeof copy.areas] : null;
  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">{text.detailsIntro}</p>
      {filterLabel && (
        <div className="flex flex-wrap items-center gap-2">
          <StatChip tone={areaTone(filter!)} icon={areaIcon(filter!)}>{fill(text.filterBy, { area: filterLabel })}</StatChip>
          <Button size="tap" variant="ghost" onClick={() => onFilter(null)}><X aria-hidden />{text.clearFilter}</Button>
        </div>
      )}
      {groups.map(({ group, rows }) => (
        <SectionCard key={group.id} title={group.title} icon={ICONS[group.icon]} tone={areaTone(group.areas[0] || "status")}>
          <ul>
            {rows.map((card) => <FactRow key={card.id} card={card} onSaved={onSaved} hidden={!showPrivate && isSensitive(card.key)} />)}
          </ul>
        </SectionCard>
      ))}
      {filter && !groups.length && !shared.length && (
        <EmptyState icon={areaIcon(filter)} tone={areaTone(filter)} title={filterLabel || ""} description={text.areaEmpty}
          action={<Button size="tap" onClick={() => onChat(filterLabel || undefined)}><MessageCircle aria-hidden />{text.tellPai}</Button>} />
      )}
      {shared.map(({ area, source }) => (
        <SharedGroup key={area} area={area} items={at(picture, source)} onChat={onChat}
          hidden={!showPrivate && layout.sensitive.areas.includes(area)} />
      ))}
    </div>
  );
}
