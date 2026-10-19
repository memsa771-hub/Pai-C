// Preview-only auth service: never contacts an identity provider.
// The password "wrong" fails so the harness can capture the error state.
const wait = () => new Promise((resolve) => setTimeout(resolve, 150));
export const signInWithPassword = async (_identifier: string, password: string) => {
  await wait(); if (password === 'wrong') throw new Error('That email or password does not match an account.'); return {} as never;
};
export const signUpWithPassword = async () => { await wait(); return { session: null, needsEmailConfirmation: true }; };
// The real call leaves for the provider; the preview marks the URL instead.
export const signInWithOAuth = async (provider: string) => { location.hash = 'oauth-' + provider; };
export const requestPasswordReset = async () => { await wait(); };
export const completePasswordReset = async () => ({} as never);
export const completeOAuth = async () => { throw new Error('This sign-in link has expired. Please try again.'); };
export const authenticatedFetch = async (): Promise<Response> => { throw new Error('Network disabled in offline UI review'); };
