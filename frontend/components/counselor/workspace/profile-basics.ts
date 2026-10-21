import type { ProfileCard } from "@/lib/counselor-workspace";
import layout from "./profile-layout.json";

type Basic = (typeof layout.basics)[number] & { alsoMetBy?: { record: string; field: string }[] };

/** Basics the student has not given yet. A basic is met by its own key, or by
 * a record field named in `alsoMetBy` (a board result such as FSc marks sits
 * on the education record, not on a test attempt). */
export function missingBasics(cards: ProfileCard[]): Basic[] {
  const has = (key: string) => cards.some((c) => c.key === key || c.key.startsWith(key + "."));
  const filled = (record: string, field: string) => cards.some((c) => {
    if (c.key !== record || !c.value || typeof c.value !== "object") return false;
    const value = (c.value as Record<string, unknown>)[field];
    return value !== null && value !== undefined && value !== "" && !(typeof value === "object" && !Object.keys(value as object).length);
  });
  return (layout.basics as Basic[]).filter((b) => !has(b.key) && !(b.alsoMetBy || []).some((m) => filled(m.record, m.field)));
}

/** Results the student has only said, not shown. Merit numbers count only
 * once shown or confirmed, so these invite a result card. */
export function resultsToProve(cards: ProfileCard[]): ProfileCard[] {
  return cards.filter((c) => c.evidence_level === "stated" && layout.proofRecords.some((p) => {
    if (c.key !== p.record || !c.value || typeof c.value !== "object") return false;
    const value = (c.value as Record<string, unknown>)[p.field];
    return value !== null && value !== undefined && value !== "" && !(typeof value === "object" && !Object.keys(value as object).length);
  }));
}
