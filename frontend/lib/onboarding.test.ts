import { describe, expect, it } from 'vitest';
import {
  FIELD_LAYOUT, chipKey, clearedDependents, levelRedirect, normWording, visibleOnboardingAnswers, visibleOnboardingFields,
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

describe('Other text that names a level', () => {
  const level = spec('level', { choices: ['intermediate', 'bachelor'], allowOther: true,
    redirects: { 'f sc': 'intermediate', fsc: 'intermediate', bs: 'bachelor', intermediate: 'intermediate' } });

  it('normalises the way the catalog does', () => {
    expect(normWording('  F.Sc. ')).toBe('f sc');
    expect(normWording('Bachelor’s')).toBe('bachelor s');
  });

  it('names the chip for a typed level, never for the chip itself or real Other text', () => {
    expect(levelRedirect(level, 'F.Sc')).toBe('intermediate');
    expect(levelRedirect(level, 'BS')).toBe('bachelor');
    expect(levelRedirect(level, 'Intermediate')).toBe('intermediate');
    expect(levelRedirect(level, 'intermediate')).toBeNull();
    expect(levelRedirect(level, 'Cambridge Pre-U')).toBeNull();
  });

  it('names the chip for a level typed with its group or field', () => {
    expect(levelRedirect(level, 'FSc Pre-Engineering')).toBe('intermediate');
    expect(levelRedirect(level, 'BS Computer Science')).toBe('bachelor');
    expect(levelRedirect(level, 'Pre-Engineering')).toBeNull();
  });

  it('treats every Other keystroke as the same chip', () => {
    const fields = [level];
    expect(chipKey(fields, 'level', '')).toBe(chipKey(fields, 'level', 'My own'));
    expect(chipKey(fields, 'level', 'intermediate')).not.toBe(chipKey(fields, 'level', 'bachelor'));
  });
});

// req: R-47
describe('marks questions', () => {
  const MARKS: OnboardingFieldSpec[] = [
    ...EDUCATION,
    spec('marksObtained', { isNumber: true, depends_on: { field: 'status', values: ['completed'] } }),
    spec('marksObtained', { isNumber: true, required: false, depends_on: { field: 'status', values: ['current'] } }),
    spec('entryTest', { required: false, choices: ['mdcat'] }),
  ];

  it('does not require a required follow-up its condition hides', () => {
    const shown = visibleOnboardingFields(MARKS, { level: 'intermediate', status: 'current' });
    expect(shown.filter((f) => f.name === 'marksObtained').map((f) => f.required)).toEqual([false]);
    const done = visibleOnboardingFields(MARKS, { level: 'intermediate', status: 'completed' });
    expect(done.filter((f) => f.name === 'marksObtained').map((f) => f.required)).toEqual([true]);
  });

  it('leaves an optional question left empty out of the answers', () => {
    expect(visibleOnboardingAnswers(MARKS, { level: 'other', status: 'current' }))
      .toEqual({ level: 'other', status: 'current' });
    expect(visibleOnboardingAnswers(MARKS, { level: 'other', status: 'current', entryTest: 'mdcat' }))
      .toEqual({ level: 'other', status: 'current', entryTest: 'mdcat' });
  });
});

// req: R-80
describe('Part-I and Part-II marks questions', () => {
  const inter = { field: 'level', values: ['intermediate'] };
  const done = { field: 'status', values: ['completed'], and: inter };
  const yearTwo = { field: 'year', values: ['year_2'], and: { field: 'status', values: ['current'], and: inter } };
  const PARTS: OnboardingFieldSpec[] = [
    ...EDUCATION,
    spec('part1MarksObtained', { isNumber: true, required: false, atMost: 'part1MarksTotal', depends_on: done }),
    spec('part1MarksTotal', { isNumber: true, required: false, depends_on: done }),
    spec('part1MarksObtained', { isNumber: true, required: false, atMost: 'part1MarksTotal', depends_on: yearTwo }),
    spec('part1MarksTotal', { isNumber: true, required: false, depends_on: yearTwo }),
    spec('part2MarksObtained', { isNumber: true, required: false, atMost: 'part2MarksTotal', depends_on: done }),
    spec('part2MarksTotal', { isNumber: true, required: false, depends_on: done }),
  ];
  const names = (answers: Record<string, string>) => visibleOnboardingFields(PARTS, answers)
    .map((f) => f.name).filter((n) => n.startsWith('part'));

  it('asks both parts of a completed intermediate student', () => {
    expect(names({ level: 'intermediate', status: 'completed' }))
      .toEqual(['part1MarksObtained', 'part1MarksTotal', 'part2MarksObtained', 'part2MarksTotal']);
  });

  it('asks only Part-I of a second-year student, and nothing in year one or at another level', () => {
    expect(names({ level: 'intermediate', status: 'current', year: 'year_2' }))
      .toEqual(['part1MarksObtained', 'part1MarksTotal']);
    expect(names({ level: 'intermediate', status: 'current', year: 'year_1' })).toEqual([]);
    expect(names({ level: 'matric', status: 'completed' })).toEqual([]);
  });

  it('leaves unanswered optional parts out of the answers', () => {
    const base = { level: 'intermediate', status: 'completed', group: 'pre_medical', year: '2025' };
    expect(visibleOnboardingAnswers(PARTS, base)).toEqual(base);
    expect(visibleOnboardingAnswers(PARTS, { ...base, part1MarksObtained: '400', part1MarksTotal: '550' }))
      .toEqual({ ...base, part1MarksObtained: '400', part1MarksTotal: '550' });
  });
});
