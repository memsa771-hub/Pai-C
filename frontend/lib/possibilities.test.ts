// req: R-47
import { expect, it } from 'vitest';
import { latestPathsChangeMessageId, newestPathsMessageId } from './possibilities';

it('finds the last message with a non-empty paths_found', () => {
  expect(newestPathsMessageId([
    { id: '1', metadata: { paths_found: ['a'] } },
    { id: '2', metadata: { paths_found: [] } },
    { id: '3', metadata: {} },
  ])).toBe('1');
  expect(newestPathsMessageId([{ id: '1', metadata: { paths_found: ['a'] } }, { id: '2', metadata: { paths_found: ['b'] } }])).toBe('2');
});
it('is null with no paths card', () => {
  expect(newestPathsMessageId([])).toBeNull();
});
it('finds the last paths-excluded notice, ignoring other messages', () => {
  expect(latestPathsChangeMessageId([
    { id: '1', metadata: { paths_excluded_job_id: 'j1' } },
    { id: '2', metadata: { paths_excluded_job_id: 'j2' } },
    { id: '3', metadata: {} },
  ])).toBe('2');
  expect(latestPathsChangeMessageId([{ id: '1', metadata: null }])).toBeUndefined();
});
