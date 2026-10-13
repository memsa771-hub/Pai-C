import { describe, expect, it } from 'vitest';
import { FIELD_LAYOUT } from './onboarding';

describe('generic onboarding layout', () => {
  it('does not suggest an identity or location using example answers', () => {
    for (const field of ['fullName', 'preferredName', 'nationality', 'currentCountry', 'currentCity']) {
      expect(FIELD_LAYOUT[field]).not.toHaveProperty('placeholder');
    }
  });
});
