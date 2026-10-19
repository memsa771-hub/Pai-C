/* Screen registry for the offline harness. Paths use synthetic fixtures. */
const fill = async (page, label, value) => page.getByLabel(label, { exact: true }).fill(value);
const submit = async (page, name) => { await page.getByRole('button', { name, exact: true }).click(); };

module.exports = [
  { id: 'design-system', path: '/student?kit=1', full: true, crawl: false },

  { id: 'auth-sign-in', path: '/sign-in' },
  { id: 'auth-sign-in-error', path: '/sign-in', crawl: false, setup: async (page) => {
    await fill(page, 'Email or username', 'sam'); await fill(page, 'Password', 'wrong');
    await submit(page, 'Sign in'); await page.getByRole('alert').waitFor();
  } },
  { id: 'auth-sign-up', path: '/sign-up' },
  { id: 'auth-sign-up-error', path: '/sign-up', crawl: false, setup: async (page) => {
    await fill(page, 'Username', 'sam'); await fill(page, 'Email', 'sam@example.test');
    await fill(page, 'Password', 'Better-pass1'); await fill(page, 'Confirm password', 'Different-pass1');
    await submit(page, 'Create account'); await page.getByText('Passwords do not match.').waitFor();
  } },
  { id: 'auth-check-email', path: '/sign-up', crawl: false, setup: async (page) => {
    await fill(page, 'Username', 'sam'); await fill(page, 'Email', 'sam@example.test');
    await fill(page, 'Password', 'Better-pass1'); await fill(page, 'Confirm password', 'Better-pass1');
    await submit(page, 'Create account'); await page.getByRole('heading', { name: 'Check your email' }).waitFor();
  } },
  { id: 'auth-forgot', path: '/forgot-password' },
  { id: 'auth-forgot-sent', path: '/forgot-password', crawl: false, setup: async (page) => {
    await fill(page, 'Email', 'sam@example.test'); await submit(page, 'Send reset link');
    await page.getByRole('heading', { name: 'Reset link sent' }).waitFor();
  } },
  { id: 'auth-reset', path: '/auth/reset-password?code=offline' },
  { id: 'auth-reset-expired', path: '/auth/reset-password', ready: 'h1' },
  { id: 'auth-callback-failed', path: '/auth/callback?error=access_denied', ready: 'h1' },
];
