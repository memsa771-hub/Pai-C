/** Words for the Roadmap page. The engine sends copy keys with values; the
 * templates mirror backend policy/roadmap.json (a test keeps them in step). */
import type { CopyItem, EducationLine, FieldCard, RouteGroup, RouteNeed } from "@/lib/roadmap";
import copy from "./copy.json";

const t = copy.roadmap;

export const fill = (template: string, values: Record<string, unknown>) =>
  Object.entries(values).reduce((out, [key, value]) => out.replaceAll(`{${key}}`, value == null ? "" : String(value)), template);

/** A group list as a Matric student chooses it: "FSc Pre-Engineering or ICS". */
export const groupsText = (groups: unknown) =>
  (Array.isArray(groups) ? (groups as RouteGroup[]) : []).map((g) => g.route_label || g.label).join(t.groupJoiner);

/** One reason or step: its template with the values filled in. */
export function render(item: CopyItem): string {
  const template = (t.templates as Record<string, string>)[item.key];
  if (!template) return "";
  const { key: _key, ...values } = item;
  return fill(template, { ...values, groups: groupsText(values.groups) }).replace(/\s+/g, " ").trim();
}

/** The checklist item a need becomes (mirrors decisions.py _need_step). */
export function needItem(need: RouteNeed): CopyItem {
  const d = need.detail || {};
  if (need.kind === "marks") return { key: "step_marks", min: d.min, have: d.have };
  if (need.kind === "bridge") return { key: "step_bridge", text: d.text };
  if (need.kind === "check") return { key: "step_check", note: d.note };
  return Array.isArray(d.groups) && d.groups.length ? { key: "step_group", groups: d.groups } : { key: "step_any_group" };
}

/** A short label for the Compare table, never the rule's long text. */
export function shortNeed(need: RouteNeed | undefined): string {
  const s = t.compareStep;
  if (!need) return s.none;
  const d = need.detail || {};
  if (need.kind === "marks") return fill(s.marks, { min: d.min });
  if (need.kind === "bridge") return s.bridge;
  if (need.kind === "check") return s.check;
  return Array.isArray(d.groups) && d.groups.length ? fill(s.group, { groups: groupsText(d.groups) }) : s.any_group;
}

/** "From FSc Pre-Engineering, 78%" from the Vault standing. */
export function educationText(line: EducationLine | null): string {
  if (!line) return "";
  const e = t.educationLine;
  const groups = line.groups.map((g) => g.label).join(e.groups_joiner);
  const template = line.percent == null ? e.without_percent : e.with_percent;
  return fill(template, { level: line.level_label, groups, percent: line.percent }).replace(/\s+,/g, ",").replace(/\s+/g, " ").trim();
}

/** "Needs 60% · you 78%", "Needs 60%", or nothing when the rule has no floor. */
export function marksText(card: FieldCard): string {
  const { min_percent: min, student_percent: have } = card.verdict;
  if (min == null) return "";
  return have == null ? fill(t.facts.needs, { min }) : fill(t.facts.needsYou, { min, have });
}

export const testsText = (card: FieldCard) => card.verdict.tests.map((test) => test.name).join(", ");
export const yearsText = (years: number | null) => (years == null ? "" : fill(t.facts.years, { n: years }));
/** A rule that is not official gets the calm "Check with the university" note. */
export const uncertain = (card: FieldCard) =>
  card.verdict.confidence != null && card.verdict.confidence !== t.officialConfidence;
