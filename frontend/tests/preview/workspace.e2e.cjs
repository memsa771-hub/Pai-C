/* Offline UI review harness. Runs against the fixture Vite server only
 * (`npx vite --config tests/preview/vite.config.mjs`). No real API, identity
 * or provider is used: every non-local request is aborted.
 *
 *   node tests/preview/workspace.e2e.cjs <playwright-module-path> [--only=a,b] [--skip-crawl] [--skip-flow] [--flow-only]
 *
 * For every screen: light and dark at 375, 768 and 1440 px. It fails on page
 * errors, console errors, horizontal overflow and raw schema keys in visible
 * text, and saves screenshots (375 and 1440) to docs/counselor/screenshots/v2.
 * The crawler clicks every enabled control and fails on dead buttons and on
 * links to routes the app does not have. The flow section checks A-K
 * boundaries (consent, no automatic choice, no auto-send). */
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { chromium } = require(process.argv[2] || 'playwright');
const args = process.argv.slice(3);
const only = (args.find((a) => a.startsWith('--only=')) || '').slice(7).split(',').filter(Boolean);
const OUT = path.resolve(__dirname, '../../../docs/counselor/screenshots/v2');
const ORIGIN = 'http://127.0.0.1:4173';
const WIDTHS = [375, 768, 1440];
const SHOT_WIDTHS = [375, 1440];
const THEMES = ['light', 'dark'];

/* Screens. `full` expands the app's scroll container so the whole page is
 * captured; `ready` is a locator that must appear; `setup` drives a state. */
const SCREENS = require('./screens.cjs');

/* Next.js routes that exist in app/. Links must resolve to one of these. */
const ROUTES = [/^\/$/, /^\/sign-in$/, /^\/sign-up$/, /^\/forgot-password$/, /^\/auth\/(callback|desktop|reset-password)$/,
  /^\/share\/[^/]+$/, /^\/[^/]+$/, /^\/[^/]+\/settings(\/(general|integrations|preferences|profile|security))?$/];
const RAW_KEY = /\b(?:identity|location|preferences|education|language|communication)\.[a-z_]+\b|\b[a-z]{2,}_[a-z_]{2,}\b/;
const EXPAND = '[data-scroll-root]{height:auto!important;min-height:100svh;overflow:visible!important}'
  + '[data-scroll-root] [data-scroll-area]{overflow:visible!important;height:auto!important}';

async function open(browser, width, theme) {
  const context = await browser.newContext({ viewport: { width, height: width < 500 ? 812 : width < 1000 ? 1024 : 900 } });
  await context.route('**/*', (route) => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push('page error: ' + error.message));
  page.on('console', (message) => { if (message.type() === 'error') errors.push('console: ' + message.text()); });
  page.theme = theme;
  return { context, page, errors };
}
const url = (screen, theme) => `${ORIGIN}${screen.path}${screen.path.includes('?') ? '&' : '?'}theme=${theme}`;
async function load(page, screen) {
  await page.goto(url(screen, page.theme));
  await page.locator(screen.ready || 'button').first().waitFor({ timeout: 10000 });
  if (screen.setup) await screen.setup(page);
  await page.waitForTimeout(screen.settle || 350);
}

async function checkScreens(browser) {
  fs.mkdirSync(OUT, { recursive: true });
  let shots = 0;
  for (const screen of SCREENS.filter((s) => !only.length || only.some((o) => s.id.startsWith(o)))) {
    for (const theme of THEMES) for (const width of WIDTHS) {
      const { context, page, errors } = await open(browser, width, theme);
      const where = `${screen.id} ${theme} ${width}px`;
      try {
        await load(page, screen);
        const text = await page.locator('body').innerText();
        assert(text.length > 60, `${where}: renders content`);
        const raw = text.match(RAW_KEY);
        assert(!raw, `${where}: raw key visible: ${raw && raw[0]}`);
        const [scrollWidth, innerWidth] = await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
        assert(scrollWidth <= innerWidth, `${where}: horizontal overflow ${scrollWidth} > ${innerWidth}`);
        if (SHOT_WIDTHS.includes(width)) {
          if (screen.full) { await page.addStyleTag({ content: EXPAND }); await page.waitForTimeout(150); }
          const device = width < 500 ? 'phone' : 'desktop';
          await page.screenshot({ path: path.join(OUT, `${screen.id}-${theme}-${device}.png`), fullPage: !!screen.full });
          shots++;
        }
        assert.equal(errors.length, 0, `${where}: ${errors.join(' | ')}`);
      } finally { await context.close(); }
    }
  }
  return shots;
}

/* Click every enabled button and link in a screen and prove it does something:
 * the URL changes, the DOM changes, or focus moves into a new layer. */
async function crawl(browser) {
  const dead = [], badLinks = [], failures = [];
  let clicks = 0;
  for (const screen of SCREENS.filter((s) => s.crawl !== false && (!only.length || only.some((o) => s.id.startsWith(o))))) {
    for (const width of [1440, 375]) {
      const { context, page, errors } = await open(browser, width, 'light');
      try {
        await load(page, screen);
        const count = await page.locator('button:not([disabled]):visible, a[href]:visible').count();
        for (let i = 0; i < count; i++) {
          await load(page, screen);
          const control = page.locator('button:not([disabled]):visible, a[href]:visible').nth(i);
          if (!(await control.count())) continue;
          const name = ((await control.getAttribute('aria-label')) || (await control.innerText()).trim() || '(icon)').slice(0, 40);
          // Re-selecting the selected chip or the current page is a correct no-op.
          if ((await control.getAttribute('aria-pressed')) === 'true' || (await control.getAttribute('aria-current')) === 'page'
            || (await control.getAttribute('aria-selected')) === 'true') continue;
          const href = await control.getAttribute('href');
          if (href !== null) {
            const target = new URL(href, page.url());
            if (target.origin === ORIGIN && !ROUTES.some((route) => route.test(target.pathname))) badLinks.push(`${screen.id}: "${name}" -> ${target.pathname}`);
            continue; // In-app links leave the preview; their target route is what matters.
          }
          const before = page.url();
          let chooser = false;
          page.once('filechooser', () => { chooser = true; });
          page.once('download', () => { chooser = true; });
          await page.evaluate(() => {
            window.__mutations = 0;
            new MutationObserver((list) => { window.__mutations += list.length; })
              .observe(document.body, { subtree: true, childList: true, attributes: true, characterData: true });
          });
          try { await control.click({ timeout: 3000 }); } catch (error) { failures.push(`${screen.id} ${width}: "${name}": ${error.message.split('\n')[0]}`); continue; }
          clicks++;
          await page.waitForTimeout(400);
          // Opening the file chooser or starting a download is a real response.
          const changed = chooser || page.url() !== before || (await page.evaluate(() => window.__mutations || 0)) > 0;
          if (!changed) dead.push(`${screen.id} ${width}px: "${name}"`);
        }
        if (errors.length) failures.push(`${screen.id} ${width}: ${errors.join(' | ')}`);
      } finally { await context.close(); }
    }
  }
  assert.equal(badLinks.length, 0, 'Links to missing routes:\n' + badLinks.join('\n'));
  assert.equal(dead.length, 0, 'Dead buttons:\n' + dead.join('\n'));
  assert.equal(failures.length, 0, 'Crawler failures:\n' + failures.join('\n'));
  return clicks;
}

(async () => {
  const browser = await chromium.launch({ channel: 'msedge' });
  const flowOnly = args.includes('--flow-only');
  const shots = flowOnly ? 0 : await checkScreens(browser);
  const clicks = flowOnly || args.includes('--skip-crawl') ? 0 : await crawl(browser);
  if (flowOnly || (!args.includes('--skip-flow') && !only.length)) await require('./flow.cjs')(browser, open, ORIGIN);
  console.log(`PASS: ${shots} screenshots, ${clicks} crawled clicks, no overflow, raw keys or console errors. No live calls.`);
  await browser.close();
})().catch((error) => { console.error(error); process.exit(1); });
