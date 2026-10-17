// Exercise Inbox launch controls with synthetic state and intercepted launch requests.
'use strict';
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PR_REVIEW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const fixture=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'../fixtures/workspace_browser_fixture.py')],{stdio:['ignore','pipe','inherit']});
 let browser;
 try{
  const [output]=await once(fixture.stdout,'data'),origin=output.toString().trim();
  browser=await chromium.launch({headless:true,channel:process.env.PR_REVIEW_BROWSER_CHANNEL||'chrome'});
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
  const page=await context.newPage(),errors=[],launches=[];
  page.on('pageerror',error=>errors.push(error.message));
  const snapshot=await (await context.request.get(origin+'/api/state')).json();
  const pr=snapshot.prs.find(item=>item.number===1);
  assert.ok(pr);
  pr.artifacts={};pr.run=null;pr.history=[];pr.history_total=0;
  await page.route('**/api/state',route=>route.fulfill({json:snapshot}));
  await page.route('**/api/workspace-context*',route=>route.fulfill({json:{notes:[{id:'note-context-1',preview:'Check the saved note',revision:'Current commit',selections:1}],conversations:[{id:'11111111-1111-1111-1111-111111111111',preview:'What should the review verify?',revision:'Current commit',messages:2,answers:1}],limits:{max_chars:48000}}}));
  let failNext=false;
  await page.route('**/regenerate-review',async route=>{
   assert.equal(route.request().method(),'POST');
   const body=route.request().postDataJSON();
   assert.equal(body.url,pr.url);assert.equal(body.retry,false);
   assert.ok(route.request().headers()['x-csrf-token']);
   launches.push(body);
   if(failNext){failNext=false;await route.fulfill({status:400,json:{error:'Synthetic launch failure'}});return;}
   pr.run={run_id:'synthetic-run',status:'running',tool:'claude',transport:'terminal',tasks:[],updated_at:new Date().toISOString()};
   await route.fulfill({json:{run_id:pr.run.run_id,transport:'terminal',existing:false}});
  });
  await page.goto(origin);
  const card=page.locator(`#pr-list [data-pr="${pr.url}"]`);
  await card.waitFor();
  assert.equal(await card.locator('[data-action="/regenerate-review"]').count(),1,'Inbox must offer a first AI review before notes exist');
  await card.locator('.pr-overflow > summary').click();
  await card.getByRole('button',{name:'Run AI review',exact:true}).click();
  await card.getByRole('button',{name:'AI review in progress',exact:true}).waitFor({state:'attached'});
  assert.equal(await card.getByRole('button',{name:'AI review in progress',exact:true}).isDisabled(),true);
  assert.equal(launches.length,1);

  // Existing notes still allow reruns; a rejected launch must restore the action.
  pr.run.status='completed';
  pr.artifacts={'review-html':{path:'/synthetic/review.html',freshness:'current',head_sha:'b'.repeat(40)}};
  failNext=true;
  await page.reload();await card.waitFor();
  await card.locator('.pr-overflow > summary').click();
  await card.getByRole('button',{name:'Run full AI review',exact:true}).click();
  await page.waitForFunction(()=>document.getElementById('toast').textContent.includes('Synthetic launch failure'));
  assert.equal(await card.getByRole('button',{name:'Run full AI review',exact:true}).isDisabled(),false);
  assert.equal(launches.length,2);

  for(const width of [1440,390]){
   await page.setViewportSize({width,height:1000});
   const menu=card.locator('.pr-overflow');
   if(!await menu.evaluate(element=>element.open))await menu.locator('summary').click();
   assert.equal(await card.getByRole('button',{name:'Run full AI review',exact:true}).isVisible(),true);
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`page overflow at ${width}`);
  }
  await card.getByRole('button',{name:'Run full AI review',exact:true}).click();
  await card.getByRole('button',{name:'AI review in progress',exact:true}).waitFor({state:'attached'});
  assert.equal(launches.length,3);
  assert.equal(launches[2].guidance,undefined,'Plain reruns must not send guidance');

  // Guided reruns send the typed steering text; cancelling sends nothing.
  pr.run.status='completed';
  await page.reload();await card.waitFor();
  await card.locator('.pr-overflow > summary').click();
  await card.getByRole('button',{name:'Run with guidance…',exact:true}).click();
  const dialog=page.locator('#guidance-dialog');
  await dialog.getByRole('button',{name:'Cancel',exact:true}).click();
  assert.equal(await dialog.evaluate(element=>element.open),false);
  assert.equal(launches.length,3);
  await card.locator('.pr-overflow > summary').click();
  await card.getByRole('button',{name:'Run with guidance…',exact:true}).click();
  assert.equal(await card.locator('.pr-overflow').evaluate(element=>element.open),false,'Opening guidance must close the actions menu');
  assert.equal(await page.locator('#guidance-title').textContent(),pr.title);
  await dialog.locator('[data-guidance-note]').check();
  await dialog.locator('[data-guidance-conversation]').check();
  await dialog.getByRole('checkbox',{name:/In-depth explanation/}).check();
  await dialog.getByRole('textbox').fill('Docs only; skip tests.');
  await dialog.getByRole('textbox').press('Control+Enter');
  await card.locator('[data-action="/regenerate-review"]:disabled',{hasText:'AI review in progress'}).waitFor({state:'attached'});
  assert.equal(await card.locator('[data-review-guidance]').count(),0,'Active runs must not offer guided launches');
  assert.equal(launches.length,4);
  assert.equal(launches[3].guidance,'Docs only; skip tests.');
  assert.equal(launches[3].deep_explanation,true);
  assert.deepEqual(launches[3].workspace_context,{notes:['note-context-1'],conversations:['11111111-1111-1111-1111-111111111111']});
  assert.equal(await dialog.evaluate(element=>element.open),false);

  // A finished report of an older commit offers an update, emphasised as the pre-check suggests.
  pr.run.status='completed';
  pr.artifacts={'review-html':{path:'/synthetic/review.html',freshness:'older',status:'completed',head_sha:'b'.repeat(40)}};
  pr.update_check={scope:'update',decided_by:'model',reason:'A focused <fix> for the batch parser.',findings:[{index:1,status:'likely-addressed'},{index:2,status:'untouched'}],hotspots:['Callers of parse()']};
  await page.reload();await card.waitFor();
  // The row offers the update; the side panel explains the pre-check.
  assert.equal(await card.locator('.row-ai').getByRole('button',{name:'Update AI review',exact:true}).count(),1);
  await card.locator('td.row-updated').click();
  const hint=page.locator('#pr-drawer-body .update-hint');
  assert.match(await hint.textContent(),/Update suggested: A focused <fix> for the batch parser\. 1 of 2 previous findings looks addressed; the update re-checks all of them\. Also check: Callers of parse\(\)/);
  assert.equal(await hint.locator('button.primary').textContent(),'Update AI review');
  for(const width of [1440,390]){
   await page.setViewportSize({width,height:1000});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`update hint overflow at ${width}`);
  }
  await hint.getByRole('button',{name:'Update AI review',exact:true}).click();
  await card.locator('[data-action="/regenerate-review"]:disabled',{hasText:'AI review in progress'}).waitFor({state:'attached'});
  assert.equal(await page.locator('#pr-drawer-body .update-hint').count(),0,'Active runs must not offer updates');
  assert.equal(await card.getByRole('button',{name:'Update AI review'}).count(),0);
  await page.click('#pr-drawer-close');
  assert.equal(launches.length,5);
  assert.equal(launches[4].mode,'update');
  assert.equal(launches[3].mode,undefined,'Full launches must not send a mode');

  // Fixed rules that require a full review hide the update and emphasise the full review.
  pr.run.status='completed';
  pr.update_check={scope:'full',decided_by:'rules',reason:'The PR was rebased or force-pushed since the last AI review.',findings:[],hotspots:[]};
  await page.reload();await card.waitFor();
  assert.equal(await card.getByRole('button',{name:'Update AI review'}).count(),0);
  await card.locator('td.row-updated').click();
  assert.match(await hint.textContent(),/Full review suggested: The PR was rebased/);
  assert.equal(await hint.locator('button.primary').textContent(),'Run full AI review');
  assert.deepEqual(errors,[]);
  console.log('Inbox review browser checks passed: first launch, active-run guard, rerun, failure recovery, guided rerun, update suggestions, desktop/mobile.');
 }finally{
  if(browser)await browser.close();
  const stopped=once(fixture,'exit');fixture.kill('SIGTERM');await stopped;
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
