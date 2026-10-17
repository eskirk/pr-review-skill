#!/usr/bin/env node
'use strict';
const fs=require('fs');const path=require('path');const {pathToFileURL}=require('url');const {execFileSync}=require('child_process');
const runtime=path.join(__dirname,'report-runtime');const {chromePath,refuseInSandbox}=require(path.join(runtime,'chrome.cjs'));
refuseInSandbox();
// The report runtime's playwright-core drives the installed Chrome; PR_REVIEW_PLAYWRIGHT_MODULE may name a full Playwright instead.
let chromium;
try{({chromium}=require(process.env.PR_REVIEW_PLAYWRIGHT_MODULE||path.join(runtime,'node_modules','playwright-core')));}
catch{console.error(process.env.PR_REVIEW_PLAYWRIGHT_MODULE?'Cannot load PR_REVIEW_PLAYWRIGHT_MODULE':'Install the report runtime: npm ci --prefix '+runtime);process.exit(2);}
const [fileArg,outputArg,inputArg]=process.argv.slice(2);
if(!fileArg||!outputArg){console.error('Usage: check_review.cjs page.html validation-directory [input.json]');process.exit(2);}
const file=path.resolve(fileArg),output=path.resolve(outputArg);fs.mkdirSync(output,{recursive:true});
const result={file,errors:[],warnings:[],words:0,sections:[],quizClicks:0,sourceExcerpts:0,screenshots:[]};
function check(ok,message){if(!ok)result.errors.push(message);}
(async()=>{
 let browser;
 try{
  const bundled=process.env.PR_REVIEW_PLAYWRIGHT_MODULE&&!process.env.PR_REVIEW_CHROME_PATH;
  browser=await chromium.launch({headless:true,...(bundled?{}:{executablePath:chromePath()})});
  const context=await browser.newContext();const requests=[];
  await context.route(/^https?:/,route=>{requests.push(route.request().url());return route.abort();});
  const page=await context.newPage();page.on('pageerror',e=>result.errors.push('Page JavaScript: '+e.message));
  await page.setViewportSize({width:1280,height:900});await page.goto(pathToFileURL(file).href);
  // Walk reports show one scene at a time: check the rail selects exactly one, then show all for the checks below.
  if(await page.evaluate(()=>document.documentElement.dataset.layout==='walk')){
   const tabs=page.locator('.walk-rail a'),count=await tabs.count();check(count>=2,'Walk layout needs a scene rail');
   for(let i=0;i<count;i++){await tabs.nth(i).click();check(await page.locator('.walk-scenes > section.walk-current').count()===1,'Scene rail does not select one scene');}
   await page.evaluate(()=>{document.documentElement.dataset.scenes='all';});
  }
  const inventory=await page.evaluate(()=>{
   const count=root=>{const it=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let node,parts=[];while(node=it.nextNode())if(!node.parentElement.closest('pre,textarea,script,style,svg,.diagram-body,.cases table,[data-exclude-count]'))parts.push(node.textContent);return parts.join(' ').trim().split(/\s+/).filter(Boolean).length;};
   const paper=document.documentElement.dataset.layout==='paper';
   const paperWords=()=>[...document.querySelectorAll('.paper-page .outcome,.paper-why,.paper-judgment,.paper-background:not(details),.paper-orientation[open],.paper-sections > section')]
    .filter(e=>!['review-findings','verification','self-check','since-last-review'].includes(e.id))
    .reduce((total,element)=>{
     const copy=element.cloneNode(true);
     if(copy.matches('.paper-orientation'))copy.append(copy.querySelector(':scope > summary > span').cloneNode(true));
     copy.querySelectorAll('h1,h2,h3,figure,pre,textarea,svg,.diagram-body,.source-meta,.code-walk-chip,.stepper-visual,.stepper-markers,.walk-finding,.walk-card,.table-hint,.caption,summary,[data-exclude-count]').forEach(e=>e.remove());
     return total+count(copy);
    },0);
   return {layout:document.documentElement.dataset.layout,kind:document.querySelector('.paper-page')?.dataset.kind,words:count(document.body),explanationWords:paper?paperWords():[...document.querySelectorAll('header[data-section],main > section,.walk-scenes > section,.paper-sections > section')].filter(e=>!['review-findings','verification','self-check','since-last-review'].includes(e.id)).reduce((n,e)=>n+count(e),0)-(document.getElementById('review-assessment')?count(document.getElementById('review-assessment')):0),mode:document.documentElement.dataset.mode,sections:[...document.querySelectorAll('[data-section]')].map(e=>({section:e.dataset.section,words:count(e)})),csp:document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.content,assets:[...document.querySelectorAll('script[src],link[rel=stylesheet],iframe,form,img[src]')].map(e=>e.outerHTML),links:[...document.querySelectorAll('a')].map(a=>({href:a.getAttribute('href'),target:a.target,rel:a.rel,reviewNotes:a.classList.contains('review-notes-link')})),long:[...document.querySelectorAll('p,li')].filter(e=>!e.closest('pre,svg,.diagram-body')&&!e.querySelector('p,li')).flatMap(e=>{const copy=e.cloneNode(true);copy.querySelectorAll('.code-walk-chip,summary,details,[data-exclude-count]').forEach(n=>n.remove());return copy.textContent.trim().split(/(?<=[.!?])\s+/).filter(s=>s.split(/\s+/).length>30);}),whitespace:[...document.querySelectorAll('pre')].every(p=>['pre','pre-wrap'].includes(getComputedStyle(p).whiteSpace)),rows:[...document.querySelectorAll('.code-line')].map(e=>({height:e.getBoundingClientRect().height,lineHeight:parseFloat(getComputedStyle(e).lineHeight)})),sources:[...document.querySelectorAll('.source')].map(s=>({path:s.dataset.path,revision:s.dataset.revision,side:s.dataset.side,lines:[...s.querySelectorAll('.code-line')].map(l=>({number:Number(l.dataset.line),text:l.querySelector('.source-text').textContent}))}))};
  });
  result.words=inventory.words;result.sections=inventory.sections;result.mode=inventory.mode;
  const modeTarget={'Brief · Small':800,'Brief · Standard':1200,Deep:3000}[inventory.mode];check(!!modeTarget,'Missing/invalid mode');
  const kindTargets={docs:250,config:300,ci:300,deps:300,refactor:300,test:300,logic:450,ui:450,api:450,lifecycle:600,data:600};
  // Paper uses per-kind caps, except an explicitly requested Deep explainer.
  const target=inventory.layout==='paper'&&inventory.mode!=='Deep'?kindTargets[inventory.kind]:modeTarget,ceiling=(target||0)*1.5;
  if(inventory.layout==='paper')check(!!target,'Missing/invalid paper change kind');
  check(inventory.explanationWords<=ceiling,'Explanation prose exceeds hard limit: '+inventory.explanationWords+' > '+ceiling+' (target '+target+')');
  if(target&&inventory.explanationWords>target&&inventory.explanationWords<=ceiling)result.warnings.push('Explanation prose is over target: '+inventory.explanationWords+' > '+target+'; trim repetition if possible without dropping essential caveats.');
  result.explanationWords=inventory.explanationWords;result.explanationTarget=target;

  if(inventory.long.length)result.warnings.push(inventory.long.length+' sentences/paragraph fragments exceed 30 words; inspect readability without dropping essential conditions.');
  check(inventory.csp?.includes("default-src 'none'")&&inventory.csp?.includes("connect-src 'none'")&&inventory.csp?.includes("base-uri 'none'")&&inventory.csp?.includes("form-action 'none'"),'Missing restrictive CSP');
  check(!inventory.assets.length,'External assets, images, frames, or forms present');check(inventory.whitespace,'Code block does not preserve whitespace');check(inventory.rows.every(r=>r.height===0||Math.abs(r.height-r.lineHeight)<1),'Source rows have extra vertical spacing');
  const attachments=inputArg?(JSON.parse(fs.readFileSync(inputArg,'utf8')).attachments||[]).map(p=>pathToFileURL(fs.realpathSync(p)).href):[];
  for(const link of inventory.links){if(link.href.startsWith('#'))check(await page.locator('[id="'+link.href.slice(1)+'"]').count()===1,'Unresolved section link: '+link.href);else{check(link.href.startsWith('https://')||attachments.includes(link.href),'Unapproved source/artifact navigation');check(link.target==='_blank'&&link.rel.includes('noopener')&&link.rel.includes('noreferrer'),'Missing safe navigation attributes');}}
  const sourceInput=inputArg?JSON.parse(fs.readFileSync(inputArg,'utf8')):null;
  if(sourceInput){
   const captions=[];
   const visit=value=>{
    if(Array.isArray(value)){value.forEach(visit);return;}
    if(!value||typeof value!=='object')return;
    if(['source','example'].includes(value.type)&&typeof value.caption==='string')captions.push(value.caption);
    if(value.type==='code_walk')for(const item of value.items||[])if(typeof item.text==='string')captions.push(item.text);
    Object.values(value).forEach(visit);
   };visit(sourceInput.sections);visit(sourceInput.review?.visuals);
   const short=captions.filter(text=>text.trim().split(/\s+/).length<4);
   if(short.length)result.warnings.push(short.length+' code walk/excerpt captions have fewer than 4 words: '+short.map(text=>JSON.stringify(text)).join(', '));
  }
  if(sourceInput?.review?.assessment){
   const assessment=page.locator('#review-assessment');
   check(await assessment.count()===1&&await assessment.isVisible(),'Missing visible overview assessment');
   check(await assessment.locator('details,.review-comment,.scenario,.flow,.sequence,.diagram,.cases').count()===0,'Overview assessment hides caveats or contains drafts');
   const box=await assessment.boundingBox();
   check(box&&box.y+box.height<=900,'Assessment extends below first desktop viewport; inspect overview length');
   // A verdict card starts collapsed; its shortcut sits inside the body.
   const collapsed=await assessment.evaluate(e=>e.tagName==='DETAILS'&&!e.open);
   if(collapsed)await assessment.locator(':scope > summary').click();
   await assessment.locator('.findings-link').click();
   check(await page.locator('#review-findings').evaluate(e=>e.getBoundingClientRect().top>=-1&&e.getBoundingClientRect().top<innerHeight),'Overview shortcut does not reach findings');
   if(collapsed)await assessment.evaluate(e=>{e.open=false;});
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>{scrollTo(0,0);requestAnimationFrame(resolve);})));
  }
  if(sourceInput?.layout==='paper'){
   const sentenceCount=text=>text.trim().split(/(?<=[.!?])\s+/).length;
   if(sentenceCount(sourceInput.outcome)>2||sourceInput.outcome.trim().split(/\s+/).length>40)result.warnings.push('Paper outcome exceeds two sentences or 40 words.');
   check(await page.locator('.walk-rail,.walk-step').count()===0,'Paper layout has scene controls');
   check(await page.locator('.paper-sections > section').evaluateAll(items=>items.every(e=>e.getBoundingClientRect().height>0)),'Paper hides authored sections');
   if(sourceInput.orientation){
    const orientation=page.locator('.paper-orientation');
    check(await orientation.count()===1,'Missing orientation');
    check(await orientation.evaluate(e=>e.open)===sourceInput.orientation.open,'Orientation open state differs from input');
    await orientation.locator(':scope > summary').click();
    check(await orientation.evaluate(e=>e.open)!==sourceInput.orientation.open,'Orientation does not toggle');
    await orientation.locator(':scope > summary').click();
   }
   if(sourceInput.why)check(await page.locator('.paper-why .paper-source-chip').count()>0,'Missing why source/inference chip');
   else result.warnings.push('Paper report has no "why this PR exists" lead; cite the PR, issue or commit, or mark it inferred.');
   check(await page.locator('.paper-jumps a').count()>0,'Missing paper jump links');
   for(const jump of await page.locator('.paper-jumps a').all()){
    const target=await jump.getAttribute('href');
    check(await page.locator('[id="'+target.slice(1)+'"]').count()===1,'Paper jump does not resolve: '+target);
   }
  }
  if(sourceInput){for(const source of inventory.sources){
   const raw=source.revision==='working-tree'?fs.readFileSync(path.resolve(sourceInput.repository,source.path),'utf8'):execFileSync('git',['-C',sourceInput.repository,'show',source.revision+':'+source.path],{encoding:'utf8'});
   const lines=raw.split(/\r?\n/);for(const line of source.lines)check(lines[line.number-1]===line.text,'Source mismatch: '+source.path+':'+line.number);result.sourceExcerpts++;
  }}else result.warnings.push('No authoring input supplied; source fidelity not independently compared with Git.');
  check(await page.locator('#review-findings').count()===1,'Missing integrated review findings');
  const findings=page.locator('#review-findings > details.review-finding');result.findings=await findings.count();
  if(result.findings){
   check(await page.locator('details.review-finding[open]').count()===0,'Findings should start collapsed');
   for(let i=0;i<result.findings;i++){
    const summary=findings.nth(i).locator(':scope > summary');
    await summary.focus();await page.keyboard.press('Enter');
    check(await findings.nth(i).getAttribute('open')!==null,'Finding does not open with keyboard');
   }
   check(await page.locator('details.review-finding[open]').count()===result.findings,'Opening a finding closes another');
   check(await page.locator('details.review-finding details[open]').count()===0,'Nested evidence should remain collapsed');
   if(result.findings>1){
    await page.getByRole('button',{name:'Collapse all findings',exact:true}).click();
    check(await page.locator('details.review-finding[open]').count()===0,'Collapse all leaves findings open');
    await page.getByRole('button',{name:'Expand all findings',exact:true}).click();
    check(await page.locator('details.review-finding[open]').count()===result.findings,'Expand all leaves findings hidden');
   }
  }
  const comments=page.locator('.review-comment');result.comments=await comments.count();
  // Assert the exact Markdown payload, then exercise both clipboard outcomes.
  if(sourceInput){
   const expected=[];let current=null,fence=null;
   for(const line of sourceInput.review.markdown.split(/\r?\n/)){
    const token=line.trim().match(/^(`{3,}|~{3,})(.*)$/);
    if(token){if(!fence)fence=token[1];else if(token[1][0]===fence[0]&&token[1].length>=fence.length&&!token[2].trim())fence=null;}
    if(!fence&&line.trim()==='<!-- review-comment:start -->'){current=[];continue;}
    if(!fence&&line.trim()==='<!-- review-comment:end -->'){expected.push(current.join('\n').replace(/^\n+|\n+$/g,''));current=null;continue;}
    if(current)current.push(line);
   }
   // Mirrors comment_footer in render_review.py.
   const by=sourceInput.comment_attribution,footer=by?`*Posted by ${by.tool.trim()}${by.model&&by.model.trim()?` (${by.model.trim()})`:''} on ${by.person.trim()}'s behalf.*`:'';
   if(footer)expected.forEach((body,i)=>{expected[i]=body+'\n\n'+footer;});
   check(expected.length===result.comments,'Comment block count differs from input');
   for(let i=0;i<result.comments;i++)check(await comments.nth(i).locator('.comment-source').inputValue()===expected[i],'Copy payload differs from authored Markdown');
  }
  for(let i=0;i<result.comments;i++){
   const comment=comments.nth(i),button=comment.locator('.copy-comment');
   await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>{window.copiedReviewComment=value;}}}));
   await button.click();await page.waitForFunction(()=>document.querySelector('.copy-status')!==null);
   check(await page.evaluate(()=>window.copiedReviewComment)===await comment.locator('.comment-source').inputValue(),'Copy loses Markdown or includes metadata');
   await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw new Error('denied');}}}));
   await button.click();check(await comment.locator('.comment-source').isVisible(),'Missing manual-copy fallback');
   await comment.locator('.comment-source').evaluate(e=>{e.hidden=true;});
   await comment.locator('.copy-status').evaluate(e=>{e.textContent='';});
  }
  const scenarios=page.locator('.scenario');result.scenarios=await scenarios.count();
  for(let i=0;i<result.scenarios;i++){
   const scenario=scenarios.nth(i),buttons=scenario.locator('.scenario-controls button'),frames=scenario.locator(':scope > .scenario-frame');
   const n=await buttons.count();check(n>=2&&n<=5,'Scenario needs meaningful alternatives');
   check(await frames.count()===n,'Scenario controls and states differ');
   for(let j=0;j<n;j++){
    await buttons.nth(j).focus();await page.keyboard.press('Enter');
    for(let k=0;k<n;k++){
     check(await frames.nth(k).isVisible()===(j===k),'Scenario exposes the wrong state');
     check(await buttons.nth(k).getAttribute('aria-pressed')===String(j===k),'Scenario selection is not announced');
    }
   }
   await buttons.first().click();
  }
  const codeItems=page.locator('.code-walk > ol > li');result.codeWalkItems=await codeItems.count();
  for(const item of await codeItems.all()){
   await item.evaluate(e=>{for(let parent=e.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;});
   const first=item.locator('.source').first();
   if(await first.count()&&sourceInput?.layout!=='paper')check(await first.evaluate(e=>!e.closest('details')||!e.closest('details').closest('.code-walk')),'First code walk source is hidden in a disclosure');
   check(await item.locator(':scope > figure,:scope > .paper-excerpt-pair > figure').count()>0,'Code walk has no inline excerpt');
   check(await item.locator(':scope > figure .code-line,:scope > .paper-excerpt-pair .code-line').evaluateAll(items=>items.every(e=>Math.abs(e.getBoundingClientRect().height-parseFloat(getComputedStyle(e).lineHeight))<1)),'Inline code walk rows have extra vertical spacing');
  }
  const steppers=page.locator('.stepper');result.steppers=await steppers.count();
  for(let i=0;i<result.steppers;i++){
   const stepper=steppers.nth(i),texts=stepper.locator('.stepper-texts > li'),notes=stepper.locator('.stepper-note');
   await stepper.evaluate(e=>{for(let parent=e.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;});
   const n=await texts.count();check(n>=2&&n<=8,'Numbered diagram needs two to eight notes');
   check(await stepper.locator('.stepper-controls,.stepper-counter,[data-stepper]').count()===0,'Numbered diagram retains stepping controls');
   const assertStep=async j=>{
    check(await texts.evaluateAll(items=>items.every(e=>!e.hidden&&e.getBoundingClientRect().height>0)),'Numbered diagram hides notes');
    for(let k=0;k<n;k++)check(await notes.nth(k).getAttribute('aria-pressed')===String(j===k),'Note selection is not announced');
    if(j===null){check(await stepper.locator('.stepper-focus,.stepper-dim').count()===0,'Clearing retains visual highlighting');return;}
    const focus=JSON.parse(await texts.nth(j).getAttribute('data-focus'));
    const states=await stepper.locator('[data-stepper-target]').evaluateAll(items=>items.map(e=>({key:e.dataset.stepperTarget,hot:e.classList.contains('stepper-focus'),visible:e.getBoundingClientRect().height>0||e.getBoundingClientRect().width>0})));
    check(states.length===JSON.parse(await stepper.getAttribute('data-targets')).length,'Numbered diagram has missing rendered focus targets');
    check(focus.every(key=>states.some(e=>e.key===String(key)&&e.hot&&e.visible)),'Note highlights a missing or hidden focus target');
    if(await stepper.getAttribute('data-visual')!=='diagram')check(states.every(e=>e.hot===focus.some(key=>String(key)===e.key)),'Note highlights a target outside its focus');
    const companions=await stepper.evaluate((root,focus)=>{
     if(root.dataset.visual==='mermaid-flowchart'){
      const keys=JSON.parse(root.dataset.targets),named=JSON.parse(root.dataset.edges);
      return [...root.querySelectorAll('[data-et=edge]')].every(edge=>{
       const pair=keys.flatMap(from=>keys.map(to=>[from,to])).find(([from,to])=>edge.dataset.id.startsWith('L_'+from+'_'+to+'_'))||named[edge.dataset.id];
       return !pair||edge.classList.contains('stepper-focus')===pair.every(key=>focus.includes(key));
      });
     }
     if(root.dataset.visual!=='mermaid-sequence')return true;
     const messages=[...root.querySelectorAll('[data-et=message]')];
     const actors=new Set(messages.filter((e,i)=>focus.includes(i+1)).flatMap(e=>[e.dataset.from,e.dataset.to]));
     return messages.every((message,i)=>{
      const hot=focus.includes(i+1);if(message.classList.contains('stepper-focus')!==hot)return false;
      for(let label=message.previousElementSibling;label&&!label.matches('[data-et=message]');label=label.previousElementSibling){
       if(label.matches('.messageText')&&label.classList.contains('stepper-focus')!==hot)return false;
      }
      return true;
     })&&[...root.querySelectorAll('[data-et=participant]')].every(e=>e.classList.contains('stepper-focus')===actors.has(e.dataset.id));
    },focus);check(companions,'Companion label lines, participants or edges do not match note focus');
    check(await stepper.evaluate(e=>e.getAnimations({subtree:true}).length)===0,'Numbered diagram animates');
   };
   await assertStep(null);
   for(let j=0;j<n;j++){
    await notes.nth(j).click();await assertStep(j);
    await notes.nth(j).click();await assertStep(null);
    await notes.nth(j).focus();await page.keyboard.press('Enter');await assertStep(j);
    await page.keyboard.press('Space');await assertStep(null);
    const marker=stepper.locator('.stepper-marker').filter({hasText:new RegExp('^'+(j+1)+'$')}).first();
    await marker.click();await assertStep(j);await marker.click();await assertStep(null);
    await notes.nth(j).click();await page.keyboard.press('Escape');await assertStep(null);
   }
   const markerCount=(await texts.evaluateAll(items=>items.reduce((n,e)=>n+JSON.parse(e.dataset.focus).length,0)));
   check(await stepper.locator('.stepper-marker').count()===markerCount,'Focus elements are missing number badges');
   check(await stepper.locator('.stepper-marker').evaluateAll(items=>items.every(e=>{const box=e.getBoundingClientRect(),host=e.parentElement.parentElement.getBoundingClientRect();return box.top>=host.top-1&&box.bottom<=host.bottom+1;})),'Number badges are clipped vertically');
  }
  if(result.steppers){
   await page.emulateMedia({media:'print'});
   check(await page.locator('.stepper-texts > li').evaluateAll(items=>items.every(e=>e.getBoundingClientRect().height>0)),'Print hides notes');
   check(await page.locator('.stepper-markers').evaluateAll(items=>items.every(e=>getComputedStyle(e).display==='none')),'Print shows interactive badges');
   await page.emulateMedia({media:'screen'});
  }
  if(result.scenarios||result.steppers){
   const fallbackContext=await browser.newContext({javaScriptEnabled:false});
   const fallback=await fallbackContext.newPage();await fallback.goto(pathToFileURL(file).href);
   await fallback.locator('details').evaluateAll(items=>items.forEach(e=>e.open=true));
   check(await fallback.locator('.scenario-frame-label').evaluateAll(items=>items.every(e=>e.getBoundingClientRect().height>0)),'Scenario labels disappear without JavaScript');
   check(await fallback.locator('.scenario-frame').evaluateAll(items=>items.every(e=>e.getBoundingClientRect().height>0)),'Scenario content disappears without JavaScript');
   check(await fallback.locator('.scenario-controls').evaluateAll(items=>items.every(e=>e.hidden)),'Inactive scenario controls shown without JavaScript');
   check(await fallback.locator('.stepper-texts > li').evaluateAll(items=>items.every(e=>e.getBoundingClientRect().height>0)),'Stepper texts disappear without JavaScript');
   check(await fallback.locator('.stepper-controls').evaluateAll(items=>items.every(e=>e.hidden)),'Inactive numbered diagram controls shown without JavaScript');
   await fallbackContext.close();
  }
  if(await page.locator('.paper-tail').count())await page.locator('.paper-tail').evaluate(e=>{e.open=true;});
  const quiz=page.locator('.question');const count=await quiz.count();
  check(count<=(inventory.mode==='Deep'?5:3),'Too many self-checks');
  if(count){
   check(await page.locator('#quiz').getAttribute('open')===null,'Self-check should start collapsed');await page.locator('#quiz > summary').click();
   for(let q=0;q<count;q++){
    const group=quiz.nth(q);const choices=group.locator('.options button');const n=await choices.count();const answer=Number(await group.getAttribute('data-answer'));
    check(n>=2&&n<=4,'Question must have 2–4 choices');check(await group.locator('.quiz-explanation').isHidden(),'Answer explanation is exposed before choice');
    if(sourceInput){const original=sourceInput.questions[q];const correctText=await choices.nth(answer).innerText();check(correctText.slice(3)===original.options[original.answer],'Answer mapping changed during rendering');}
    for(let a=0;a<n;a++){
     await choices.nth(a).click();result.quizClicks++;check(await group.locator('.feedback').getAttribute('data-result')===(a===answer?'correct':'incorrect'),'Wrong feedback state');check((await group.locator('.feedback').innerText()).includes('Selected '+String.fromCharCode(65+a)), 'Feedback does not identify selected answer');check(await group.locator('.quiz-explanation').isVisible(),'Missing answer explanation');
    }
   }
   await page.locator('#reset-quiz').click();check(await page.locator('.options button[aria-pressed]').count()===0,'Reset retains selection');
   check((await page.locator('.feedback').allInnerTexts()).every(t=>!t),'Reset retains feedback');
   await page.locator('#quiz > summary').click();
  }
  if(await page.locator('.paper-tail').count())await page.locator('.paper-tail').evaluate(e=>{e.open=false;});
  for(const expected of ['light','dark','system']){await page.locator('#theme').click();check((await page.locator('html').getAttribute('data-theme')||'system')===expected,'Theme cycle mismatch');}
  result.themes=[];
  for(const width of [1280,390])for(const scheme of ['light','dark']){
   await page.emulateMedia({colorScheme:scheme});await page.setViewportSize({width,height:width===390?844:900});
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>{scrollTo(0,0);requestAnimationFrame(resolve);})));
   const geometry=await page.evaluate(()=>({viewport:innerWidth,width:document.documentElement.scrollWidth,background:getComputedStyle(document.body).backgroundColor,overviewBottom:document.querySelector('.outcome')?.getBoundingClientRect().bottom}));
   if(width===390){
    const tiny=await page.locator('svg text,svg tspan,svg foreignObject span,svg foreignObject p').evaluateAll(items=>items.filter(e=>{
     if(!e.textContent.trim()||!e.getBoundingClientRect().height)return false;
     const matrix=e.getScreenCTM?.()||e.closest('svg').getScreenCTM();
     return parseFloat(getComputedStyle(e).fontSize)*Math.hypot(matrix.a,matrix.b)<9.99;
    }).map(e=>e.textContent.trim()));
    if(tiny.length)result.warnings.push('SVG text renders below 10px at 390px ('+scheme+'): '+[...new Set(tiny)].join(', '));
    if(inventory.layout==='paper')check(await page.locator('.cases td').evaluateAll(items=>items.every(e=>{
     const box=e.getBoundingClientRect();return !box.height||(box.left>=0&&box.right<=innerWidth);
    })),'Paper cases hide outcomes outside the phone viewport');
   }
   if(result.steppers){
    const placement=await page.locator('.stepper').evaluateAll(items=>items.map(e=>{
     const visual=e.querySelector('.stepper-visual').getBoundingClientRect(),notes=e.querySelector('.stepper-texts').getBoundingClientRect();
     return notes.top>=visual.bottom-1;
    }));check(placement.every(Boolean),'Numbered notes are not below the diagram at '+width+'px');
    const contrasts=await page.locator('.stepper').evaluateAll(items=>items.map(e=>{
     const rgb=color=>color.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});
     const luminance=color=>rgb(color).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0);
     const probe=document.createElement('span');probe.style.color='var(--accent)';e.append(probe);
     const accent=getComputedStyle(probe).color,background=getComputedStyle(e).backgroundColor;probe.remove();
     const shape=e.querySelector('svg path.stepper-focus,svg line.stepper-focus,svg .stepper-focus rect,svg .stepper-focus polygon');
     const painted=!shape||getComputedStyle(shape).stroke===accent;
     const a=luminance(accent),b=luminance(background);return painted?(Math.max(a,b)+.05)/(Math.min(a,b)+.05):0;
    }));check(contrasts.every(value=>value>=4.5),'Stepper accent lacks 4.5:1 contrast in '+scheme+' mode');
   }
   check(geometry.width<=width,'Document overflow at '+width+'px ('+scheme+'): '+geometry.width+'px');if(width===1280)check(geometry.overviewBottom<900,'Outcome is below the first desktop viewport');result.themes.push({scheme,...geometry});
   const screenshot=path.join(output,(width===390?'phone':'desktop')+'-'+scheme+'.jpg');await page.screenshot({path:screenshot,fullPage:true,type:'jpeg',quality:80});result.screenshots.push(screenshot);
   if(result.findings){
    await findings.evaluateAll(items=>items.forEach(item=>item.open=false));
    const collapsed=path.join(output,(width===390?'phone':'desktop')+'-'+scheme+'-collapsed.jpg');await page.screenshot({path:collapsed,fullPage:true,type:'jpeg',quality:80});result.screenshots.push(collapsed);
    check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Collapsed findings cause overflow');
    await findings.evaluateAll(items=>items.forEach(item=>item.open=true));
   }
  }
  check(result.themes[0].background!==result.themes[1].background,'System theme does not respond to color scheme');
  check(requests.length===0,'Page attempted network requests');result.networkRequests=requests;
 }catch(error){result.errors.push(String(error.stack||error));}
 finally{if(browser)await browser.close();fs.writeFileSync(path.join(output,'validation.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));if(result.errors.length)process.exitCode=1;}
})();
