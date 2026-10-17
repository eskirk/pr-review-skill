/* Browser regression suite, using the production routes and isolated boundaries. */
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
  const page=await browser.newPage({viewport:{width:880,height:1000}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(output.toString().trim());
  await page.locator('#file-0 [data-line="head"]').first().waitFor();
  await page.locator('#diff-layout').selectOption('split');
  assert.equal(await page.locator('#file-0 .split-pane').count(),2);
  // Side by side must remain usable with the Files panel occupying part of a narrow window.
  assert.equal(await page.locator('#files-toggle').getAttribute('aria-expanded'),'true');
  assert.equal(await page.locator('#diff-layout').inputValue(),'split');
  await page.reload();await page.locator('#file-0 .split-pane').first().waitFor();
  assert.equal(await page.locator('#diff-layout').inputValue(),'split');
  await page.locator('#file-0').getByRole('button',{name:'Select head line 40',exact:true}).click();
  await page.locator('#ask-selection').click();
  await page.locator('#question').fill('Explain this guard');
  await page.locator('#send-question').click();
  await page.locator('.message.streaming').waitFor();
  assert.match(await page.locator('.message.streaming').innerText(), /Streaming answer/);
  assert.equal(await page.locator('.message.streaming script').count(),0);
  await page.locator('[data-save-message="1"]').waitFor();
  assert.equal(await page.locator('.message-sources a').getAttribute('href'),'https://www.w3.org/TR/trace-context/');
  assert.equal(await page.locator('.message script').count(),0);
  const thread=new URL(page.url()).searchParams.get('chat');assert.ok(thread);
  // The chat rail hides navigation at this width; reopen Files before switching.
  await page.locator('#files-toggle').click();
  await page.locator('#file-tree button').nth(1).click();
  await page.locator('#file-1').getByRole('button',{name:'Select head line 20',exact:true}).click();
  await page.locator('#ask-selection').click();
  await page.locator('#question').fill('Keep this draft');
  await page.locator('[data-remove-context="0"]').click();
  assert.equal(await page.locator('#question').inputValue(),'Keep this draft');
  assert.equal(await page.locator('.context-attachment').count(),1);
  assert.equal(await page.locator('.message').count(),2);
  await page.locator('#question').fill('What test is missing?');
  await page.locator('#send-question').click();
  await page.waitForFunction(()=>document.getElementById('chat-status').textContent.includes('Connecting to Codex'));
  assert.match(await page.locator('#chat-status').innerText(),/\d+s/);
  await page.locator('[data-save-message="3"]').waitFor();
  await page.locator('#chat-activity summary').click();
  assert.match(await page.locator('#chat-activity-items').innerText(),/Reading.*types\.ts/);
  assert.equal(new URL(page.url()).searchParams.get('chat'),thread);
  await page.locator('[data-save-message="3"]').click();
  await page.locator('#notes-toggle').click();
  await page.locator('.saved-note').waitFor();
  await page.locator('#close-rail').click();
  await page.locator('#file-1 [data-viewed]').check();
  // Navigation waits for serialized server saves; no arbitrary sleep.
  await page.locator('#refresh-comparison').click();
  await page.waitForURL(url=>!url.searchParams.has('chat'));
  await page.locator('#file-1 [data-viewed]').waitFor();
  assert.equal(await page.locator('#file-1 [data-viewed]').isChecked(),true);
  await page.locator('#chat-toggle').click();
  await page.locator('#thread-picker').selectOption(thread);
  assert.equal(await page.locator('.message').count(),4);
  await page.locator('#review-tab').click();
  await page.frameLocator('.review-frame').getByRole('heading',{name:'Fixture AI review'}).waitFor();
  assert.equal(await page.locator('.review-frame').getAttribute('sandbox'),'allow-scripts allow-popups allow-popups-to-escape-sandbox');
  // Continuing copies the finished review's fork command or a handoff prompt.
  await page.context().grantPermissions(['clipboard-read','clipboard-write'],{origin:new URL(page.url()).origin});
  await page.getByRole('button',{name:'Continue in Claude Code'}).click();
  await page.locator('#workspace-toast',{hasText:'Paste it into a terminal'}).waitFor();
  assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'cd /tmp/reviews && claude --resume 4c099c4b-400d-4914-a857-53605e88f11a --fork-session');
  await page.getByRole('button',{name:'Copy handoff prompt'}).click();
  await page.locator('#workspace-toast',{hasText:'Handoff prompt copied'}).waitFor();
  assert.match(await page.evaluate(()=>navigator.clipboard.readText()),/^Pick up where an earlier Claude Code review left off\.\nSession ID: 4c099c4b/);
  // Guided launches post the steering text from a dialog that survives report refreshes.
  const launches=[];
  await page.route('**/regenerate-review',async route=>{launches.push(route.request().postDataJSON());await route.fulfill({json:{run_id:'guided-run',existing:false,transport:'in-app'}});});
  await page.locator('#generate-review-guided').click();
  await page.locator('#guidance-sources [data-guidance-note]').first().check();
  await page.locator('#guidance-sources [data-guidance-conversation]').first().check();
  await page.locator('#guidance-text').fill('Only iOS changed; validate on iOS.');
  await page.locator('#guidance-deep').check();
  await page.locator('#guidance-form [type=submit]').click();
  await page.waitForFunction(()=>!document.getElementById('guidance-dialog').open);
  assert.equal(launches.length,1);
  assert.equal(launches[0].guidance,'Only iOS changed; validate on iOS.');
  assert.equal(launches[0].deep_explanation,true);
  assert.equal(launches[0].workspace_context.notes.length,1);
  assert.equal(launches[0].workspace_context.conversations.length,1);
  await page.unroute('**/regenerate-review');
  await page.locator('#code-tab').click();
  await page.locator('#question').fill('Cancel this question');
  await page.locator('#send-question').click();await page.locator('#stop-chat').click();
  await page.waitForFunction(()=>document.getElementById('chat-status').textContent==='Stopped.');
  for(const width of [1440,880,390,320]){
   await page.setViewportSize({width,height:950});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`overflow ${width}`);
   assert.equal(await page.locator('#diff-layout').inputValue(),'split');
  }
  assert.deepEqual(errors,[]);
  console.log('Workspace browser checks passed: layouts, source selection, durable chat/notes/viewed state, cancellation, report sandbox and responsive layout.');
 }finally{if(browser)await browser.close();fixture.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
