/** The student's Vault as `/v1/vault` returns it (backend/app/memory/vault_view.py).
 * Values and display text are English; the view never carries the student's
 * original words, so nothing here can show them. */

export type VaultLevel = 'inferred' | 'stated' | 'shown' | 'confirmed';
export type VaultKind = 'fact' | 'record' | 'item';

export type VaultDocument = { file_id: string; page: number | null; filename: string };

export type VaultDisagreement = {
  value: unknown;
  display: string;
  source: string | null;
  document: VaultDocument | null;
};

export type VaultEntry = {
  kind: VaultKind;
  type: string;
  id: string;
  value: unknown;
  display: string;
  label: string;
  level: VaultLevel;
  badge: string;
  source: string | null;
  source_language?: string | null;
  document: VaultDocument | null;
  observed_at: string | null;
  confirmed_at: string | null;
  fresh_until: string | null;
  stale: boolean;
  in_question: boolean;
  disagreements: VaultDisagreement[];
  /** A record's level as the backend reads it, even when its title is a
   * wording ("BS Computer Science"); only for types with level-aware lists. */
  record_level?: string | null;
};

export type VaultSection = { label: string; entries: VaultEntry[] };

export type VaultStoryCard = {
  type: string;
  label: string;
  entries: VaultEntry[];
  rich: boolean;
  next_step: string | null;
};

export type VaultAnswer = 'keep_current' | 'accept_proposed' | 'both_true' | 'provide_new';

/** Where one side of a conflict came from: the same ladder and badge words as
 * entries, the day it was said or read, and the file behind it. Never words. */
export type VaultConflictSource = {
  level: VaultLevel;
  badge: string;
  said_on: string | null;
  document: VaultDocument | null;
};

export type VaultConflict = {
  id: string;
  kind: 'fact' | 'record' | 'item' | 'document_owner' | 'other';
  type: string | null;
  entry_id: string | null;
  summary: string;
  question: string;
  current: unknown;
  proposed: unknown;
  current_display: string;
  proposed_display: string;
  /** Only the answers this card offers; they differ per card. */
  answers: VaultAnswer[];
  /** The saved entry's source, and the new answer's (null when unknown). */
  current_source: VaultConflictSource | null;
  proposed_source: VaultConflictSource | null;
  created_at: string | null;
};

/** The open conflict an entry's "In question" badge points at: the card about
 * that entry, else the card about its type. */
export function conflictFor(conflicts: VaultConflict[], entry: Pick<VaultEntry, 'id' | 'type' | 'in_question'>): VaultConflict | null {
  if (!entry.in_question) return null;
  return conflicts.find((c) => c.entry_id === entry.id) || conflicts.find((c) => c.type === entry.type) || null;
}

export type VaultView = {
  details: Record<string, VaultSection>;
  story: VaultStoryCard[];
  conflicts: VaultConflict[];
  stale: VaultEntry[];
};

export type JsonSchema = {
  type?: string | string[];
  enum?: unknown[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  minimum?: number;
  maximum?: number;
};

export type VaultChoice = { code: string; label: string };

export type VaultCatalogType = {
  key: string;
  label: string;
  storage: VaultKind;
  shown_on: 'details' | 'story';
  section: string | null;
  inputs: string[];
  schema: JsonSchema | null;
  /** Field path ("" for the whole value, "details.board" for nested) -> choices. */
  choices: Record<string, VaultChoice[]>;
  /** A field whose list depends on the record's level: path -> level code ->
   * choices (a Bachelor's field_of_study is a study field). */
  choice_by_level?: Record<string, Record<string, VaultChoice[]>>;
};

export type VaultCatalog = { types: VaultCatalogType[] };

export type VaultWriteResult = {
  saved: boolean;
  kind: VaultKind;
  type: string;
  id?: string | null;
  /** Not refused: the value now waits on a "Please check" card. */
  in_question?: boolean;
};

/** Every entry the view holds, Details and story alike. */
export function vaultEntries(view: VaultView): VaultEntry[] {
  return [
    ...Object.values(view.details).flatMap((section) => section.entries),
    ...view.story.flatMap((card) => card.entries),
  ];
}

/** An entry named as the Mirror, coverage and paths name it (backend
 * memory/vault_view.py entry_ref): `fact:<type>`, `<record type>:<id>`, `item:<id>`. */
export function entryRef(entry: Pick<VaultEntry, 'kind' | 'type' | 'id'>): string {
  if (entry.kind === 'fact') return `fact:${entry.type}`;
  return entry.kind === 'item' ? `item:${entry.id}` : `${entry.type}:${entry.id}`;
}

/** The badge an entry shows: an open question overrides its evidence level. */
export function badgeLevel(entry: Pick<VaultEntry, 'level' | 'in_question'>): VaultLevel | 'question' {
  return entry.in_question ? 'question' : entry.level;
}

/** The backend's own sentence for a refused write (a 4xx carries a message
 * written for the student, such as the household-income rule), else null. */
export function vaultError(error: unknown): string | null {
  const match = error instanceof Error ? /^API 4\d\d: ([\s\S]*)$/.exec(error.message) : null;
  if (!match) return null;
  try {
    const message = (JSON.parse(match[1]) as { message?: unknown }).message;
    return typeof message === 'string' && message.trim() ? message : null;
  } catch {
    return null;
  }
}

/** A value with its choice codes replaced by the catalog's labels, so the
 * page reads "FSc", never "fsc". Paths follow the catalog ("" or "a.b"). */
const qualificationOf = (value: unknown) =>
  value && typeof value === 'object' ? (value as Record<string, unknown>).qualification_name : undefined;

/** The choices for one value: the type's lists, with a level-aware field
 * read against the value's own level, so a Bachelor's field offers study
 * fields and never intermediate groups. The level is the qualification's code
 * or label; an older wording ("BS") uses the level the backend read for the
 * stored entry while the draft still holds that wording. */
export function choicesFor(type: VaultCatalogType | null | undefined, value: unknown,
  stored?: VaultEntry | null): Record<string, VaultChoice[]> {
  const choices = type?.choices || {};
  const byLevel = type?.choice_by_level;
  const raw = qualificationOf(value);
  if (!byLevel || typeof raw !== 'string') return choices;
  const wording = raw.trim().toLowerCase();
  const known = (choices.qualification_name || []).find((c) => c.code === wording || c.label.toLowerCase() === wording)?.code;
  const level = known ?? (stored?.record_level && qualificationOf(stored.value) === raw ? stored.record_level : wording);
  const lists = Object.fromEntries(Object.entries(byLevel)
    .filter(([, levels]) => levels[level]).map(([path, levels]) => [path, levels[level]]));
  return { ...choices, ...lists };
}

/** When the draft's level changes, every level-aware field whose code is not
 * in the new level's list is cleared (""), so switching FSc to Bachelor's
 * never keeps Pre-Medical as a Bachelor's field. Other edits leave it be. */
export function withoutOffListChoices(type: VaultCatalogType | null | undefined, value: unknown,
  previous: unknown, stored?: VaultEntry | null): unknown {
  if (!type?.choice_by_level || !value || typeof value !== 'object' || Array.isArray(value)) return value;
  if (qualificationOf(value) === qualificationOf(previous)) return value;
  const choices = choicesFor(type, value, stored);
  const next = { ...(value as Record<string, unknown>) };
  for (const path of Object.keys(type.choice_by_level)) {
    const current = next[path];
    if (typeof current === 'string' && current && choices[path] && !choices[path].some((c) => c.code === current))
      next[path] = '';
  }
  return next;
}

export function withChoiceLabels(value: unknown, type?: VaultCatalogType | null): unknown {
  const choices = choicesFor(type, value);
  if (!Object.keys(choices).length) return value;
  const walk = (node: unknown, path: string): unknown => {
    if (typeof node === 'string' && choices[path]) return choices[path].find((c) => c.code === node)?.label ?? node;
    if (Array.isArray(node)) return node.map((item) => walk(item, path));
    if (node && typeof node === 'object')
      return Object.fromEntries(Object.entries(node as Record<string, unknown>)
        .map(([key, item]) => [key, walk(item, path ? `${path}.${key}` : key)]));
    return node;
  };
  return walk(value, '');
}
