"use client";
import { useState } from "react";
import { MessageCircle, Plus } from "lucide-react";
import { workspaceApi } from "@/lib/api";
import { vaultError, type JsonSchema, type VaultCatalogType, type VaultChoice, type VaultStoryCard } from "@/lib/vault";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import copy from "./copy.json";
import { fill, text } from "./profile-parts";
import { ChoiceSelect, EntryBadge, codeLabel, fieldClass, fieldLabel } from "./profile-details";

type Field = {
  key: string; // "" when the whole value is one field
  label: string;
  input: "text" | "number" | "boolean" | "choice" | "list";
  choices?: VaultChoice[];
  required: boolean;
};

/** The form for one catalog type, read from its schema: text, number,
 * yes/no, a choice (catalog labels first, else the schema's enum) or a list
 * typed with commas. Nested objects stay with PAI's conversation. Required
 * fields come first. */
export function formFields(type: VaultCatalogType): Field[] {
  const field = (key: string, schema: JsonSchema, required: boolean, label: string): Field | null => {
    const kind = Array.isArray(schema.type) ? schema.type[0] : schema.type;
    const choices = type.choices[key] || (schema.enum ? schema.enum.map((code) => ({ code: String(code), label: codeLabel(String(code)) })) : undefined);
    if (choices) return { key, label, input: "choice", choices, required };
    if (kind === "boolean") return { key, label, input: "boolean", required };
    if (kind === "number" || kind === "integer") return { key, label, input: "number", required };
    if (kind === "array") return { key, label, input: "list", required };
    if (kind === "string" || !kind) return { key, label, input: "text", required };
    return null;
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
    <form onSubmit={submit} aria-label={fill(text.storyAddLabel, { label: type.label })} className="mt-3 space-y-3 border-t pt-3">
      {fields.map((f) => {
        const label = f.required || fields.length === 1 ? f.label : fill(text.optional, { label: f.label });
        if (f.input === "choice")
          return <ChoiceSelect key={f.key} label={label} value={String(draft[f.key] || "")} choices={f.choices!} required={f.required} onChange={(code) => set(f.key, code)} />;
        if (f.input === "boolean")
          return (
            <label key={f.key} className="flex min-h-11 items-center gap-2 text-sm">
              <input type="checkbox" className="size-5 accent-[var(--brand)]" checked={draft[f.key] === true} onChange={(e) => set(f.key, e.target.checked)} />
              {f.label}
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

const round = "flex size-9 shrink-0 items-center justify-center rounded-full border transition-colors hover:border-primary hover:text-primary";

/** One story card from the Vault: its entries with a compact badge, the
 * progress bar, "Talk about this" and an Add form from the catalog. */
export function StoryCard({ card, type, onChat, onOpen, onSaved }: {
  card: VaultStoryCard;
  type: VaultCatalogType | null;
  onChat: (topic?: string) => void;
  onOpen: (entryId: string) => void;
  onSaved: () => void;
}) {
  const [adding, setAdding] = useState(false);
  const canAdd = !!type && formFields(type).length > 0;
  const count = card.entries.length;
  return (
    <article className="flex flex-col rounded-2xl border bg-card p-5 shadow-soft">
      <div className="flex items-start justify-between gap-3 border-b pb-3">
        <h3 className="text-base font-bold leading-snug">{card.label}</h3>
        <div className="flex shrink-0 gap-2">
          {canAdd && (
            <button type="button" onClick={() => setAdding((open) => !open)} aria-expanded={adding}
              aria-label={fill(text.storyAddLabel, { label: card.label })} className={round}>
              <Plus aria-hidden className="size-4" />
            </button>
          )}
          <button type="button" onClick={() => onChat(fill(text.storyDraft, { area: card.label.toLowerCase() }))}
            aria-label={`${text.storyTalk}: ${card.label}`} className={round}>
            <MessageCircle aria-hidden className="size-4" />
          </button>
        </div>
      </div>
      {card.next_step && !count && <p className="mt-3 text-sm text-muted-foreground">{card.next_step}</p>}
      {count > 0 && (
        <ul className="mt-3 space-y-1 text-sm">
          {card.entries.map((entry) => (
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
      {adding && type && <AddEntryForm type={type} onCancel={() => setAdding(false)} onDone={() => { setAdding(false); onSaved(); }} />}
      <div className="mt-auto pt-4">
        <div className="h-1.5 overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(count, 3) / 3 * 100}%` }} />
        </div>
        <p className="mt-1.5 text-xs font-semibold text-muted-foreground">{fill(text.sharedCount, { count })}</p>
      </div>
    </article>
  );
}
