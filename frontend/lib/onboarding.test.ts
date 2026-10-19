import { describe, expect, it } from 'vitest';
import { FIELD_LAYOUT, visibleOnboardingAnswers } from './onboarding';

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
