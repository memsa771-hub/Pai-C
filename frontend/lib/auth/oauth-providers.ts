/** Public names stay separate from Supabase's provider identifiers. */
/** Google is the only social sign-in. */
export const OAUTH_PROVIDERS = {
  google: { label: 'Google', supabaseProvider: 'google' },
} as const;

export type OAuthProvider = keyof typeof OAUTH_PROVIDERS;
