// @vitest-environment jsdom
import { expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { I18nProvider } from '@/lib/i18n';
import { RoadmapFit } from './roadmap-fit';
import type { Roadmap } from '@/lib/roadmaps';

it('renders student fit and sourced questions through translated labels', () => {
  const roadmap = { lane: 'stated_goal', why_for_you: 'Matches your practical experience',
    strengths_used: ['Building'], test_30_days: 'Complete a small project', gaps: [],
    missing_facts: [{field: 'eligibility'}, {field: 'gap.0.need'}],
    your_questions: [{ id: 'question', question: 'What is needed?', status: 'answered',
      answer: 'Completed study is required', source_url: 'https://official.example/route', label: 'verified' }],
  } as unknown as Roadmap;
  render(<I18nProvider><RoadmapFit roadmap={roadmap} /></I18nProvider>);
  expect(screen.getByText('Matches your practical experience')).toBeTruthy();
  expect(screen.getByText('Your questions')).toBeTruthy();
  expect(screen.getByText('Entry requirements')).toBeTruthy();
  expect(screen.getByText('Other supporting evidence')).toBeTruthy();
  expect(document.body.textContent).not.toContain('gap.0.need');
  expect(screen.getByRole('link').getAttribute('href')).toBe('https://official.example/route');
  expect(document.body.textContent).not.toContain('roadmapFit.');
});
