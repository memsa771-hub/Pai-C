/** Words for the Roadmap page. The engine sends copy keys with values; the
 * templates mirror backend policy/roadmap.json (a test keeps them in step). */
import type { CopyItem, EducationLine, FieldCard, RouteGroup, RouteNeed, RouteStep, RouteTime } from "@/lib/roadmap";
import { formatDate } from "@/lib/i18n/format";
import { DEFAULT_LOCALE } from "@/lib/i18n/locales";
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

/** A route step's words: its copy key with its values. Steps saved before
 * steps had keys carry the copy key itself as `key`. */
export const stepLabel = (step: Pick<RouteStep, "key" | "label_key" | "values">) =>
  step.label_key ? render({ ...(step.values || {}), key: step.label_key }) : render(step as unknown as CopyItem);

/** Whether the student may tick a step themselves: applying, a step that is
 * not yet done (the claim stays "stated"), or one they ticked before. The
 * degree itself is never ticked. */
export const tickable = (step: RouteStep) =>
  step.kind === "apply" || step.key === "apply" || !!step.manual_done || (step.status === "not" && step.kind !== "degree");

export const doneCount = (steps: RouteStep[]) => steps.filter((s) => s.status === "done").length;
export const stepsDoneText = (steps: RouteStep[] | undefined) =>
  steps?.length ? fill(t.route.progress, { done: doneCount(steps), total: steps.length }) : "";

/** "May 2027" for a calendar month. */
export const whenText = (month: number, year: number) =>
  formatDate(`${year}-${String(month).padStart(2, "0")}-01`, DEFAULT_LOCALE, { month: "long", year: "numeric", timeZone: "UTC" });

/** When a step happens: its first dated event, or "Date not confirmed" when
 * the calendar has no month for it; empty when the step waits on nothing. */
export function stepWhen(step: RouteStep, time: RouteTime | null | undefined): string {
  const row = time?.basis.find((b) => b.step === step.key);
  if (!row) return "";
  return row.month && row.year ? whenText(row.month, row.year) : t.templates.date_not_confirmed;
}

const lowerFirst = (text: string) => text.charAt(0).toLowerCase() + text.slice(1);

/** "About 11 months to entry · about 4.9 years to finish", and a note on how
 * sure the dates are ("Dates not confirmed; …" when uncertain). */
export function timeText(time: RouteTime | null | undefined): { main: string; note: string } {
  if (!time) return { main: "", note: "" };
  const main = time.to_entry_months == null ? t.templates.date_not_confirmed
    : [fill(t.templates.time_to_entry, { months: time.to_entry_months }),
      time.to_finish_years == null ? "" : lowerFirst(fill(t.templates.time_to_finish, { years: time.to_finish_years }))]
      .filter(Boolean).join(" · ");
  const note = time.confidence === "uncertain" ? t.templates.time_uncertain
    : fill(t.time.confidence, { confidence: t.confidence[time.confidence] });
  return { main, note };
}

/** The card's short time line: "About 11 months to entry" or "Date not confirmed". */
export const cardTime = (time: RouteTime | null | undefined) =>
  !time ? "" : time.to_entry_months == null ? t.templates.date_not_confirmed : fill(t.templates.time_to_entry, { months: time.to_entry_months });

/** The Compare cell: "About 11 months", with "Not confirmed" when the dates are uncertain. */
export const compareTime = (time: RouteTime | null | undefined) =>
  !time || time.to_entry_months == null ? t.time.notConfirmed
    : [fill(t.time.entryShort, { months: time.to_entry_months }), time.confidence === "uncertain" ? t.time.notConfirmed : ""]
      .filter(Boolean).join(" · ");

/** "Entry: September intake, September 2027". */
export const intakeText = (time: RouteTime | null | undefined) => {
  const intake = time?.next_intake;
  if (!intake) return "";
  const month = formatDate(`${intake.year}-${String(intake.start_month).padStart(2, "0")}-01`, DEFAULT_LOCALE,
    { month: "long", timeZone: "UTC" });
  return fill(t.time.intake, { label: intake.label, month, year: intake.year });
};
