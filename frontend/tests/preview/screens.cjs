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

  { id: 'onboarding-name', path: '/student?onboarding=1' },
  { id: 'onboarding-level', path: '/student?onboarding=1', setup: async (page) => {
    await page.getByLabel('Your name').fill('Sam Taylor'); await submit(page, 'Next');
    await submit(page, 'Other'); await page.getByPlaceholder('Type it in your own words').fill('Secondary education');
  } },
  { id: 'onboarding-language', path: '/student?onboarding=1', setup: async (page) => {
    await page.getByLabel('Your name').fill('Sam Taylor'); await submit(page, 'Next');
    await submit(page, 'Catalog level'); await submit(page, 'Next');
    await page.getByLabel('City').fill('My city'); await submit(page, 'Next');
    await submit(page, 'English');
  } },

  { id: 'shell', path: '/student?view=journey', ready: 'main h1' },
  { id: 'shell-account-menu', path: '/student?view=journey', ready: 'main h1', crawl: false, setup: async (page) => {
    await page.getByRole('button', { name: 'Account', exact: true }).click(); await page.getByRole('menuitem', { name: 'Sign out' }).waitFor();
  } },
  { id: 'shell-notifications', path: '/student?view=journey', ready: 'main h1', crawl: false, setup: async (page) => {
    await page.getByRole('button', { name: 'Notifications', exact: true }).click(); await page.waitForTimeout(250);
  } },
  { id: 'shell-more', path: '/student?view=journey', ready: 'main h1', crawl: false, setup: async (page) => {
    const more = page.getByRole('button', { name: 'More', exact: true });
    if (await more.isVisible()) { await more.click(); await page.getByRole('dialog').waitFor(); }
  } },
  { id: 'journey', path: '/student?view=journey', ready: 'main h1', full: true },

  { id: 'profile', path: '/student?view=profile', ready: 'main h1', full: true },
  { id: 'profile-mirror-check', path: '/student?view=profile&mirror=1', ready: 'main h1', full: true, crawl: false },
  { id: 'profile-private-shown', path: '/student?view=profile', ready: 'main h1', full: true, crawl: false, setup: async (page) => {
    await page.getByRole('button', { name: 'Show private details' }).click();
  } },
  { id: 'profile-details', path: '/student?view=profile&tab=details', ready: 'main h1', full: true },
  { id: 'profile-details-filtered', path: '/student?view=profile', ready: 'main h1', full: true, crawl: false, setup: async (page) => {
    await page.getByRole('button', { name: /^Education & experience:/ }).click();
    await page.getByText('Showing: Education & experience').waitFor();
  } },
  { id: 'profile-details-row-open', path: '/student?view=profile&tab=details', ready: 'main h1', full: true, crawl: false, setup: async (page) => {
    await page.getByRole('button', { name: 'Show source and actions for Education' }).first().click();
  } },

  { id: 'chat', path: '/student?view=threads', ready: 'main textarea' },
  { id: 'chat-empty', path: '/student?view=threads&card=empty', ready: 'main textarea', crawl: false },
  { id: 'chat-typing', path: '/student?view=threads&card=typing', ready: 'main textarea', crawl: false },
  { id: 'chat-first-picture', path: '/student?view=threads&card=picture', ready: 'main textarea', crawl: false },
  { id: 'chat-rating', path: '/student?view=threads&card=rating', ready: 'main textarea' },
  { id: 'chat-fact-upload', path: '/student?view=threads&card=fact', ready: 'main textarea' },
  { id: 'chat-path-card', path: '/student?view=threads&card=paths', ready: 'main textarea' },
  { id: 'chat-mirror', path: '/student?view=threads&mirror=1', ready: 'main textarea' },
  { id: 'chat-mirror-rate', path: '/student?view=threads&mirror=1', ready: 'main textarea', crawl: false, setup: async (page) => {
    await page.getByRole('button', { name: 'Yes, that is right' }).click(); await page.getByRole('radiogroup').waitFor();
  } },
  { id: 'chat-check-in', path: '/student?view=plan', ready: 'main h1', crawl: false, setup: async (page) => {
    await page.getByRole('button', { name: 'Open conversation' }).first().click();
    await page.getByRole('region', { name: 'Check-in' }).waitFor();
  } },

  { id: 'paths', path: '/student?view=paths', ready: 'main h1', full: true },
  { id: 'path', path: '/student?view=paths&path=path-one', ready: 'main h1', full: true },
  { id: 'programs-consent', path: '/student?view=paths&path=path-one&stage=H', ready: 'main h1', full: true },
  { id: 'programs', path: '/student?view=paths&path=path-one&stage=H&programs=1', ready: 'main h1', full: true },
  { id: 'programs-none-verified', path: '/student?view=paths&path=path-one&stage=H', ready: 'main h1', full: true, crawl: false, setup: async (page) => {
    await page.getByRole('checkbox').check(); await page.getByRole('button', { name: 'Look at programs' }).click();
    await page.getByText('No verified program information', { exact: false }).waitFor();
  } },
];
