import type { VaultEntry } from "@/lib/vault";
import layout from "./profile-layout.json";

type Basic = (typeof layout.basics)[number] & { alsoMetBy?: { record: string; field: string }[] };

const present = (value: unknown) =>
  value !== null && value !== undefined && value !== "" && !(typeof value === "object" && !Object.keys(value as object).length);
const field = (entry: VaultEntry, name: string) =>
  entry.value && typeof entry.value === "object" ? (entry.value as Record<string, unknown>)[name] : undefined;

/** Basics the student has not given yet. A basic is met by a Vault entry of
 * its type, or by a record field named in `alsoMetBy` (a board result such as
 * FSc marks sits on the education record, not on a test attempt). */
export function missingBasics(entries: VaultEntry[]): Basic[] {
  const has = (type: string) => entries.some((e) => e.type === type || e.type.startsWith(type + "."));
  const filled = (record: string, name: string) => entries.some((e) => e.type === record && present(field(e, name)));
  return (layout.basics as Basic[]).filter((b) => !has(b.key) && !(b.alsoMetBy || []).some((m) => filled(m.record, m.field)));
}

/** Results the student has only said (or PAI only guessed), not shown. Merit
 * numbers count only once shown or confirmed, so these invite a result card. */
export function resultsToProve(entries: VaultEntry[]): VaultEntry[] {
  return entries.filter((e) => (e.level === "stated" || e.level === "inferred")
    && layout.proofRecords.some((p) => e.type === p.record && present(field(e, p.field))));
}
