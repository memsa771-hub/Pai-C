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
};

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
export function withChoiceLabels(value: unknown, type?: VaultCatalogType | null): unknown {
  const choices = type?.choices || {};
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
