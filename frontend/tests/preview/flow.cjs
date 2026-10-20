/* A-K behaviour checks on the redesigned UI, offline with fake data.
 * Each step proves a product boundary, not just that a screen renders. */
const assert = require('node:assert/strict');

const calls = (page) => page.evaluate(() => window.__offlineCalls);
const called = async (page, method) => (await calls(page)).filter((call) => call.method === method);

module.exports = async function flow(browser, open, ORIGIN) {
  const { context, page, errors } = await open(browser, 1440, 'light');
  const go = (path) => page.goto(`${ORIGIN}${path}${path.includes('?') ? '&' : '?'}theme=light`);
  try {
    // A: three entry steps; a required step cannot be skipped; no reply
    // language; Pakistan is the data default; no provider call.
    await go('/student?onboarding=1');
    assert.equal(await page.locator('ol[aria-label^="Step"] > li').count(), 3, 'three onboarding steps');
    assert.equal(await page.locator('form input:visible').count(), 2, 'step 1 asks first and last name only');
    await page.getByRole('button', { name: 'Continue' }).click();
    await page.getByText('Please fill this in.').first().waitFor();
    assert.equal(await page.getByText('Step 1 of 3').count(), 1, 'an empty required step does not advance');
    await page.getByLabel('First name', { exact: true }).fill('Sam');
    await page.getByLabel('Last name', { exact: true }).fill('Taylor');
    await page.getByRole('button', { name: 'Continue' }).click();
    await page.getByRole('button', { name: 'Other', exact: true }).click();
    await page.getByPlaceholder('Type it in your own words').fill('Secondary education');
    await page.getByRole('button', { name: 'Date of birth' }).click();
    await page.getByRole('option', { name: '2008', exact: true }).click();
    await page.getByRole('option', { name: 'Mar', exact: true }).click();
    await page.getByRole('button', { name: 'March 12, 2008' }).click();
    await page.getByRole('button', { name: 'Female', exact: true }).click();
    await page.getByRole('button', { name: 'Continue' }).click();
    assert.equal(await page.getByLabel('Country').inputValue(), 'Pakistan', 'country defaults to Pakistan');
    await page.getByLabel('City').fill('My city');
    assert.equal(await page.getByText(/reply language/i).count(), 0, 'no reply-language question');
    // The preview reloads into the workspace on finish; keep the recorded call.
    await page.evaluate(() => addEventListener('pagehide', () => sessionStorage.setItem('entryCalls', JSON.stringify(window.__offlineCalls))));
    await page.getByRole('button', { name: 'Start with PAI' }).click();
    await page.waitForURL('**view=threads');
    const entry = (await page.evaluate(() => JSON.parse(sessionStorage.getItem('entryCalls') || '[]')))
      .filter((call) => call.method === 'submitOnboarding').at(-1);
    assert.deepEqual(entry && entry.args[0], { firstName: 'Sam', lastName: 'Taylor', level: 'Secondary education',
      dateOfBirth: '2008-03-12', gender: 'female', currentCountry: 'Pakistan', currentCity: 'My city' }, 'entry answers sent as typed');

    // B-D: the conversation, and a journey with every A-K stage present.
    await page.getByRole('navigation').getByRole('button', { name: 'Your journey', exact: true }).click();
    await page.getByRole('heading', { name: 'Your journey, at your pace' }).waitFor();
    assert.equal(await page.locator('main ol > li').count(), 11, 'all eleven stages');
    assert.equal(await page.locator('main ol > li[aria-current="step"]').count(), 1, 'exactly one current stage');

    // E: the Mirror needs agreement before feedback; the rating is the exact version.
    await go('/student?view=threads&mirror=1');
    assert.equal(await page.getByRole('radiogroup').count(), 0, 'no rating before agreement');
    await page.getByRole('button', { name: 'Yes, that is right' }).click();
    await page.locator('label').filter({ hasText: 'Completely' }).click();
    assert(await page.getByRole('radio', { name: '5: Completely' }).isChecked(), 'the label selects the rating');
    await page.getByRole('slider').fill('7');
    await page.getByRole('button', { name: 'Send', exact: true }).click();
    await page.getByText('Thank you. PAI will use this to do better.').waitFor();
    const feedback = await called(page, 'submitCounselorMirrorFeedback');
    assert.deepEqual(feedback.at(-1).args, [1, 5, 7], 'Mirror feedback is version 1, understood 5, certainty 7');

    // F-G: paths first. Merely viewing a path must not search programs.
    await page.getByRole('navigation').getByRole('button', { name: 'Paths', exact: true }).click();
    await page.getByRole('button', { name: 'Explore', exact: true }).first().click();
    await page.getByRole('heading', { name: 'What it is', exact: true }).waitFor();
    assert.equal((await called(page, 'searchPrograms')).length, 0, 'no program search from viewing a path');

    // H: the student explicitly opens places and consents before any search.
    await page.getByRole('button', { name: 'Look at places' }).click();
    const search = page.getByRole('button', { name: 'Look at programs' });
    assert(await search.isDisabled(), 'search needs consent');
    await page.getByRole('checkbox').check();
    await search.click();
    await page.getByText('No verified program information is available yet.', { exact: false }).waitFor();
    assert.equal((await called(page, 'searchPrograms')).length, 1, 'one search after consent');

    // I: a reviewed roadmap is prepared; no choice is made for the student.
    await page.getByRole('button', { name: 'Prepare a reviewed roadmap' }).click();
    await page.getByRole('heading', { name: 'Compare paths', exact: true }).waitFor();
    assert.equal((await called(page, 'chooseRoadmap')).length, 0, 'no automatic choice');
    // The certainty slider sends nothing until the student presses Share.
    await page.locator('#decision-certainty').fill('8');
    assert.equal((await called(page, 'sendMessage')).length, 0, 'moving the slider sends nothing');
    await page.getByRole('button', { name: 'Share with PAI' }).click();
    await page.getByText('Shared with PAI.', { exact: false }).waitFor();
    const shared = await called(page, 'sendMessage');
    assert.equal(shared.length, 1);
    assert.match(String(shared[0].args[1]), /8 out of 10/);
    await page.getByRole('button', { name: 'Choose route', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('button', { name: 'Choose route', exact: true }).click();
    await dialog.getByRole('status').waitFor();
    assert.equal((await called(page, 'getRoadmapChoiceToken')).length, 1, 'one confirmation token');
    assert.equal((await called(page, 'chooseRoadmap')).length, 1, 'one explicit choice');
    await dialog.getByRole('button', { name: 'Close' }).first().click();

    // J-K: the plan, and a check-in that opens the same conversation as a
    // draft. Quick starts fill the draft; nothing is sent automatically.
    await page.getByRole('navigation').getByRole('button', { name: 'Plan & check-ins', exact: true }).click();
    await page.getByRole('heading', { name: 'Small next steps' }).waitFor();
    const sentBefore = (await called(page, 'sendMessage')).length;
    await page.getByRole('button', { name: 'Open conversation' }).click();
    await page.getByRole('region', { name: 'Check-in' }).getByRole('button', { name: 'I tried something' }).click();
    // Wait for the draft to render (the click updates React state), then check it.
    await page.waitForFunction(() => /^I tried something\. /.test(document.querySelector('textarea[data-chat-input]')?.value || ''), null, { timeout: 5000 });
    assert.match(await page.locator('textarea[data-chat-input]').inputValue(), /^I tried something\. /);
    assert.equal((await called(page, 'sendMessage')).length, sentBefore, 'check-in is a draft, not an auto-send');

    // Profile: a heatmap area opens readable details; confirm uses the exact digest.
    await go('/student?view=profile');
    await page.getByRole('button', { name: /^Current life:/ }).click();
    await page.getByText('Showing: Current life').waitFor();
    await page.getByRole('button', { name: 'Show source and actions for Name' }).click();
    await page.getByRole('button', { name: 'Confirm', exact: true }).click();
    const review = await called(page, 'reviewProfileCard');
    assert.equal(review.at(-1).args[1].expected_digest, 'a'.repeat(64));
    assert.equal(review.at(-1).args[1].action, 'confirm');
  } finally {
    assert.equal(errors.length, 0, 'flow: ' + errors.join(' | '));
    await context.close();
  }

  // Phone: the account menu lives in the top bar; sign-out needs confirmation.
  const phone = await open(browser, 375, 'dark');
  try {
    const p = phone.page;
    await p.goto(`${ORIGIN}/student?view=profile&theme=dark`);
    await p.getByRole('heading', { level: 1 }).first().waitFor();
    const account = p.getByRole('button', { name: 'Account', exact: true });
    const box = await account.boundingBox();
    assert(box && box.width >= 44 && box.height >= 44 && box.x + box.width <= 375, 'account control is reachable and 44px');
    await account.click();
    await p.getByRole('menuitem', { name: 'Sign out', exact: true }).click();
    await p.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click();
    assert.equal(await p.evaluate(() => sessionStorage.getItem('offline-sign-out')), null, 'cancel keeps the session');
    await account.click();
    await p.getByRole('menuitem', { name: 'Sign out', exact: true }).click();
    await p.getByRole('dialog').getByRole('button', { name: 'Sign out', exact: true }).click();
    await p.waitForURL('**/sign-in');
    assert.equal(await p.evaluate(() => sessionStorage.getItem('offline-sign-out')), 'done');
    // Every phone tab is a 44px target and the More sheet reaches the rest.
    await p.goto(`${ORIGIN}/student?view=journey&theme=dark`);
    for (const tab of await p.getByRole('navigation').last().getByRole('button').all()) {
      const b = await tab.boundingBox();
      assert(b && b.height >= 44 && b.width >= 44, 'tab bar target is at least 44px');
    }
    await p.getByRole('button', { name: 'More', exact: true }).click();
    await p.getByRole('dialog').getByRole('button', { name: 'Settings' }).click();
    await p.getByRole('heading', { name: 'Make this space yours' }).waitFor();
  } finally {
    assert.equal(phone.errors.length, 0, 'phone flow: ' + phone.errors.join(' | '));
    await phone.context.close();
  }
  console.log('Flow: A-K boundaries, Mirror version, consent, no auto-choice/auto-send, digest confirm, phone account and tabs.');
};
