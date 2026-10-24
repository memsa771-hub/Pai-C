"use client";
import { useState } from "react";
import { MessageCircle, Plus } from "lucide-react";
import { workspaceApi } from "@/lib/api";
import { vaultError, type JsonSchema, type VaultCatalogType, type VaultChoice, type VaultEntry, type VaultStoryCard } from "@/lib/vault";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toneClass } from "@/components/pai";
import { cn } from "@/lib/utils";
import copy from "./copy.json";
import layout from "./profile-layout.json";
import { areaIcon, areaTone, fill, text } from "./profile-parts";
import { ChoiceSelect, EntryBadge, codeLabel, fieldClass, fieldLabel } from "./profile-details";

type Field = {
  key: string; // "" when the whole value is one field
  label: string;
  /** "chat": a nested object the form cannot hold; PAI asks about it. */
  input: "text" | "number" | "boolean" | "choice" | "list" | "chat";
  choices?: VaultChoice[];
  required: boolean;
};

/** The form for one catalog type, read from its schema: text, number,
 * yes/no, a choice (catalog labels first, else the schema's enum) or a list
 * typed with commas. A nested object stays with PAI's conversation: dropped
 * when optional, named in a note when required. Required fields come first. */
export function formFields(type: VaultCatalogType): Field[] {
  const field = (key: string, schema: JsonSchema, required: boolean, label: string): Field | null => {
    const kind = Array.isArray(schema.type) ? schema.type[0] : schema.type;
    const choices = type.choices[key] || (schema.enum ? schema.enum.map((code) => ({ code: String(code), label: codeLabel(String(code)) })) : undefined);
    if (choices) return { key, label, input: "choice", choices, required };
    if (kind === "boolean") return { key, label, input: "boolean", required };
    if (kind === "number" || kind === "integer") return { key, label, input: "number", required };
    if (kind === "array") return { key, label, input: "list", required };
    if (kind === "string" || !kind) return { key, label, input: "text", required };
    return required ? { key, label, input: "chat", required } : null;
  };
  const schema = type.schema;
  if (!schema) return [];
  if (!schema.properties) {
    const one = field("", schema, true, type.label);
    return one ? [one] : [];
  }
  const required = new Set(schema.required || []);
  return Object.entries(schema.properties)
    .map(([key, child]) => field(key, child, required.has(key), fieldLabel(key)))
    .filter((f): f is Field => f !== null)
    .sort((a, b) => Number(b.required) - Number(a.required));
}

/** A type the student can add from the page: it has at least one field the form holds. */
const addable = (type: VaultCatalogType) => formFields(type).some((f) => f.input !== "chat");

type Draft = Record<string, string | boolean>;

/** What the form sends: empty fields left out, numbers as numbers, lists split. */
function valueOf(fields: Field[], draft: Draft): { value: unknown; complete: boolean } {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const raw = draft[f.key];
    let value: unknown;
    if (f.input === "boolean") value = raw === true ? true : f.required ? false : undefined;
    else if (typeof raw === "string" && raw.trim()) {
      value = f.input === "number" ? Number(raw) : f.input === "list" ? raw.split(",").map((s) => s.trim()).filter(Boolean) : raw.trim();
    }
    if (value !== undefined) out[f.key] = value;
  }
  // A required field only PAI can ask about keeps the form from sending a value the backend would refuse.
  const complete = fields.every((f) => !f.required || out[f.key] !== undefined);
  return { value: fields.length === 1 && fields[0].key === "" ? out[""] : out, complete };
}

/** A small form that adds one story entry through the Vault API, built with
 * the same inputs and buttons as the entry review. */
function AddEntryForm({ type, onDone, onCancel }: { type: VaultCatalogType; onDone: () => void; onCancel: () => void }) {
  const fields = formFields(type);
  const [draft, setDraft] = useState<Draft>({}),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null);
  const { value, complete } = valueOf(fields, draft);
  const set = (key: string, next: string | boolean) => setDraft((d) => ({ ...d, [key]: next }));
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await workspaceApi.addVaultEntry(type.key, value);
      onDone();
    } catch (failure) {
      setError(vaultError(failure) || text.saveFailed);
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} aria-label={fill(text.storyAddLabel, { label: type.label })} className="space-y-3">
      {fields.map((f) => {
        const label = f.required || fields.length === 1 ? f.label : fill(text.optional, { label: f.label });
        if (f.input === "chat")
          return <p key={f.key} className="text-sm text-muted-foreground">{fill(text.requiredInChat, { label: f.label.toLowerCase() })}</p>;
        if (f.input === "choice")
          return <ChoiceSelect key={f.key} label={label} value={String(draft[f.key] || "")} choices={f.choices!} required={f.required} onChange={(code) => set(f.key, code)} />;
        if (f.input === "boolean")
          return (
            <label key={f.key} className="flex min-h-11 items-center gap-2 text-sm">
              <input type="checkbox" className="size-5 accent-[var(--brand)]" checked={draft[f.key] === true} onChange={(e) => set(f.key, e.target.checked)} />
              {label}
            </label>
          );
        return (
          <label key={f.key} className="block text-sm font-medium">
            {label}
            <Input className={fieldClass} type={f.input === "number" ? "number" : "text"} required={f.required}
              value={String(draft[f.key] || "")} onChange={(e) => set(f.key, e.target.value)} />
            {f.input === "list" && <span className="mt-1 block text-xs text-muted-foreground">{text.listHint}</span>}
          </label>
        );
      })}
      {error && <p role="alert" className="text-sm font-medium text-danger-ink">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <Button size="tap" type="submit" disabled={busy || !complete}>{text.storyAddSave}</Button>
        <Button size="tap" type="button" variant="ghost" onClick={onCancel}>{copy.cancel}</Button>
      </div>
    </form>
  );
}

/** The story area each Vault story type belongs to (`storyAreas` in data);
 * a type the data does not name yet still shows, in the fallback area. */
export function areaOf(type: string): string {
  const areas = layout.storyAreas as Record<string, string[]>;
  return Object.keys(areas).find((area) => areas[area].includes(type)) || layout.storyFallbackArea;
}

const round = "flex size-11 shrink-0 items-center justify-center rounded-full border transition-colors hover:border-primary hover:text-primary";

/** One of the seven story areas, filled from the Vault: every entry of the
 * area's types with a compact badge, the progress bar, "Talk about this",
 * and Add, which first asks which kind of entry when the area has several. */
export function StoryArea({ area, cards, types, onChat, onOpen, onSaved }: {
  area: string;
  cards: VaultStoryCard[];
  types: VaultCatalogType[];
  onChat: (topic?: string) => void;
  onOpen: (entryId: string) => void;
  onSaved: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const choices = types.filter(addable);
  const [picked, setPicked] = useState("");
  const chosen = choices.length === 1 ? choices[0] : choices.find((t) => t.key === picked) || null;
  const label = copy.areas[area as keyof typeof copy.areas] || area;
  const Icon = areaIcon(area), tone = toneClass[areaTone(area)];
  const entries: VaultEntry[] = cards.flatMap((card) => card.entries);
  const count = entries.length;
  const close = () => { setAdding(false); setPicked(""); };
  return (
    <article className="flex flex-col rounded-2xl border bg-card p-5 shadow-soft">
      <div className="flex items-start justify-between gap-3 border-b pb-3">
        <div className="flex min-w-0 items-center gap-3">
          <span aria-hidden className={cn("flex size-9 shrink-0 items-center justify-center rounded-full", tone.soft, tone.ink)}><Icon className="size-4" /></span>
          <h3 className="text-base font-bold leading-snug">{label}</h3>
        </div>
        <div className="flex shrink-0 gap-2">
          {choices.length > 0 && (
            <button type="button" onClick={() => (adding ? close() : setAdding(true))} aria-expanded={adding}
              aria-label={fill(text.storyAddLabel, { label })} className={round}>
              <Plus aria-hidden className="size-4" />
            </button>
          )}
          <button type="button" onClick={() => onChat(fill(text.storyDraft, { area: label.toLowerCase() }))}
            aria-label={fill(text.storyTalkLabel, { label })} className={round}>
            <MessageCircle aria-hidden className="size-4" />
          </button>
        </div>
      </div>
      <p className="mt-3 text-sm text-muted-foreground">{layout.story[area as keyof typeof layout.story]}</p>
      {count > 0 && (
        <ul className="mt-3 space-y-1 text-sm">
          {entries.map((entry) => (
            <li key={entry.id} className="min-w-0">
              <button type="button" onClick={() => onOpen(entry.id)} aria-haspopup="dialog"
                className="group -mx-2 flex min-h-11 w-[calc(100%+1rem)] items-center gap-2 rounded-xl px-2 text-left transition-colors hover:bg-muted/60">
                <span className="min-w-0 flex-1 break-words font-semibold group-hover:text-primary">{entry.display}</span>
                <EntryBadge entry={entry} compact />
              </button>
            </li>
          ))}
        </ul>
      )}
      {adding && (
        <div className="mt-3 space-y-3 border-t pt-3">
          {choices.length > 1 && (
            <ChoiceSelect label={text.storyAddType} value={picked} onChange={setPicked}
              choices={choices.map((t) => ({ code: t.key, label: t.label }))} />
          )}
          {chosen ? <AddEntryForm key={chosen.key} type={chosen} onCancel={close} onDone={() => { close(); onSaved(); }} />
            : <Button size="tap" type="button" variant="ghost" onClick={close}>{copy.cancel}</Button>}
        </div>
      )}
      <div className="mt-auto pt-4">
        <div className="h-1.5 overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(count, 3) / 3 * 100}%` }} />
        </div>
        <p className="mt-1.5 text-xs font-semibold text-muted-foreground">{fill(text.sharedCount, { count })}</p>
      </div>
    </article>
  );
}
