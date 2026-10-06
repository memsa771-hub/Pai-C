import { expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { RoadmapCard } from './roadmap-card';
import type { Roadmap } from '@/lib/roadmaps';

const route: Roadmap = {
  id: 'route-1', journey_id: 'journey-1', goal_id: 'goal-1', origin: 'stated_goal',
  title: 'Computer Science route', route: { country: 'Germany', level: 'Bachelor', why_suggested: 'Your stated direction' },
  fit_level: 'partial', fit_dimensions: { academics: { level: 'fixable', reason: 'A prerequisite is missing', source: 'https://example.edu/rules' } },
  gaps: [{ field: 'education', status: 'fixable', reason: 'A prerequisite is missing', source_url: 'https://example.edu/rules', remediation: { action: 'Complete a foundation year' } }],
  steps: [], total_cost: null, time_to_start: null, risks: ['Requirement awaiting review'],
  sources: [{ url: 'https://example.edu/rules', checked_at: '2026-10-06' }],
  generation_status: 'ready', stale_reason: null, execution_run_id: 'run-1', version: 1,
  favorite: false, exploring: false, dismissed_at: null, chosen_at: null, focused_at: null,
  created_at: '2026-10-06T00:00:00Z', updated_at: '2026-10-06T00:00:00Z',
};

it('renders sourced fit and explicit decision actions for a presented route', () => {
  const html = renderToStaticMarkup(<RoadmapCard roadmap={route} busy={false} onAction={() => {}} />);
  expect(html).toContain('Your goal');
  expect(html).toContain('A prerequisite is missing');
  expect(html).toContain('https://example.edu/rules');
  expect(html).toContain('Choose route');
  expect(html).toContain('Not yet');
});

it('shows why a stale fit needs checking again while preserving favorite state', () => {
  const html = renderToStaticMarkup(<RoadmapCard roadmap={{ ...route, generation_status: 'stale', stale_reason: 'Student profile changed: education', favorite: true }} busy={false} onAction={() => {}} />);
  expect(html).toContain('Student profile changed: education');
  expect(html).not.toContain('Choose route');
  expect(html).toContain('Remove favorite');
});
