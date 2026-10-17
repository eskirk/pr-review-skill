// Capture the production UI with disposable synthetic fixtures. Never use live tracker data.
'use strict';
const {spawn, execFileSync} = require('node:child_process');
const {once} = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PR_REVIEW_PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const output = path.resolve(process.argv[2] || path.join(root, 'docs/screenshots'));
const python = process.env.PYTHON || 'python3';
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'readme-captures-'));
let browser;

async function capture(page, name) {
  await page.evaluate(async () => {await document.fonts.ready; await Promise.all(document.getAnimations().map(a => a.finished.catch(() => {})));});
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), name + ' overflows');
  await page.screenshot({path: path.join(output, name + '.jpg'), type: 'jpeg', quality: 88, animations: 'disabled'});
}

async function fixture(name, action) {
  const child = spawn(python, [path.join(root, 'tests/fixtures', name + '.py')], {
    env: {...process.env, TMPDIR: temporary, PR_REVIEW_TRACKER_HOME: temporary, PR_REVIEW_TRACKER_GH: '/usr/bin/false'},
    stdio: ['ignore', 'pipe', 'inherit'],
  });
  let context;
  try {
    // Tracker commands may log before the fixture prints its URL.
    const url = await new Promise((resolve, reject) => {
      let log = '';
      child.stdout.on('data', chunk => {
        log += chunk;
        const match = log.match(/^http:\/\/127\.0\.0\.1:\d+\S*/m);
        if (match) resolve(match[0]);
      });
      child.once('error', reject);
      child.once('exit', code => reject(new Error(`Fixture exited: ${code}`)));
    });
    context = await browser.newContext({viewport: {width: 1440, height: 1050}, colorScheme: 'light'});
    const origin = new URL(url).origin;
    await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await action(page, url);
    assert.deepEqual(errors, []);
  } finally {
    if (context) await context.close();
    if (child.exitCode === null) {const done = once(child, 'exit'); child.kill('SIGTERM'); await done;}
  }
}

(async () => {
  fs.mkdirSync(output, {recursive: true});
  browser = await chromium.launch({headless: true, channel: process.env.PR_REVIEW_BROWSER_CHANNEL || 'chrome'});
  await fixture('workspace_browser_fixture', async (page, url) => {
    const titles = ['Preserve keyboard focus in the command menu', 'Retry failed telemetry batches', 'Stream uploads with bounded memory', 'Handle disconnects during export', 'Update parser error messages'];
    await page.route('**/api/state', async route => {
      const response = await route.fetch();
      const state = await response.json();
      state.prs.forEach((pr, i) => {
        pr.title = titles[i % titles.length];
        pr.author_login = ['ava-demo', 'sam-demo', 'kim-demo'][i % 3];
        if (pr.triage) pr.triage.reason = 'Estimated from the synthetic diff; validate behavior during review.';
      });
      await route.fulfill({json: state});
    });
    await page.goto(url);
    await page.locator('[data-pr]').first().waitFor();
    await capture(page, 'inbox-light');
    await page.click('#settings-show');
    await page.locator('#settings[open]').waitFor();
    await capture(page, 'ai-settings-light');
    await page.locator('#settings').evaluate(dialog => dialog.close());
    await page.emulateMedia({colorScheme: 'dark'});
    await page.click('#reporting-tab');
    await page.locator('.report-bar').first().waitFor();
    await page.getByRole('button', {name: /11 reviewed, 8 yours merged/}).click();
    await capture(page, 'reporting-dark');
    // A fresh light page: switching the theme in place leaves transitions that never settle.
    const cost = await page.context().newPage();
    await cost.goto(url);
    await cost.click('#reporting-tab');
    await cost.locator('.cost-day').first().waitFor();
    await cost.locator('.cost-section').evaluate(el => el.scrollIntoView());
    await cost.locator('.cost-day').nth(26).hover();
    await cost.locator('.cost-tooltip:not([hidden])').waitFor();
    await capture(cost, 'reporting-cost-light');
  });
  await fixture('my_reviews_browser_fixture', async (page, url) => {
    await page.goto(url); await page.click('#my-reviews-tab');
    await page.locator('[data-queue-pr]').first().waitFor();
    await capture(page, 'my-reviews-light');
  });
  await fixture('workspace_integration_fixture', async (page, url) => {
    await page.goto(url);
    const thread = page.locator('#file-0 .review-thread[data-thread="PRRT_placed"]');
    await thread.waitFor();
    await thread.scrollIntoViewIfNeeded();
    await page.click('#comments-toggle');
    await page.locator('#comment-conversation').waitFor();
    await capture(page, 'code-workspace-light');
  });
  await fixture('codex_browser_fixture', async (page, url) => {
    await page.goto(url); await page.locator('[data-review-open]').first().click();
    await page.locator('#review-dialog[open] .review-event').first().waitFor();
    await page.locator('#review-compose-text').fill('What is going on?');
    await page.locator('#review-compose-text').press('Enter');
    await page.waitForFunction(() => document.getElementById('review-updates').textContent.includes('Sample reply'));
    await page.setViewportSize({width: 1440, height: 1250});
    await capture(page, 'live-review-light');
  });
  const report = path.join(temporary, 'review.html');
  execFileSync(python, [path.join(root, 'tests/fixtures/readme_report_fixture.py'), report]);
  const page = await browser.newPage({viewport: {width: 1440, height: 1050}, colorScheme: 'light'});
  await page.goto(pathToFileURL(report).href);
  await capture(page, 'review-overview-light');
  // Paper reports are one scrolling page; capture the change section and the findings.
  await page.locator('#change').evaluate(el => el.scrollIntoView());
  await capture(page, 'review-explainer-light');
  await page.locator('.review-finding > summary').nth(0).click();
  await page.locator('#review-findings').evaluate(el => el.scrollIntoView());
  await capture(page, 'review-findings-light');
  console.log('Captured ten README images from production assets and synthetic fixtures.');
})().catch(error => {console.error(error); process.exitCode = 1;}).finally(async () => {
  if (browser) await browser.close();
  fs.rmSync(temporary, {recursive: true, force: true});
});
