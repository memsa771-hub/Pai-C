/** The Mirror state card (GET /v1/counselor/summary → {type: "mirror_state", card}),
 * computed from the Vault on every read by backend app/pai_c/mirror/engine.py.
 * Entry text is English display text, never the student's own words. */
import type { VaultLevel } from "./vault";
import type { EducationLine } from "./roadmap";

/** An entry as the Mirror names it: `fact:<type>`, `<record type>:<id>` or `item:<id>`. */
export type MirrorEntry = {
  id: string;
  text: string;
  evidence: VaultLevel;
  source_label: string;
  observed_at: string | null;
};

export type MirrorTension = { a_id: string; b_id: string; note_key: string };

export type MirrorArea = {
  key: string;
  label: string;
  /** 0 unknown, 1 stated only, 2 shown or confirmed, 3 two or more shown or confirmed. */
  level: 0 | 1 | 2 | 3;
  entries: MirrorEntry[];
  /** Per-subject marks of the current education record, when it has them. */
  bars?: { label: string; percent: number }[];
  tension: MirrorTension[];
};

export type MirrorUnknown = { area: string; label: string; question_key: string | null; priority: number };

export type MirrorText = { sentences: string[]; version: string; written_at: string | null };

export type MirrorHeader = {
  name: string | null;
  education_line: (EducationLine & { text: string }) | null;
};

export type MirrorCard = {
  version: string;
  header: MirrorHeader;
  areas: MirrorArea[];
  unknowns: MirrorUnknown[];
  text: MirrorText | null;
  ready: boolean;
};

/** What the workspace read and the chat card carry: the card without its areas. */
export type MirrorPicture = Pick<MirrorCard, "header" | "unknowns" | "text" | "ready" | "version">;

export type MirrorState = { type: "mirror_state"; card: MirrorCard };

/** The most recent date on the card: the newest entry or the text. */
export function updatedAt(card: MirrorCard): string | null {
  const dates = [card.text?.written_at, ...card.areas.flatMap((a) => a.entries.map((e) => e.observed_at))]
    .filter((d): d is string => !!d);
  return dates.sort().at(-1) ?? null;
}
