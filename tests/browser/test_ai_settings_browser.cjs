'use strict';
const {spawn}=require('node:child_process'),{once}=require('node:events'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PR_REVIEW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const fixture=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'../fixtures/triage_browser_fixture.py')],{stdio:['ignore','pipe','inherit']});let browser;
 try{
  const [chunk]=await once(fixture.stdout,'data'),url=chunk.toString().trim();
  browser=await chromium.launch({headless:true,channel:'chrome'});
  const page=await browser.newPage({viewport:{width:1360,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);await page.waitForSelector('.pr-row');await page.click('#settings-show');
  assert.equal(await page.locator('.feature-card').count(),3);
  const known=page.getByLabel('Repositories',{exact:true});
  await known.fill('https://github.com/owner/repo');
  assert.equal(await known.evaluate(input=>input.checkValidity()),false);
  assert.match(await page.locator('#known-repositories-error').textContent(),/owner\/repo/);
  await page.click('#ai-save');assert.equal(await page.evaluate(()=>state.ai.settings.known_repositories.length),0);
  await known.fill(Array.from({length:201},(_,i)=>`owner/repo${i}`).join('\n'));
  assert.match(await page.locator('#known-repositories-error').textContent(),/200/);
  await page.click('#ai-discard');assert.equal(await known.inputValue(),'');
  await page.selectOption('#triage-provider','claude');
  assert.equal(await page.inputValue('#triage-model'),'claude-haiku-5-5');
  assert.equal(await page.isDisabled('#triage-effort'),false);
  await page.selectOption('#chat-provider','claude');await page.selectOption('#chat-effort','max');
  await page.selectOption('#chat-provider','codex');await page.selectOption('#chat-provider','claude');
  assert.equal(await page.inputValue('#chat-effort'),'max');
  await page.selectOption('#chat-model','claude-haiku-4-5-20251001');
  assert.equal(await page.inputValue('#chat-effort'),'');assert.equal(await page.isDisabled('#chat-effort'),true);
  await page.click('#ai-discard');assert.equal(await page.inputValue('#triage-provider'),'codex');
  await page.selectOption('#triage-provider','claude');await page.selectOption('#review-provider','codex');await page.selectOption('#review-model','gpt-6-astra');await page.selectOption('#review-effort','high');await page.selectOption('#chat-provider','claude');
  await known.focus();await page.keyboard.insertText(' Example/Repo \nexample/REPO\nGrafana/faro-web-sdk');
  await page.locator('#ai-save').focus();await page.keyboard.press('Enter');await page.waitForFunction(()=>!settingsDirty&&!aiSaving);
  const settings=await page.evaluate(()=>state.ai.settings);
  assert.equal(settings.triage.provider,'claude');assert.equal(settings.review.provider,'codex');assert.equal(settings.chat.provider,'claude');
  assert.deepEqual(settings.known_repositories,['example/repo','grafana/faro-web-sdk']);
  await page.reload();await page.waitForSelector('.pr-row');await page.click('#settings-show');
  assert.equal(await page.inputValue('#chat-model'),'claude-sonnet-5-5');
  assert.equal(await known.inputValue(),'example/repo\ngrafana/faro-web-sdk');
  // Dirty windows retain their draft and revision across background polling.
  await page.selectOption('#chat-effort','high');
  await known.fill('local/draft');
  await page.evaluate(async()=>{const updated=structuredClone(state.ai.settings);updated.review.profiles.codex.effort='max';updated.known_repositories=['other/window'];await post('/ai-config',{settings:updated,revision:state.ai.revision});await loadState();});
  await page.click('#ai-save');await page.waitForFunction(()=>!aiSaving);
  assert.match(await page.locator('#toast').textContent(),/another window/);
  assert.equal(await page.inputValue('#chat-effort'),'high');
  assert.equal(await known.inputValue(),'local/draft');
  await page.click('#ai-discard');assert.equal(await page.inputValue('#review-effort'),'max');
  assert.equal(await known.inputValue(),'other/window');
  await known.fill('');await page.click('#ai-save');await page.waitForFunction(()=>!settingsDirty&&!aiSaving);
  assert.deepEqual(await page.evaluate(()=>state.ai.settings.known_repositories),[]);
  const fs=require('node:fs'),output=require('node:os').tmpdir()+'/pr-review-ai-settings';fs.mkdirSync(output,{recursive:true});
  for(const theme of ['light','dark'])for(const width of [1360,390,320]){
   await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);await page.setViewportSize({width,height:1000});
   assert.ok(await page.evaluate(()=>document.querySelector('#settings').scrollWidth<=document.querySelector('#settings').clientWidth),`settings overflow ${theme}/${width}`);
   await known.scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(output,`${theme}-${width}.png`)});
  }
  assert.deepEqual(errors,[]);console.log('AI settings: repository validation, keyboard save/reload, clearing, mixed providers, profile memory, reasoning compatibility, atomic save, stale-window protection, discard and responsive light/dark layouts passed.');
 }finally{await browser?.close();fixture.kill('SIGTERM');await once(fixture,'exit');}
})().catch(error=>{console.error(error);process.exitCode=1;});
