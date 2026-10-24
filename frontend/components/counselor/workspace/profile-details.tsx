"use client";
import { useState } from "react";
import { FileText, RefreshCw } from "lucide-react";
import { workspaceApi } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace-context";
import { badgeLevel, vaultError, withChoiceLabels, type VaultCatalogType, type VaultChoice, type VaultDocument, type VaultEntry } from "@/lib/vault";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EvidenceBadge, vaultBadgeLabel } from "@/components/pai";
import { human, shortDate } from "./resource";
import { fill, text } from "./profile-parts";
import copy from "./copy.json";
import layout from "./profile-layout.json";
import labels from "@/lib/evidence-labels.json";

/** A field's label: the shared label list first, else its own words
 * ("target_date" -> "Target date"), so no schema key is ever shown raw. */
export function fieldLabel(key: string) {
  const known = labels.labels[key as keyof typeof labels.labels];
  if (known) return known;
  const words = key.split(".").at(-1)!.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** A choice code's words when no catalog label exists ("on_campus" -> "On campus"). */
export const codeLabel = (code: string) => labels.values[code as keyof typeof labels.values] || fieldLabel(code);

export const fieldClass = "mt-1 h-11 w-full rounded-xl";
const selectClass = "mt-1 h-11 w-full rounded-xl border border-input bg-card px-3 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** A select of catalog choices, styled like the page's inputs. */
export function ChoiceSelect({ label, value, choices, onChange, required }: {
  label: string; value: string; choices: VaultChoice[]; onChange: (code: string) => void; required?: boolean;
}) {
  return (
    <label className="block text-sm font-medium">
      {label}
      <select className={selectClass} value={value} required={required} onChange={(e) => onChange(e.target.value)}>
        <option value="">{text.choose}</option>
        {choices.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
      </select>
    </label>
  );
}

/** Edits a stored value in its own shape. Fields with catalog choices are a
 * select, so a correction stays a valid code. */
export function ValueEditor({ value, onChange, label, choices = {}, path = "" }: {
  value: unknown; onChange: (value: unknown) => void; label: string;
  choices?: Record<string, VaultChoice[]>; path?: string;
}) {
  if (value && typeof value === "object")
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        {Object.entries(value).filter(([key]) => !labels.hidden.includes(key)).map(([key, item]) => (
          <ValueEditor key={key} label={Array.isArray(value) ? label : fieldLabel(key)} value={item} choices={choices}
            path={Array.isArray(value) ? path : path ? `${path}.${key}` : key}
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
  if (choices[path])
    return <ChoiceSelect label={label} value={value === null || value === undefined ? "" : String(value)} choices={choices[path]} onChange={onChange} />;
  return (
    <label className="block text-sm font-medium">
      {label}
      <Input className={fieldClass} value={value === null || value === undefined ? "" : String(value)} type={typeof value === "number" ? "number" : "text"}
        onChange={(e) => onChange(typeof value === "number" ? Number(e.target.value) : e.target.value)} />
    </label>
  );
}

/** "Qualification: FSc" rows for an object value; the plain value otherwise. */
export function ReadableValue({ value }: { value: unknown }) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const rows = Object.entries(value as Record<string, unknown>).filter(([key, v]) => !labels.hidden.includes(key) && human(v));
    return (
      <dl className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
        {rows.map(([key, v]) => (
          <div key={key} className="min-w-0">
            <dt className="text-xs text-muted-foreground">{fieldLabel(key)}</dt>
            <dd className="break-words text-sm font-medium">{human(v)}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return <p className="break-words text-sm font-semibold">{human(value)}</p>;
}

/** Opens the Documents view on one file (the shell's own navigation). */
export function useOpenDocument(onNavigate?: (view: string) => void) {
  const { setSelectedFileId } = useWorkspace();
  if (!onNavigate) return null;
  return (fileId: string) => { setSelectedFileId(fileId); onNavigate("files"); };
}

/** A small file icon that opens the document behind a value. */
export function DocumentLink({ document, open, className }: { document: VaultDocument; open: (fileId: string) => void; className?: string }) {
  return (
    <button type="button" onClick={() => open(document.file_id)} aria-label={fill(text.openDocument, { filename: document.filename })}
      title={fill(text.openDocument, { filename: document.filename })}
      className={`flex size-9 shrink-0 items-center justify-center rounded-full border text-muted-foreground transition-colors hover:border-primary hover:text-primary ${className || ""}`}>
      <FileText aria-hidden className="size-4" />
    </button>
  );
}

/** The quiet re-check marker for a value whose freshness window has passed. */
export function StaleMarker() {
  return (
    <p className="mt-1.5 flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
      <RefreshCw aria-hidden className="size-3.5" />{text.staleMarker}
    </p>
  );
}

/** The badge for an entry: its level, or "In question" while a card asks. */
export function EntryBadge({ entry, compact }: { entry: VaultEntry; compact?: boolean }) {
  const level = badgeLevel(entry);
  return <EvidenceBadge compact={compact} level={level} label={vaultBadgeLabel(level)} />;
}

/** The entry with its choice codes read as words. */
export const readable = (entry: VaultEntry, type?: VaultCatalogType | null) => withChoiceLabels(entry.value, type);

function sourceLine(entry: VaultEntry) {
  const date = shortDate(entry.level === "confirmed" ? entry.confirmed_at || entry.observed_at : entry.observed_at);
  const template = { confirmed: text.sourceConfirmed, shown: text.sourceShown, inferred: text.sourceGuess, stated: text.sourceSaid }[entry.level];
  return date ? fill(template, { date }) : entry.level === "inferred" ? text.sourceGuessNoDate : text.sourceNoDate;
}

/** Where one Vault entry came from, what disagrees with it, and the
 * student's Confirm / Edit / Remove through the Vault API. A refused write
 * shows the backend's own sentence (for example the household-income rule). */
export function FactReview({ entry, type, onSaved, openDocument }: {
  entry: VaultEntry;
  type: VaultCatalogType | null;
  onSaved: () => void;
  openDocument: ((fileId: string) => void) | null;
}) {
  const [editing, setEditing] = useState(false),
    [removing, setRemoving] = useState(false),
    [value, setValue] = useState(entry.value),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null);
  // A file's own record changes in Documents; adding and editing are for catalog types only.
  const fromFile = layout.fileRecordTypes.includes(entry.type);
  const canEdit = !!type && !fromFile;
  async function run(action: "confirm" | "edit" | "remove") {
    setBusy(true);
    setError(null);
    try {
      if (action === "confirm") await workspaceApi.confirmVaultEntry(entry.kind, entry.id);
      else if (action === "edit") await workspaceApi.editVaultEntry(entry.kind, entry.id, value);
      else await workspaceApi.removeVaultEntry(entry.kind, entry.id);
      setEditing(false);
      setRemoving(false);
      onSaved();
    } catch (failure) {
      setError(vaultError(failure) || text.saveFailed);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-3">
      <div className="space-y-2 rounded-xl bg-muted/60 px-4 py-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-semibold text-muted-foreground">{sourceLine(entry)}</p>
          <EntryBadge entry={entry} />
        </div>
        {entry.document && openDocument && (
          <button type="button" onClick={() => openDocument(entry.document!.file_id)}
            className="flex items-center gap-1.5 text-xs font-semibold text-primary hover:underline">
            <FileText aria-hidden className="size-3.5" />{fill(text.openDocument, { filename: entry.document.filename })}
          </button>
        )}
        {entry.stale && <p className="text-xs text-muted-foreground"><span className="font-semibold">{text.staleMarker}.</span> {text.staleHelp}</p>}
        {/* The student's raw words stay backend evidence: the page shows only the stored English value. */}
      </div>
      {entry.disagreements.length > 0 && (
        <ul className="space-y-2 rounded-xl border border-warning/40 px-4 py-3 text-sm">
          {entry.disagreements.map((d, i) => (
            <li key={i} className="flex items-center justify-between gap-3">
              <span>{fill(d.document ? text.disagreeDocument : text.disagreeOther, { display: d.display })}</span>
              {d.document && openDocument && <DocumentLink document={d.document} open={openDocument} />}
            </li>
          ))}
        </ul>
      )}
      {fromFile && <p className="text-sm text-muted-foreground">{text.fileRecordNote}</p>}
      {editing && <ValueEditor value={value} onChange={setValue} label={entry.label} choices={type?.choices} />}
      {removing && (
        <div className="rounded-xl border border-danger/30 bg-danger-soft p-4 text-sm text-danger-ink">
          <p>{copy.removeHelp}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="tap" variant="destructive" disabled={busy} onClick={() => run("remove")}>{copy.removeConfirm}</Button>
            <Button size="tap" variant="ghost" onClick={() => setRemoving(false)}>{copy.cancel}</Button>
          </div>
        </div>
      )}
      {error && <p role="alert" className="text-sm font-medium text-danger-ink">{error}</p>}
      {!removing && !fromFile && (
        <div className="flex flex-wrap gap-2">
          {editing ? (
            <>
              <Button size="tap" disabled={busy || JSON.stringify(value) === JSON.stringify(entry.value)} onClick={() => run("edit")}>{copy.save}</Button>
              <Button size="tap" variant="ghost" onClick={() => { setEditing(false); setValue(entry.value); }}>{copy.cancel}</Button>
            </>
          ) : (
            <>
              <Button size="tap" disabled={busy} onClick={() => run("confirm")}>{copy.confirm}</Button>
              {canEdit && <Button size="tap" variant="outline" onClick={() => setEditing(true)}>{copy.edit}</Button>}
              <Button size="tap" variant="ghost" onClick={() => setRemoving(true)}>{copy.remove}</Button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
