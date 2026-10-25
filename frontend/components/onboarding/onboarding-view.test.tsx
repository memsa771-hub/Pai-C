// @vitest-environment jsdom
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { I18nProvider } from '@/lib/i18n';
import type { OnboardingFieldSpec, OnboardingState } from '@/lib/onboarding';
import { OnboardingView } from './onboarding-view';

const api = vi.hoisted(() => ({ submit: vi.fn() }));
vi.mock('@/lib/api', () => ({ workspaceApi: { submitOnboarding: api.submit } }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() } }));

beforeAll(() => {
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as never;
});
afterEach(() => { cleanup(); api.submit.mockReset(); });

const spec = (name: string, extra: Partial<OnboardingFieldSpec> = {}): OnboardingFieldSpec => ({
  name, fieldKey: 'education', required: true, choices: [], isDate: false, step: 2, ...extra,
});
const notDegree = ['matric', 'o_level', 'intermediate', 'a_level', 'masters'];
// Shaped like GET /v1/vault/onboarding; step 2 alone, so the form opens on it.
const state: OnboardingState = {
  required: true, completedAt: null, prefill: {},
  fields: [
    spec('level', { choices: ['matric', 'o_level', 'intermediate', 'a_level', 'dae', 'bachelor', 'masters'], allowOther: true,
      redirects: { fsc: 'intermediate', inter: 'intermediate', intermediate: 'intermediate', bs: 'bachelor' } }),
    spec('group', { choices: ['science_biology', 'science_computer', 'arts'],
      labels: { science_biology: 'Science (Biology)', science_computer: 'Science (Computer)', arts: 'Arts' },
      depends_on: { field: 'level', values: ['matric'] } }),
    spec('group', { choices: ['pre_engineering', 'pre_medical', 'ics', 'icom', 'fa_humanities'],
      depends_on: { field: 'level', values: ['intermediate'] } }),
    spec('subjects', { choices: ['mathematics', 'physics', 'biology'], multi: true,
      labels: { mathematics: 'Mathematics', physics: 'Physics', biology: 'Biology' },
      depends_on: { field: 'level', values: ['o_level'] } }),
    spec('status', { choices: ['current', 'completed'], depends_on: { field: 'level' } }),
    spec('field', { choices: ['electrical_engineering', 'computer_science'], searchable: true,
      labels: { electrical_engineering: 'Electrical Engineering', computer_science: 'Computer Science' },
      depends_on: { field: 'level', values: ['bachelor'] } }),
    spec('year', { choices: ['year_1', 'year_2'], labelKey: 'currentYear',
      depends_on: { field: 'status', values: ['current'], and: { field: 'level', values: notDegree } } }),
    spec('year', { isYear: true, labelKey: 'graduationYear', depends_on: { field: 'status', values: ['completed'] } }),
  ],
};

const view = (s: OnboardingState = state) =>
  render(<I18nProvider><OnboardingView state={s} onDone={() => {}} /></I18nProvider>);
const chip = (name: string) => screen.getByRole('button', { name });

it('picking Intermediate reveals the group chips', () => {
  view();
  expect(screen.queryByRole('button', { name: 'FSc Pre-Medical' })).toBeNull();
  fireEvent.click(chip('Intermediate'));
  for (const name of ['FSc Pre-Engineering', 'FSc Pre-Medical', 'ICS', 'I.Com', 'FA']) expect(chip(name)).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Arts' })).toBeNull();
});

it('picking O-level reveals subject chips, then status and year', () => {
  view();
  fireEvent.click(chip('O-level'));
  fireEvent.click(chip('Physics'));
  fireEvent.click(chip('Biology'));
  expect(chip('Physics').getAttribute('aria-pressed')).toBe('true');
  expect(chip('Biology').getAttribute('aria-pressed')).toBe('true');
  expect(screen.queryByRole('button', { name: '2nd year' })).toBeNull();
  fireEvent.click(chip('Studying now'));
  expect(chip('2nd year')).toBeTruthy();
  fireEvent.click(chip('Completed'));
  expect(screen.queryByRole('button', { name: '2nd year' })).toBeNull();
  expect(screen.getByLabelText('Year completed')).toBeTruthy();
});

it('needs the group before continuing', async () => {
  view();
  fireEvent.click(chip('Intermediate'));
  fireEvent.click(chip('Studying now'));
  fireEvent.click(chip('1st year'));
  fireEvent.click(screen.getByRole('button', { name: 'Start with PAI' }));
  expect(await screen.findByText('Please fill this in.')).toBeTruthy();
  expect(api.submit).not.toHaveBeenCalled();
});

it('submits one answer per shown question, subjects as a list', async () => {
  api.submit.mockResolvedValue({ saved: ['education'], rejected: {}, completed: true });
  view();
  fireEvent.click(chip('Intermediate'));
  fireEvent.click(chip('FSc Pre-Medical'));
  // Changing the level clears the group picked for the old one.
  fireEvent.click(chip('O-level'));
  fireEvent.click(chip('Mathematics'));
  fireEvent.click(chip('Physics'));
  fireEvent.click(chip('Completed'));
  fireEvent.change(screen.getByLabelText('Year completed'), { target: { value: '2024' } });
  fireEvent.click(screen.getByRole('button', { name: 'Start with PAI' }));
  await waitFor(() => expect(api.submit).toHaveBeenCalledTimes(1));
  expect(api.submit.mock.calls[0][0]).toEqual({
    level: 'o_level', subjects: ['mathematics', 'physics'], status: 'completed', year: '2024',
  });
});

it('a legacy FSc prefill opens on Intermediate with the group still to pick', () => {
  view({ ...state, prefill: { level: 'intermediate' } });
  expect(chip('Intermediate').getAttribute('aria-pressed')).toBe('true');
  expect(chip('FSc Pre-Medical').getAttribute('aria-pressed')).toBe('false');
});

// -- Review round 1 ------------------------------------------------------------

it('Other text that names a level points to its chip, beside the Other box', async () => {
  view();
  fireEvent.click(chip('Other'));
  fireEvent.change(screen.getByPlaceholderText('Type it in your own words'), { target: { value: 'FSc' } });
  fireEvent.click(chip('Studying now'));
  fireEvent.click(screen.getByRole('button', { name: 'Start with PAI' }));
  expect(await screen.findByText('Choose Intermediate above')).toBeTruthy();
  expect(api.submit).not.toHaveBeenCalled();
});

it('typing in Other keeps the status already picked', () => {
  view();
  fireEvent.click(chip('Other'));
  const box = screen.getByPlaceholderText('Type it in your own words');
  fireEvent.change(box, { target: { value: 'My' } });
  fireEvent.click(chip('Studying now'));
  fireEvent.change(box, { target: { value: 'My own system' } });
  expect(chip('Studying now').getAttribute('aria-pressed')).toBe('true');
});

it('the field search has its own label, wraps long titles and takes focus when nothing matches', async () => {
  view();
  fireEvent.click(chip("Bachelor's"));
  const search = screen.getByLabelText('Search fields');
  expect(chip('Electrical Engineering').className).toContain('whitespace-normal');
  fireEvent.change(search, { target: { value: 'zzz' } });
  fireEvent.click(chip('Studying now'));
  fireEvent.click(screen.getByRole('button', { name: 'Start with PAI' }));
  await screen.findByText('Please fill this in.');
  expect(document.activeElement).toBe(search);
});
