/**
 * First-run onboarding — the student's opening statement about themselves.
 *
 * This replaces the OpenAgents "connect your first agent" flow, which had no
 * meaning in PAI: there is nothing to connect. PAI Counselor is the only
 * conversational agent and PAI Operator is deliberately invisible. What a new
 * PAI account actually lacks is not an agent, it is any knowledge of the
 * student — so that is what we ask for.
 *
 * Every answer becomes a canonical Vault fact through the same
 * candidate -> reconciler path PAI's own extraction uses. There is no
 * onboarding store and no second copy of a student's identity.
 */

/** One answer: text or a chip code, or a list of codes for a multi-select. */
export type OnboardingAnswer = string | string[];

/** Answers by field name. Names match `ONBOARDING_FIELDS` in the backend,
 * which is the source; several follow-ups may share one name. */
export type OnboardingAnswers = Record<string, OnboardingAnswer | undefined>;

/** When a follow-up is shown: the named answer is one of `values` (any answer
 * when absent), and the `and` condition holds too. */
export interface OnboardingCondition {
  field: string;
  values?: string[];
  and?: OnboardingCondition;
}

/** One question, as the backend declares it. */
export interface OnboardingFieldSpec {
  name: string;
  /** The canonical Vault key the answer is stored under. */
  fieldKey: string;
  required: boolean;
  /** Non-empty for the chips. */
  choices: string[];
  isDate: boolean;
  allowOther?: boolean;
  /** Which of the three steps asks it. */
  step?: number;
  /** Pre-selected value when nothing is known (data-driven, e.g. a country). */
  default?: string | null;
  /** Suggested values; unlike `choices` they do not restrict the answer. */
  options?: string[];
  /** Shown only while this holds (education follow-ups). */
  depends_on?: OnboardingCondition | null;
  /** Several chips may be picked; the answer is a list. */
  multi?: boolean;
  /** A four-digit year typed by the student. */
  isYear?: boolean;
  /** A long chip list with a search box (study fields). */
  searchable?: boolean;
  /** Copy key when questions share a name (the year asked three ways). */
  labelKey?: string | null;
  /** Catalog wording for chips the UI has no copy of its own for. */
  labels?: Record<string, string>;
  /** Normalised wordings of a level -> the chip that asks it ("fsc" -> intermediate). */
  redirects?: Record<string, string>;
}

export interface OnboardingState {
  /** Whether the form is still owed by this account. */
  required: boolean;
  completedAt: string | null;
  fields: OnboardingFieldSpec[];
  /** Anything already known — a returning or pre-existing student. */
  prefill: OnboardingAnswers;
}

export interface OnboardingResult {
  /** Vault keys that actually moved. */
  saved: string[];
  /** Vault key -> why it did not, so nothing is reported as saved falsely. */
  rejected: Record<string, string>;
  completed: boolean;
}

function holds(condition: OnboardingCondition | null | undefined, answers: OnboardingAnswers): boolean {
  if (!condition) return true;
  const answer = answers[condition.field];
  const shown = condition.values ? typeof answer === 'string' && condition.values.includes(answer) : filledAnswer(answer);
  return shown && holds(condition.and, answers);
}

/** Whether an answer counts as given. */
export function filledAnswer(answer: OnboardingAnswer | undefined): boolean {
  return Array.isArray(answer) ? answer.length > 0 : !!(answer || '').trim();
}

/** The questions shown for these answers, in order. A follow-up needs the
 * answer it depends on to be shown itself, and a shared name resolves to the
 * first question whose condition holds. */
export function visibleOnboardingFields(
  fields: OnboardingFieldSpec[], answers: OnboardingAnswers,
): OnboardingFieldSpec[] {
  const shown: OnboardingFieldSpec[] = [];
  const names = new Set<string>();
  const visibleAnswers: OnboardingAnswers = {};
  for (const field of fields) {
    if (names.has(field.name) || !holds(field.depends_on, visibleAnswers)) continue;
    shown.push(field);
    names.add(field.name);
    visibleAnswers[field.name] = answers[field.name];
  }
  return shown;
}

/** Include only fields rendered to the student, even when the prefill has
 * older answers or a generated account handle. */
export function visibleOnboardingAnswers(
  fields: OnboardingFieldSpec[], answers: OnboardingAnswers,
): OnboardingAnswers {
  return Object.fromEntries(visibleOnboardingFields(fields, answers)
    .map((field) => [field.name, answers[field.name] || (field.multi ? [] : '')]));
}

/** Text the way the catalog compares wordings: no accents, no punctuation,
 * single spaces, lower case (app/memory/catalog `norm`). */
export function normWording(text: string): string {
  return text.normalize('NFKD').replace(/\p{M}/gu, '').replace(/[^\p{L}\p{N}_\s]/gu, ' ')
    .replace(/\s+/g, ' ').trim().toLowerCase();
}

/** The chip an Other answer really names ("FSc" -> intermediate), or null. */
export function levelRedirect(field: OnboardingFieldSpec, answer: OnboardingAnswer | undefined): string | null {
  if (!field.redirects || typeof answer !== 'string' || !answer.trim() || field.choices.includes(answer)) return null;
  return field.redirects[normWording(answer)] ?? null;
}

/** Which chip an answer is: its code, or one key for anything typed in Other. */
export function chipKey(fields: OnboardingFieldSpec[], name: string, answer: OnboardingAnswer | undefined): string {
  if (typeof answer !== 'string') return JSON.stringify(answer ?? null);
  return fields.some((f) => f.name === name && f.choices.includes(answer)) ? answer : '\u0000other';
}

/** Answers to clear when `name` changes: everything that depended on it,
 * directly or through another follow-up. */
export function clearedDependents(fields: OnboardingFieldSpec[], name: string): string[] {
  const reads = (condition: OnboardingCondition | null | undefined, target: string): boolean =>
    !!condition && (condition.field === target || reads(condition.and, target));
  const cleared = new Set<string>();
  const walk = (target: string) => {
    for (const field of fields) {
      if (field.name !== name && !cleared.has(field.name) && reads(field.depends_on, target)) {
        cleared.add(field.name);
        walk(field.name);
      }
    }
  };
  walk(name);
  return [...cleared];
}

/**
 * The order the form asks in, and how each field is rendered.
 *
 * The backend owns WHICH fields exist; this owns how they look. Anything the
 * backend sends that is missing here still renders, as a plain text box — a
 * new question is never invisible just because the UI has not caught up.
 */
export const FIELD_LAYOUT: Record<string, { half?: boolean; placeholder?: string }> = {
  fullName: {},
  preferredName: {},
  statusCategory: {},
  nationality: { half: true },
  gender: { half: true },
  dateOfBirth: { half: true },
  currentCountry: { half: true },
  currentCity: { half: true },
};
