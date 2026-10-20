import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { it, expect } from 'vitest';
import labels from './evidence-labels.json';
import { evidenceText } from './evidence-text';

const BACKEND = join(__dirname, '../../backend/app');
const KEY = /["']((?:identity|location|preferences|finance|language|communication)\.[a-z_]+)["']/g;
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (name === '__pycache__') return [];
    return statSync(path).isDirectory() ? sources(path) : name.endsWith('.py') ? [path] : [];
  });
}

it.skipIf(!existsSync(BACKEND))('every profile field the backend writes has a human label', () => {
  const keys = new Set(sources(BACKEND).flatMap((file) => [...readFileSync(file, 'utf8').matchAll(KEY)].map((m) => m[1])));
  const missing = [...keys].filter((key) => !(key in labels.labels));
  expect(missing).toEqual([]);
});

it('formats date-only values as calendar days and never shows raw ids', () => {
  expect(evidenceText('2024-05-30')).toBe('May 30, 2024');
  expect(evidenceText({ id: 'x1', qualification_name: 'Lower secondary' })).toBe('Qualification — Lower secondary');
});
