/* GitHub review comments in the code workspace, using production routes and synthetic GitHub data. */
'use strict';
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PR_REVIEW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const fixture=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'../fixtures/workspace_integration_fixture.py')],{stdio:['ignore','pipe','inherit']});
 let browser;
 try{
  const [output]=await once(fixture.stdout,'data');
  browser=await chromium.launch({headless:true,channel:process.env.PR_REVIEW_BROWSER_CHANNEL||'chrome'});
  const context=await browser.newContext({viewport:{width:1440,height:1000},permissions:['clipboard-read','clipboard-write']});
  const page=await context.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(output.toString().trim());
  const placed=page.locator('#file-0 .review-thread[data-thread="PRRT_placed"]');
  await placed.waitFor();
  // Threads follow their GitHub line; resolved threads start collapsed.
  assert.equal(await page.locator('#file-0 .code-row[data-row="45"] + .row-annotations .review-thread').count(),1);
  assert.equal(await placed.getAttribute('open'),'');
  assert.equal(await page.locator('#file-0 .review-thread[data-thread="PRRT_resolved"]').getAttribute('open'),null);
  assert.equal(await placed.locator('script').count(),0);
  assert.match(await placed.innerText(),/Suggested change/);
  await placed.locator('[data-copy-code]').click();
  assert.match(await page.evaluate(()=>navigator.clipboard.readText()),/this\.items = \[\.\.\.batch/);
  assert.match(await page.locator('#file-0 .file-comments > summary').innerText(),/1 comment not on current lines/);
  assert.equal(await page.locator('#comment-count').innerText(),'4');
  assert.equal(await page.locator('#file-tree .file-thread-count').first().innerText(),'4');
  // GitHub HTML renders through the allowlist: structure stays, active content and media do not.
  const html=page.locator('.review-thread[data-thread="PRRT_html"] .chat-markdown');
  assert.equal(await html.locator('h3').innerText(),'Flush guard can drop items');
  assert.equal(await html.locator('details summary').innerText(),'Additional Locations (1)');
  assert.equal(await html.locator('sup').count(),1);
  assert.equal(await html.locator('img,picture,source,iframe,script,[style],[onclick],[onerror],.evil').count(),0);
  assert.equal(await html.locator('a',{hasText:'Fix in Cursor'}).getAttribute('target'),'_blank');
  assert.equal(await html.locator('a',{hasText:'bad link'}).getAttribute('href'),null);
  assert.doesNotMatch(await html.innerText(),/DESCRIPTION START|Medium Severity|<details>/);
  assert.equal(await page.evaluate(()=>performance.getEntriesByType('resource').some(e=>e.name.includes('cursor.com'))),false);
  // Split view places each side's thread in its own pane and keeps rows aligned.
  await page.locator('#diff-layout').selectOption('split');
  const panes=page.locator('#file-0 .split-pane');
  assert.equal(await panes.nth(1).locator('.review-thread[data-thread="PRRT_placed"]').count(),1);
  assert.equal(await panes.nth(0).locator('.review-thread[data-thread="PRRT_resolved"]').count(),1);
  assert.equal(await panes.nth(0).locator('[data-pair]').count(),await panes.nth(1).locator('[data-pair]').count());
  await page.locator('#diff-layout').selectOption('unified');
  // Filters hide resolved threads, bots, or everything, and persist in the browser.
  await page.locator('#comment-filter').selectOption('unresolved');
  assert.equal(await page.locator('.review-thread[data-thread="PRRT_resolved"]').count(),0);
  await page.locator('#comment-filter').selectOption('hidden');
  assert.equal(await page.locator('#files .review-thread').count(),0);
  await page.reload();await page.locator('#file-0 [data-line="head"]').first().waitFor();
  assert.equal(await page.locator('#comment-filter').inputValue(),'hidden');
  await page.locator('#comment-filter').selectOption('all');
  await page.locator('#file-tree [data-jump="1"]').click();
  await page.locator('#file-1 .file-comments').waitFor();
  await page.locator('#comment-bots').uncheck();
  assert.equal(await page.locator('#file-1 .file-comments').count(),0);
  await page.locator('#comment-bots').check();
  // The rail lists threads and PR conversation; jumping reveals a thread even when hidden inline.
  await page.locator('#comments-toggle').click();
  await page.locator('[data-thread-jump="PRRT_resolved"]').waitFor();
  assert.match(await page.locator('#comment-conversation').innerText(),/Changes requested/);
  await page.locator('#comment-filter').selectOption('hidden');
  await page.locator('[data-thread-jump="PRRT_placed"]').click();
  await placed.waitFor();
  assert.equal(await placed.getAttribute('open'),'');
  await page.locator('#comment-filter').selectOption('all');
  // Ask AI attaches the comment; the server rebuilds it from cached GitHub data.
  const asks=[];
  page.on('request',request=>{if(request.url().endsWith('/workspace-chat'))asks.push(request.postDataJSON());});
  await placed.locator('[data-comment-ask]').click();
  await page.locator('.context-attachment').waitFor();
  assert.match(await page.locator('#chat-context').innerText(),/1 attachment \+ PR diff/);
  assert.match(await page.locator('.context-attachment').innerText(),/Comment · batch\.ts · @sam · Head L44/);
  await page.locator('#prompt-addressed').click();
  await page.locator('[data-save-message="1"]').waitFor();
  assert.equal(asks[0].contexts[0].kind,'comment');
  assert.equal(asks[0].contexts[0].comment,'PRRT_placed');
  // Drafting starts a fresh conversation with only the comment attached.
  await page.locator('#comments-toggle').click();
  await page.locator('.conversation-item [data-comment-draft="r1"]').click();
  await page.waitForFunction(()=>document.querySelectorAll('.message.user').length===1);
  assert.match(await page.locator('.message.user').innerText(),/Draft a reply/);
  assert.equal(asks.at(-1).thread_id,null);
  assert.deepEqual(asks.at(-1).contexts.map(c=>c.comment),['r1']);
  await page.locator('[data-save-message="1"]').waitFor();
  // Embedded review findings can be attached to a focused Ask AI conversation and
  // their prepared draft can be explicitly posted through the dashboard.
  await page.locator('#review-tab').click();
  const report=page.frameLocator('.review-frame');
  await report.getByRole('heading',{name:'Fixture AI review'}).waitFor();
  await report.locator('details.review-finding > summary').first().click();
  await report.locator('button', {hasText:'Ask AI about this finding'}).waitFor();
  const postRequests=[];
  page.on('request',request=>{if(request.url().endsWith('/workspace-comment'))postRequests.push(request.postDataJSON());});
  await report.locator('button', {hasText:'Post draft on my behalf'}).click();
  await page.locator('#post-dialog').waitFor();
  assert.equal(await page.locator('#post-dialog').isVisible(),true);
  assert.match(await page.locator('#post-target').innerText(),/existing GitHub review thread/);
  assert.match(await page.locator('#post-comment').inputValue(),/existing batching behavior/);
  await page.locator('#post-submit').click();
  await page.waitForFunction(()=>document.querySelector('#post-dialog')?.open===false);
  assert.equal(postRequests.length,1);
  assert.equal(postRequests[0].finding,'finding-1');
  assert.match(postRequests[0].body,/existing batching behavior/);
  const findingAsks=[];
  page.on('request',request=>{if(request.url().endsWith('/workspace-chat'))findingAsks.push(request.postDataJSON());});
  await report.locator('button', {hasText:'Ask AI about this finding'}).click();
  await page.locator('.context-attachment').waitFor();
  assert.match(await page.locator('#chat-context').innerText(),/AI review finding/);
  assert.equal(findingAsks.at(-1).contexts[0].kind,'finding');
  assert.equal(findingAsks.at(-1).contexts[0].finding,1);
  // Standalone artifact links use the same trusted workspace actions with a deep link.
  const deepLink=await context.newPage();
  await deepLink.goto(new URL('/workspace?'+new URLSearchParams({url:'https://github.com/example/telemetry-sdk/pull/248',tab:'review',finding:'finding-1',finding_action:'post'}),page.url()).href);
  await deepLink.locator('#post-dialog').waitFor();
  assert.equal(await deepLink.locator('#post-dialog').isVisible(),true);
  assert.match(await deepLink.locator('#post-target').innerText(),/existing GitHub review thread/);
  await deepLink.close();
  for(const width of [880,390]){
   await page.setViewportSize({width,height:950});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`overflow ${width}`);
  }
  assert.deepEqual(errors,[]);
  console.log('Workspace comment browser checks passed: inline placement, split alignment, filters, rail navigation, Ask AI and draft replies.');
 }finally{if(browser)await browser.close();fixture.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
