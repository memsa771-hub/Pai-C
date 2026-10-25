import { describe, expect, it } from 'vitest';
import {
  FIELD_LAYOUT, clearedDependents, visibleOnboardingAnswers, visibleOnboardingFields,
  type OnboardingFieldSpec,
} from './onboarding';

describe('generic onboarding layout', () => {
  it('does not suggest an identity or location using example answers', () => {
    for (const field of ['fullName', 'preferredName', 'nationality', 'currentCountry', 'currentCity']) {
      expect(FIELD_LAYOUT[field]).not.toHaveProperty('placeholder');
    }
  });
});

describe('visible onboarding answers', () => {
  it('does not submit the hidden generated username as a preferred name', () => {
    const fields = [
      { name: 'fullName' as const, fieldKey: 'identity.full_name', required: true, choices: [], isDate: false },
      { name: 'currentCity' as const, fieldKey: 'location.current_city', required: true, choices: [], isDate: false },
    ];
    expect(visibleOnboardingAnswers(fields, {
      fullName: 'Student Name', currentCity: 'Student City', preferredName: 'generated_handle',
    })).toEqual({ fullName: 'Student Name', currentCity: 'Student City' });
  });
});

const spec = (name: string, extra: Partial<OnboardingFieldSpec> = {}): OnboardingFieldSpec => ({
  name, fieldKey: 'education', required: true, choices: [], isDate: false, step: 2, ...extra,
});
const EDUCATION: OnboardingFieldSpec[] = [
  spec('level', { choices: ['matric', 'o_level', 'intermediate'], allowOther: true }),
  spec('group', { choices: ['science_biology', 'arts'], depends_on: { field: 'level', values: ['matric'] } }),
  spec('group', { choices: ['pre_engineering', 'pre_medical'], depends_on: { field: 'level', values: ['intermediate'] } }),
  spec('subjects', { choices: ['physics', 'biology'], multi: true, depends_on: { field: 'level', values: ['o_level'] } }),
  spec('status', { choices: ['current', 'completed'], depends_on: { field: 'level' } }),
  spec('year', { choices: ['year_1', 'year_2'], depends_on: { field: 'status', values: ['current'],
    and: { field: 'level', values: ['matric', 'o_level', 'intermediate'] } } }),
  spec('year', { isYear: true, depends_on: { field: 'status', values: ['completed'] } }),
];

describe('dependent education questions', () => {
  it('shows only the level until one is picked', () => {
    expect(visibleOnboardingFields(EDUCATION, {}).map((f) => f.name)).toEqual(['level']);
  });

  it('shows the group of the picked level, then status and the matching year', () => {
    const shown = visibleOnboardingFields(EDUCATION, { level: 'intermediate', status: 'current' });
    expect(shown.map((f) => f.name)).toEqual(['level', 'group', 'status', 'year']);
    expect(shown[1].choices).toEqual(['pre_engineering', 'pre_medical']);
    expect(shown[3].choices).toEqual(['year_1', 'year_2']);
    const done = visibleOnboardingFields(EDUCATION, { level: 'intermediate', status: 'completed' });
    expect(done[3].isYear).toBe(true);
  });

  it('asks no group for a level written in the student’s own words', () => {
    const shown = visibleOnboardingFields(EDUCATION, { level: 'My own system', status: 'current' });
    expect(shown.map((f) => f.name)).toEqual(['level', 'status']);
  });

  it('submits one answer per shown question, subjects as a list, nothing hidden', () => {
    expect(visibleOnboardingAnswers(EDUCATION, {
      level: 'o_level', group: 'arts', subjects: ['physics', 'biology'], status: 'completed', year: '2024',
    })).toEqual({ level: 'o_level', subjects: ['physics', 'biology'], status: 'completed', year: '2024' });
  });

  it('clears every answer that depended on a changed one', () => {
    expect(clearedDependents(EDUCATION, 'level').sort()).toEqual(['group', 'status', 'subjects', 'year']);
    expect(clearedDependents(EDUCATION, 'status')).toEqual(['year']);
    expect(clearedDependents(EDUCATION, 'year')).toEqual([]);
  });
});
