/** Public names stay separate from Supabase's provider identifiers. */
export const OAUTH_PROVIDERS = {
  google: { label: 'Google', supabaseProvider: 'google' },
  github: { label: 'GitHub', supabaseProvider: 'github' },
  linkedin: { label: 'LinkedIn', supabaseProvider: 'linkedin_oidc' },
} as const;

export type OAuthProvider = keyof typeof OAUTH_PROVIDERS;
