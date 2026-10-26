import { it, expect } from 'vitest';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';

// Guard: the chat-linked roadmap UI stays removed (ROADMAP_ENGINE_SPEC.md §4).
// Routes live only on the Roadmap page (components/counselor/workspace/roadmap*).
const ROOT = resolve(__dirname, '..');
const SKIP = new Set(['node_modules', '.next', 'out', 'dist', 'coverage', 'test-results']);

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    if (SKIP.has(name)) return [];
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(ts|tsx|cjs|js)$/.test(name) && !name.endsWith('.d.ts') ? [path] : [];
  });
}

const files = ['app', 'components', 'hooks', 'lib', 'tests']
  .map((dir) => join(ROOT, dir)).filter(existsSync).flatMap(sources)
  .filter((path) => !path.endsWith('roadmap-removed.test.ts'));

it('no module imports the old roadmap components, types or chat comparison', () => {
  const banned = /from\s+['"][^'"]*(components\/roadmaps\/|lib\/roadmaps['"]|roadmap-comparison|workspace\/decisions['"]|counselor-research-status)/;
  const offenders = files.filter((path) => banned.test(readFileSync(path, 'utf8'))).map((path) => relative(ROOT, path));
  expect(offenders).toEqual([]);
});

it('the old roadmap files and API calls are gone', () => {
  for (const path of ['components/roadmaps', 'lib/roadmaps.ts', 'components/counselor/workspace/decisions.tsx',
    'components/chat/roadmap-comparison.tsx', 'components/chat/counselor-research-status.tsx']) {
    expect(existsSync(join(ROOT, path)), path).toBe(false);
  }
  const api = readFileSync(join(ROOT, 'lib/api.ts'), 'utf8');
  expect(api).not.toMatch(/\/v1\/roadmaps|\/paths\/\$\{[^}]+\}\/roadmap|preparePathRoadmap|getRoadmaps|chooseRoadmap/);
});
