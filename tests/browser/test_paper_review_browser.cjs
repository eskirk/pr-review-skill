'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawnSync}=require('node:child_process');
const root=path.resolve(__dirname,'../..'),output=process.env.PR_REVIEW_TEST_OUTPUT||fs.mkdtempSync(path.join(os.tmpdir(),'paper-review-'));
fs.mkdirSync(output,{recursive:true});
const python=`
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()/'scripts'))
from render_review import render
out=Path(sys.argv[1]); repo=Path.cwd()
base,head=(subprocess.check_output(['git','rev-parse',r],text=True).strip() for r in ('HEAD~1','HEAD'))
visual={'type':'sequence','title':'Call order','caption':'Source-traced example.','steps':[{'from':'Reader','to':'Page','message':'Open the report.'},{'from':'Page','to':'Reader','message':'Display the result.'}]}
stepper={'type':'stepper','title':'Follow the calls','caption':'Reader-controlled steps.','visual':visual,'steps':[{'label':'Open','text':'The reader opens the report.','focus':[1]},{'label':'Read','text':'The reader sees the result.','focus':[1,2],'finding':'Finding 1'}]}
flow={'type':'stepper','title':'Follow the data','caption':'All nodes remain visible.','visual':{'type':'flow','title':'Data path','caption':'Source-traced example.','steps':[{'label':'Input','detail':'Read data.'},{'label':'Output','detail':'Return data.'}]},'steps':[{'label':'Input','text':'The page reads data.','focus':[1]},{'label':'Output','text':'The page returns data.','focus':[2]}]}
mermaid={'type':'stepper','title':'Draw the messages','caption':'Messages use their rendered hooks.','visual':{'type':'mermaid','source':'sequenceDiagram\\nparticipant A as Reader\\nparticipant B as Page\\nparticipant C as Store\\nA->>B: Open report with a long message label that wraps across multiple lines before the second message\\nB->>C: Read saved filters\\nC-->>B: Return filters'},'steps':[{'label':'Open','text':'The reader opens the report.'},{'label':'Read','text':'The page reads stored filters.'},{'label':'Return','text':'The store returns filters.'}]}
chart={'type':'stepper','title':'Draw the connections','caption':'Focused nodes share an accented edge.','visual':{'type':'mermaid','source':'flowchart LR\\nread_node[Read] link@--> write_node[Write]\\nwrite_node --> done[Done]'},'steps':[{'label':'Read','text':'The page reads data.'},{'label':'Write','text':'The page writes data.','focus':['read_node','write_node']},{'label':'Done','text':'The page finishes.'}]}
diagram={'type':'stepper','title':'Draw the handoff','caption':'Authored ids select graphic elements.','visual':{'type':'diagram','caption':'An inert SVG handoff.','html':'<svg viewBox="0 0 420 130" role="img" aria-label="Input passes to output"><g id="dg-input"><rect x="8" y="30" width="110" height="60" rx="8" fill="none" stroke="currentColor"/><text x="63" y="65" text-anchor="middle" fill="currentColor">Input</text></g><path id="dg-handoff" d="M130 60 L285 60 M276 52 L285 60 L276 68" fill="none" stroke="currentColor" stroke-width="2"/><g id="dg-output"><rect x="300" y="30" width="110" height="60" rx="8" fill="none" stroke="currentColor"/><text x="355" y="65" text-anchor="middle" fill="currentColor">Output</text></g></svg>'},'steps':[{'label':'Input','text':'The page receives data.'},{'label':'Handoff','text':'The data crosses to the output.'},{'label':'Output','text':'The page returns data.'}]}
html_diagram={'type':'stepper','title':'Follow HTML kit nodes','caption':'Nested ids preserve focused descendants.','visual':{'type':'diagram','caption':'Responsive diagram kit.','html':'<div class="dg-row" id="dg-html-shell"><div class="dg-node" id="dg-html-in">Input</div><div class="dg-arrow dg-arrow-right"></div><div class="dg-node" id="dg-html-out">Output</div></div>'},'steps':[{'label':'Input','text':'The input arrives.','focus':['dg-html-in']},{'label':'Output','text':'The output is ready.','focus':['dg-html-out']}]}
excerpt={'type':'source','path':'scripts/render_review.py','start':1,'end':4,'caption':'Exact pinned source.'}
walk={'type':'code_walk','items':[{'path':'scripts/render_review.py','tag':'changed','text':'The renderer prepares a report so the reader can follow each call and inspect the source while keeping the current explanation and its full drawing together on screen.','diff':[excerpt]},{'path':'demo.py','tag':'new','text':'An example calls the renderer.','diff':[{'type':'example','code':'render(data)','caption':'Illustrative call.'}]}]}
for layout in ('classic','walk','paper'):
 data={'layout':layout,'title':'Readers follow a continuous report','outcome':'Readers can inspect the explanation and exact code.','repository':str(repo),'base':base,'head':head,'stack':'Python','mode':'Brief · Small','glance':{'kind':'ui','blast':'contained','blast_reason':'Only report presentation changes.'},'background':{'story':'Reports explain pinned source.','terms':[{'term':'Pinned','meaning':'A fixed commit.'}]},'sections':[{'id':'change','title':'The change','claim':'The whole visual stays visible','blocks':[stepper,mermaid,chart,diagram,html_diagram,{'type':'details','title':'Optional data path','blocks':[flow]}]},{'id':'code','title':'Code','claim':'Excerpts remain exact','blocks':[walk]}],'review':{'base':base,'head':head,'assessment':'Illustrative renderer fixture.','markdown':'<details class="review-finding">\\n<summary>P3 · Demonstration finding</summary>\\n\\n**The problem in one sentence:** The sample illustrates a finding link.\\n\\n</details>'},'evidence':{'claims':['Renderer test fixture.']},'verification':'Fixture coverage.'}
 if layout=='paper': data['outcome']='Readers inspect the explanation. Readers can open exact code. Readers control each step.'
 if layout=='paper':
  prose=[data['outcome'],data['background']['story']]+[value for term in data['background']['terms'] for value in term.values()]
  def authored(blocks):
   for block in blocks:
    if block['type']=='stepper':
     for step in block['steps']:prose.extend([step['label'],step['text']])
    elif block['type']=='code_walk':
     if block.get('example'):prose.append(block['example'])
     prose.extend(item['text'] for item in block['items'])
    elif block['type']=='details':authored(block['blocks'])
    elif block['type']=='paragraph':prose.append(block['text'])
  for section in data['sections']:authored(section['blocks'])
  (out/'expected-prose.json').write_text(json.dumps(sum(len(part.split()) for part in prose)))
 (out/(layout+'.json')).write_text(json.dumps(data));(out/(layout+'.html')).write_text(render(data))
new=json.loads(json.dumps(data));new.pop('background');new['outcome']='Readers inspect a continuous report.'
new['why']={'text':'The previous report hid the reason for the change.','sources':[{'label':'PR description','url':'https://example.com/pr'}],'inferred':False}
new['orientation']={'open':False,'teaser':'Where the renderer sits','map':[{'label':'Author','changed':False},{'label':'Renderer','name':'render','changed':True},{'label':'Reader','changed':False}],'story':'The author writes a report and the reader opens it.','compare':'Like a document compiler, except the source remains embedded.','terms':[{'term':'Pinned','meaning':'A fixed revision.'}]}
new['glance']['judgment']=[{'text':'Should optional context start closed?','section':'change'}]
new['sections'][0]['approach']={'text':'Why not put all context in the standfirst?','suggested':True}
new['sections'][0]['blocks'].append({'type':'cases','columns':['Situation','Before','After'],'caption':'Both outcomes stay visible on phones.','rows':[{'situation':'First visit','cells':[{'text':'Context always visible.'},{'text':'Context opens on demand.'}]}]})
new['sections'][0]['blocks'].append({'type':'diagram','caption':'Wide labels stay readable on phones.','html':'<svg viewBox="0 0 1600 140" role="img" aria-label="Wide labels"><text x="10" y="70" font-size="14">Start the report</text><text x="1400" y="70" font-size="14">Read the result</text></svg>'})
new['sections'][1]['blocks'][0]['items'][0]['diff']=[{**excerpt,'side':'base','open':True},{**excerpt,'open':True}]
new['sections'].append({'id':'blast','title':'Blast radius','claim':'Report readers see the change','blocks':[{'type':'paragraph','text':'The source repository remains read only.'}]})
new['review']['markdown']+='\\n\\n'+new['review']['markdown']+'\\n\\n'+new['review']['markdown']
prose=[new['outcome'],new['why']['text']]+[item['text'] for item in new['glance']['judgment']]
for section in new['sections']:
 authored(section['blocks'])
 if 'approach' in section:prose.append(section['approach']['text'])
(out/'round3-prose.json').write_text(json.dumps(sum(len(part.split()) for part in prose)))
for opened in (False,True):
 new['orientation']['open']=opened;name='round3-'+str(opened).lower()
 (out/(name+'.json')).write_text(json.dumps(new));(out/(name+'.html')).write_text(render(new))
data['layout']='walk';data['sections']=[{'id':'messages','title':'Messages','claim':'Wrapped labels keep their messages','blocks':[mermaid['visual']]}]
(out/'inspector.html').write_text(render(data))
# The cap fixture has an exact prose count; all other text is excluded.
for name,layout,kind,words in [('docs-warn','paper','docs',251),('docs-fail','paper','docs',376),('lifecycle-pass','paper','lifecycle',376),('classic-pass','classic','docs',376)]:
 data['layout']=layout;data['glance']['kind']=kind;data['outcome']='Outcome.';data.pop('background',None)
 data['review']['markdown']='No findings. '+('evidence '*700);data['review'].update(assessment='Assessment. '+('scope '*200),verdict={'complete':True,'traced':True,'tests':'pass','runtime':'validated','why':['Fixture.'],'checked':['Fixture.']})
 data['sections']=[{'id':'prose','title':'Ignored heading','claim':'Ignored heading', 'blocks':[{'type':'paragraph','text':'word '*(words-1)}]}]
 data['verification']='Excluded. '+('verification '*700)
 (out/(name+'.json')).write_text(json.dumps(data));(out/(name+'.html')).write_text(render(data))
`;
(async()=>{try{
 const fixture=spawnSync(process.env.PYTHON||'python3',['-c',python,output],{cwd:root,encoding:'utf8'});
 assert.equal(fixture.status,0,fixture.stderr);
 const env={...process.env,PR_REVIEW_PLAYWRIGHT_MODULE:process.env.PR_REVIEW_PLAYWRIGHT_MODULE||require.resolve('../../scripts/report-runtime/node_modules/playwright-core'),PR_REVIEW_CHROME_PATH:process.env.PR_REVIEW_CHROME_PATH||require('../../scripts/report-runtime/chrome.cjs').chromePath()};
 for(const layout of ['classic','walk','paper']){
  const checked=spawnSync(process.execPath,[path.join(root,'scripts/check_review.cjs'),path.join(output,layout+'.html'),path.join(output,layout+'-check'),path.join(output,layout+'.json')],{cwd:root,env,encoding:'utf8',timeout:90000});
  assert.equal(checked.status,0,checked.stdout+'\n'+checked.stderr);
  const result=JSON.parse(fs.readFileSync(path.join(output,layout+'-check/validation.json'),'utf8'));
  assert.equal(result.steppers,6);assert.equal(result.sourceExcerpts,1);assert.equal(result.codeWalkItems,2);assert.deepEqual(result.errors,[]);assert.ok(!result.warnings.some(w=>w.includes('exceed 30 words')),result.warnings.join('\n'));
  if(layout==='paper'){assert.equal(result.explanationWords,JSON.parse(fs.readFileSync(path.join(output,'expected-prose.json'),'utf8')),'Count step notes and code-walk prose; exclude labels, paths and excerpts');assert.ok(result.warnings.includes('Paper outcome exceeds two sentences or 40 words.'));assert.equal(result.themes[0].background,'rgb(239, 235, 226)');assert.equal(result.themes[1].background,'rgb(18, 17, 14)');}
 }
 for(const name of ['round3-false','round3-true','docs-warn','docs-fail','lifecycle-pass','classic-pass']){
  const checked=spawnSync(process.execPath,[path.join(root,'scripts/check_review.cjs'),path.join(output,name+'.html'),path.join(output,name+'-check'),path.join(output,name+'.json')],{cwd:root,env,encoding:'utf8',timeout:90000});
  const result=JSON.parse(fs.readFileSync(path.join(output,name+'-check/validation.json'),'utf8'));
  assert.equal(checked.status,name==='docs-fail'?1:0,checked.stdout+'\n'+checked.stderr);
  if(name.startsWith('round3')){
   assert.ok(result.warnings.some(w=>w.includes('fewer than 4 words')));
   assert.ok(!result.warnings.some(w=>w.includes('SVG text renders below 10px')),result.warnings.join('\n'));
  }else{
   if(name!=='classic-pass')assert.equal(result.explanationWords,name==='docs-warn'?251:376,'Only authored explanation prose counts toward the cap');
   assert.equal(result.explanationTarget,name.startsWith('docs')?250:name==='lifecycle-pass'?600:800);
  }
  if(name==='docs-warn')assert.ok(result.warnings.some(w=>w.includes('251 > 250')));
  if(name==='docs-fail')assert.ok(result.errors.some(w=>w.includes('376 > 375')));
 }
 const {chromium}=require(env.PR_REVIEW_PLAYWRIGHT_MODULE);
 const browser=await chromium.launch({executablePath:env.PR_REVIEW_CHROME_PATH,args:['--no-sandbox']});
 try{
  const page=await browser.newPage();await page.goto(require('node:url').pathToFileURL(path.join(output,'inspector.html')).href);
  assert.match(await page.locator('.walk-rail-note').innerText(),/Click a diagram participant/);
  const labels=page.locator('.messageText'),all=await labels.allTextContents();
  assert.ok(all.length>3,'Wrapped-label regression fixture must have multiple label lines');
  await page.locator('[data-et=participant][data-id=C]').click();
  assert.deepEqual(await page.locator('.messageText.dim').allTextContents(),all.slice(0,-2),'All wrapped first-message label lines must dim together');
  await page.locator('[data-et=participant][data-id=A]').click();
  assert.deepEqual(await page.locator('.messageText.dim').allTextContents(),all.slice(-2),'Later messages must retain their own label mapping');
  await page.goto(require('node:url').pathToFileURL(path.join(output,'walk.html')).href);
  assert.doesNotMatch(await page.locator('.walk-rail-note').innerText(),/Click a diagram participant/);
  const closed=JSON.parse(fs.readFileSync(path.join(output,'round3-false-check/validation.json'),'utf8'));
  const opened=JSON.parse(fs.readFileSync(path.join(output,'round3-true-check/validation.json'),'utf8'));
  assert.equal(closed.explanationWords,JSON.parse(fs.readFileSync(path.join(output,'round3-prose.json'),'utf8')),'Why, judgment and approach prose count exactly');
  assert.equal(opened.explanationWords-closed.explanationWords,31,'Only initially open orientation counts; labels, names, story, compare and terms count');
  await page.goto(require('node:url').pathToFileURL(path.join(output,'round3-false.html')).href);
  for(const width of [1280,999,390]){
   await page.setViewportSize({width,height:900});await page.waitForTimeout(100);
   const pair=await page.locator('.paper-excerpt-pair > figure').evaluateAll(items=>items.map(e=>e.getBoundingClientRect().toJSON()));
   assert.equal(pair.length,2);assert.equal(pair[0].y===pair[1].y,width>=1000,'Base/head pair responds at 1000px');
   if(width===390){
    assert.ok(await page.locator('.paper-diagram-hint').evaluateAll(items=>items.some(e=>!e.hidden)),'Wide diagrams advertise scrolling');
    const cells=await page.locator('.cases tbody td').evaluateAll(items=>items.map(e=>({box:e.getBoundingClientRect().toJSON(),label:e.dataset.label})));
    assert.equal(cells[0].label,'Before');assert.equal(cells[1].label,'After');assert.ok(cells[1].box.y>cells[0].box.y);
    assert.ok(cells.every(e=>e.box.x>=0&&e.box.right<=390));
   }
  }
 }finally{await browser.close();}
 console.log('Paper review browser checks passed: paper/classic/walk, all five visual types, SVG/HTML, numbered notes/markers, instant focus, keyboard/buttons, print/no-JS, exact source, light/dark and 390/1280px.');
}finally{if(!process.env.PR_REVIEW_TEST_OUTPUT)fs.rmSync(output,{recursive:true,force:true});}})().catch(error=>{console.error(error);process.exitCode=1;});
