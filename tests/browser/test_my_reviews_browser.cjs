// Exercise My reviews lanes, moves, undo, reminders, snooze, search and automatic-move notices on synthetic data.
'use strict';
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PR_REVIEW_PLAYWRIGHT_MODULE||'playwright');
const pr=number=>`https://github.com/demo/workbench/pull/${number}`;
(async()=>{
 const fixture=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'../fixtures/my_reviews_browser_fixture.py')],{stdio:['ignore','pipe','inherit']});
 let browser;
 try{
  const [output]=await once(fixture.stdout,'data'),origin=output.toString().trim();
  browser=await chromium.launch({headless:true,channel:process.env.PR_REVIEW_BROWSER_CHANNEL||'chrome'});
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
  const page=await context.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>{if(!sessionStorage.getItem('seeded')){localStorage.setItem('pr-personal-view','queue');sessionStorage.setItem('seeded','1');}});
  await page.goto(origin);
  const card=number=>page.locator(`#queue-list [data-queue-pr="${pr(number)}"]`);
  const sectionOf=async number=>card(number).evaluate(el=>el.closest('[data-queue-section]')?.dataset.queueSection);
  const toast=page.locator('#toast');
  const expectToast=async text=>{await page.waitForFunction(t=>document.getElementById('toast').textContent.includes(t),text);};
  await card(201).waitFor();

  // Lanes are grouped by turn, in order, with counts and default collapse state.
  assert.deepEqual(await page.locator('.queue-turn-title').allTextContents(),['Your turn','Their turn','Later','Finished']);
  assert.deepEqual(await page.locator('[data-queue-section]').evaluateAll(els=>els.map(e=>[e.dataset.queueSection,e.open,e.querySelector('.count').textContent])),
   [['reviewing',true,'1'],['attention',true,'2'],['up_next',true,'3'],['waiting',false,'2'],['snoozed',false,'1'],['history',false,'1'],['removed',false,'1']]);
  assert.equal(await page.locator('#queue-summary').textContent(),'6 on your turn · 2 waiting for authors · 1 snoozed');
  // Each lane is a table; the Status column says why a PR is there and links what's new.
  assert.match(await card(202).locator('.queue-status-reasons').textContent(),/Head changed since your last check.*Author commented/);
  assert.match(await card(202).locator('.queue-status').textContent(),/You handed it back to the author 3d ago/);
  assert.match(await card(201).locator('.queue-status-reasons').textContent(),/Reply in your review thread/);
  assert.equal(await card(206).locator('.queue-status > span').first().textContent(),'You paused it 2d ago');
  assert.equal(await page.locator('#queue-attention .queue-rank').first().textContent(),'●');
  // The side panel keeps the full context, including the "New since you started" lead.
  await card(201).locator('td.queue-status').click();
  assert.match(await page.locator('#pr-drawer-body .queue-reasons').textContent(),/New since you started.*Reply in your review thread/);
  assert.equal(await page.locator('#pr-drawer-body .queue-tools').getAttribute('open'),'');
  await page.click('#pr-drawer-close');

  // Collapsed state persists across reloads.
  await page.locator('#queue-waiting > summary').click();
  await page.waitForFunction(()=>localStorage.getItem('pr-queue-waiting-open')==='true');await page.reload();await card(207).waitFor({state:'visible'});
  assert.equal(await page.locator('#queue-waiting').evaluate(el=>el.open),true);

  // Keep waiting explains where the PR went, and Undo brings it back.
  // Keep waiting and Pause live in the ••• menu.
  await card(202).locator('.pr-overflow > summary').click();
  await card(202).getByRole('button',{name:'Keep waiting',exact:true}).click();
  await expectToast('#202 stays in Waiting for author');
  assert.equal(await sectionOf(202),'waiting');
  await toast.getByRole('button',{name:'Undo'}).click();await expectToast('Undone.');
  await page.waitForFunction(url=>document.querySelector(`[data-queue-pr="${url}"]`)?.closest('[data-queue-section]')?.dataset.queueSection==='attention',pr(202));

  // Start, then Show scrolls to and highlights the moved PR.
  await card(204).getByRole('button',{name:'Start review',exact:true}).click();
  await expectToast('#204 is in progress.');assert.equal(await sectionOf(204),'reviewing');
  await page.evaluate(()=>scrollTo(0,document.body.scrollHeight));
  await toast.getByRole('button',{name:'Show'}).click();
  await page.waitForFunction(url=>document.querySelector(`[data-queue-pr="${url}"]`)?.classList.contains('queue-flash'),pr(204));

  // Pause returns to the top of Up next; hand back moves to waiting.
  await card(201).locator('.pr-overflow > summary').click();
  await card(201).getByRole('button',{name:'Pause',exact:true}).click();await expectToast('#201 is paused at the top of Up next');
  assert.equal(await page.locator('#queue-up_next .queue-item').first().getAttribute('data-queue-pr'),pr(201));
  assert.equal(await page.locator('#queue-up_next .queue-item').first().getByRole('button',{name:'Start review'}).getAttribute('class'),'button primary');
  await card(204).getByRole('button',{name:'Hand back to author',exact:true}).click();
  await expectToast('#204 is waiting for the author');assert.equal(await sectionOf(204),'waiting');

  // Reminders can be set and cleared on waiting PRs.
  await card(207).locator('.queue-remind > summary').click();
  await card(207).getByRole('button',{name:'3 days',exact:true}).click();
  await expectToast('#207 comes back to you');
  assert.equal(await card(207).locator('.queue-remind-set').count(),1);
  await card(207).locator('.queue-remind > summary').click();
  await card(207).getByRole('button',{name:'Clear reminder',exact:true}).click();
  await expectToast('Reminder for #207 cleared.');
  assert.equal(await card(207).locator('.queue-remind-set').count(),0);
  assert.equal(await card(207).locator('.queue-remind-label').textContent(),'Remind me');

  // Snooze sets aside a PR on your turn; Bring back now returns it to Up next.
  await card(205).locator('.queue-snooze > summary').click();
  await card(205).getByRole('button',{name:'1 day',exact:true}).click();
  await expectToast('#205 is snoozed until');
  assert.equal(await sectionOf(205),'snoozed');
  assert.match(await page.locator('#queue-summary').textContent(),/ · 2 snoozed$/);
  assert.match(await card(205).locator('.queue-status').textContent(),/You snoozed it.*💤 Back/);
  await page.locator('#queue-snoozed > summary').click();
  await card(205).getByRole('button',{name:'Bring back now',exact:true}).click();
  await expectToast('#205 is back in Up next.');assert.equal(await sectionOf(205),'up_next');

  // Stop tracking keeps the PR visible under Finished; Track again restores it.
  await card(205).locator('.pr-overflow > summary').click();
  await card(205).getByRole('button',{name:'Stop tracking',exact:true}).click();
  await expectToast('Stopped tracking #205. It stays under Finished.');
  await toast.getByRole('button',{name:'Show'}).click();
  assert.equal(await sectionOf(205),'removed');assert.equal(await page.locator('#queue-removed').evaluate(el=>el.open),true);
  await card(205).getByRole('button',{name:'Track again',exact:true}).click();
  await expectToast('#205 is back in Up next.');assert.equal(await sectionOf(205),'up_next');

  // Search finds any tracked PR, including finished ones, and shows where it is.
  await page.fill('#queue-search','json flag');
  assert.equal(await page.locator('#queue-list .queue-item').count(),1);
  assert.equal(await page.locator('.queue-section-pill').textContent(),'Merged or closed');
  await page.locator('#queue-list').getByRole('button',{name:'Show',exact:true}).click();
  assert.equal(await page.inputValue('#queue-search'),'');assert.equal(await sectionOf(209),'history');

  // Moves made outside this tab (GitHub sync, reminders) are announced with Show.
  const snapshot=await (await context.request.get(origin+'/api/state')).json();
  const moved=snapshot.prs.find(item=>item.url===pr(207));
  moved.workflow={...moved.workflow,bucket:'attention',reasons:[{kind:'reminder',label:'Your reminder is due',url:pr(207)}]};
  await page.route('**/api/state',route=>route.fulfill({json:snapshot}));
  await page.evaluate(()=>loadState());
  await expectToast('#207 is back to you: your reminder is due.');
  // A woken snooze is announced and offers to continue or snooze again.
  const woken=snapshot.prs.find(item=>item.url===pr(206));
  woken.workflow={...woken.workflow,bucket:'attention',snoozed_until:new Date(Date.now()-60000).toISOString(),reasons:[{kind:'snooze',label:'Your snooze ended',url:pr(206)}]};
  await page.evaluate(()=>loadState());
  await expectToast('#206 is back to you: your snooze ended.');
  assert.equal(await card(206).getByRole('button',{name:'Start review',exact:true}).getAttribute('class'),'button primary');
  assert.equal(await card(206).locator('.queue-snooze .queue-remind-label').textContent(),'Snooze again');
  await page.unroute('**/api/state');await page.evaluate(()=>loadState());

  for(const [width,scheme] of [[390,'dark'],[1440,'light']]){
   await page.setViewportSize({width,height:1000});await page.emulateMedia({colorScheme:scheme});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`page overflow at ${width}`);
  }
  assert.deepEqual(errors,[]);
  console.log('My reviews browser checks passed: lanes, collapse persistence, move reasons, toasts with Show/Undo, pause, reminders, snooze, stop tracking, search and automatic-move notices.');
 } finally {
  await browser?.close();fixture.kill();
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
