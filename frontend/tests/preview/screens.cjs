/* Screen registry for the offline harness. Paths use synthetic fixtures. */
const fill = async (page, label, value) => page.getByLabel(label, { exact: true }).fill(value);
const submit = async (page, name) => { await page.getByRole('button', { name, exact: true }).click(); };

module.exports = [
  { id: 'design-system', path: '/student?kit=1', full: true, crawl: false },

  { id: 'auth-sign-in', path: '/sign-in' },
  { id: 'auth-sign-in-error', path: '/sign-in', crawl: false, setup: async (page) => {
    await fill(page, 'Email', 'sam@example.test'); await fill(page, 'Password', 'wrong');
    await submit(page, 'Sign in'); await page.getByRole('alert').waitFor();
  } },
  { id: 'auth-sign-in-empty', path: '/sign-in', crawl: false, setup: async (page) => {
    await submit(page, 'Sign in'); await page.getByText('Enter a valid email address.').waitFor();
  } },
  { id: 'auth-sign-up', path: '/sign-up' },
  { id: 'auth-sign-up-error', path: '/sign-up', crawl: false, setup: async (page) => {
    await fill(page, 'Email', 'sam@example.test');
    await fill(page, 'Password', 'Better-pass1'); await fill(page, 'Confirm password', 'Different-pass1');
    await submit(page, 'Create account'); await page.getByText('Passwords do not match.').waitFor();
  } },
  { id: 'auth-check-email', path: '/sign-up', crawl: false, setup: async (page) => {
    await fill(page, 'Email', 'sam@example.test');
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
  { id: 'onboarding-name-error', path: '/student?onboarding=1', crawl: false, setup: async (page) => {
    await submit(page, 'Continue'); await page.getByText('Please fill this in.').first().waitFor();
  } },
  { id: 'onboarding-about', path: '/student?onboarding=1', setup: async (page) => {
    await fill(page, 'First name', 'Sam'); await fill(page, 'Last name', 'Taylor'); await submit(page, 'Continue');
    await submit(page, 'FSc'); await submit(page, 'Female');
  } },
  { id: 'onboarding-calendar', path: '/student?onboarding=1', crawl: false, setup: async (page) => {
    await fill(page, 'First name', 'Sam'); await fill(page, 'Last name', 'Taylor'); await submit(page, 'Continue');
    await page.getByRole('button', { name: 'Date of birth' }).click(); await page.getByRole('listbox').waitFor();
  } },
  { id: 'onboarding-place', path: '/student?onboarding=1', setup: async (page) => {
    await fill(page, 'First name', 'Sam'); await fill(page, 'Last name', 'Taylor'); await submit(page, 'Continue');
    await submit(page, 'FSc'); await submit(page, 'Female');
    await page.getByRole('button', { name: 'Date of birth' }).click();
    await page.getByRole('option', { name: '2008', exact: true }).click();
    await page.getByRole('option', { name: 'Mar', exact: true }).click();
    await page.getByRole('button', { name: 'March 12, 2008' }).click();
    await submit(page, 'Continue'); await page.getByLabel('City').waitFor();
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

  { id: 'compare', path: '/student?view=compare&roadmap=1', ready: 'main h1', full: true },
  { id: 'compare-family', path: '/student?view=compare&roadmap=1', ready: 'main h1', full: true, crawl: false, setup: async (page) => {
    await page.getByRole('button', { name: 'Help me talk this through with my family', exact: true }).click();
    await page.locator('label', { hasText: 'Parent' }).first().click();
    if (!(await page.getByRole('radio', { name: 'Parent', exact: true }).isChecked())) throw new Error('compare-family: the label must select the person');
    await page.getByRole('checkbox').first().check();
  } },
  { id: 'decision', path: '/student?view=compare&roadmap=1', ready: 'main h1', crawl: false, setup: async (page) => {
    await page.getByRole('button', { name: 'Choose route', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Choose route', exact: true }).click();
    await page.getByRole('dialog').getByRole('status').waitFor();
  } },
  { id: 'compare-chosen', path: '/student?view=compare&roadmap=1&family=1', ready: 'main h1', full: true },
  { id: 'plan-empty', path: '/student?view=plan', ready: 'main h1', full: true },
  { id: 'plan', path: '/student?view=plan&roadmap=1&family=1', ready: 'main h1', full: true },
  { id: 'roadmap-details', path: '/student?view=compare&roadmap=1', ready: 'main h1', crawl: false, setup: async (page) => {
    await page.getByRole('button', { name: 'View details' }).click(); await page.getByRole('dialog').waitFor();
  } },

  { id: 'documents', path: '/student?view=files', ready: 'main h1' },
  { id: 'settings', path: '/student?view=settings', ready: 'main h1', full: true },
  { id: 'settings-delete', path: '/student?view=settings', ready: 'main h1', full: true, crawl: false, setup: async (page) => {
    await page.getByRole('button', { name: 'Delete my app data' }).click(); await page.getByRole('checkbox').waitFor();
  } },

  { id: 'states-profile-loading', path: '/student?view=profile&state=loading', ready: 'main [role=status], main [role=alert], main h1', crawl: false },
  { id: 'states-profile-error', path: '/student?view=profile&state=error', ready: 'main [role=status], main [role=alert], main h1', crawl: true },
  { id: 'states-profile-empty', path: '/student?view=profile&state=empty', ready: 'main [role=status], main [role=alert], main h1', crawl: true },
  { id: 'states-journey-loading', path: '/student?view=journey&state=loading', ready: 'main [role=status], main [role=alert], main h1', crawl: false },
  { id: 'states-journey-error', path: '/student?view=journey&state=error', ready: 'main [role=status], main [role=alert], main h1', crawl: true },
  { id: 'states-journey-empty', path: '/student?view=journey&state=empty', ready: 'main [role=status], main [role=alert], main h1', crawl: true },
  { id: 'states-paths-loading', path: '/student?view=paths&state=loading', ready: 'main [role=status], main [role=alert], main h1', crawl: false },
  { id: 'states-paths-error', path: '/student?view=paths&state=error', ready: 'main [role=status], main [role=alert], main h1', crawl: true },
  { id: 'states-paths-empty', path: '/student?view=paths&state=empty', ready: 'main [role=status], main [role=alert], main h1', crawl: true },
  { id: 'states-compare-loading', path: '/student?view=compare&state=loading', ready: 'main [role=status], main [role=alert], main h1', crawl: false },
  { id: 'states-compare-error', path: '/student?view=compare&state=error', ready: 'main [role=status], main [role=alert], main h1', crawl: true },
  { id: 'states-compare-empty', path: '/student?view=compare&state=empty', ready: 'main [role=status], main [role=alert], main h1', crawl: true },
  { id: 'states-plan-loading', path: '/student?view=plan&state=loading', ready: 'main [role=status], main [role=alert], main h1', crawl: false },
  { id: 'states-plan-error', path: '/student?view=plan&state=error', ready: 'main [role=status], main [role=alert], main h1', crawl: true },
  { id: 'states-plan-empty', path: '/student?view=plan&state=empty', ready: 'main [role=status], main [role=alert], main h1', crawl: true },
  { id: 'states-path-error', path: '/student?view=paths&path=path-one&state=error', ready: 'main [role=alert]', crawl: true },
  { id: 'states-programs-loading', path: '/student?view=paths&path=path-one&stage=H&state=loading', ready: 'main [role=status]', crawl: false },
];
