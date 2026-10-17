'use strict';
const themeButton=document.getElementById('theme');
const modes=['system','light','dark'];let mode=0;
themeButton.addEventListener('click',()=>{mode=(mode+1)%modes.length;const selected=modes[mode];if(selected==='system')document.documentElement.removeAttribute('data-theme');else document.documentElement.setAttribute('data-theme',selected);themeButton.textContent='Theme: '+selected[0].toUpperCase()+selected.slice(1);});
for(const question of document.querySelectorAll('.question')){
 const buttons=[...question.querySelectorAll('.options button')];
 for(const [index,button] of buttons.entries())button.addEventListener('click',()=>{
  for(const other of buttons)other.removeAttribute('aria-pressed');button.setAttribute('aria-pressed','true');
  const correct=index===Number(question.dataset.answer);const feedback=question.querySelector('.feedback');
  feedback.dataset.result=correct?'correct':'incorrect';feedback.textContent='Selected '+String.fromCharCode(65+index)+'. '+(correct?'Correct.':'Not quite.');question.querySelector('.quiz-explanation').hidden=false;
 });
}
const reset=document.getElementById('reset-quiz');
if(reset)reset.addEventListener('click',()=>{for(const q of document.querySelectorAll('.question')){q.querySelectorAll('button').forEach(b=>b.removeAttribute('aria-pressed'));const f=q.querySelector('.feedback');f.textContent='';f.removeAttribute('data-result');q.querySelector('.quiz-explanation').hidden=true;}});

const findings=[...document.querySelectorAll('#review-findings > details.review-finding')];
if(findings.length>1){
 const toggle=document.createElement('button');
 toggle.type='button';toggle.id='toggle-findings';toggle.className='finding-controls';
 toggle.setAttribute('aria-controls','review-findings');
 const update=()=>{toggle.textContent=findings.every(f=>f.open)?'Collapse all findings':'Expand all findings';};
 toggle.addEventListener('click',()=>{const open=!findings.every(f=>f.open);for(const finding of findings)finding.open=open;update();});
 for(const finding of findings)finding.addEventListener('toggle',update);
 findings[0].before(toggle);update();
}

document.addEventListener('click', async event => {
 const button=event.target.closest('.copy-comment');
 if(!button)return;
 const section=button.closest('.review-comment'),source=section.querySelector('.comment-source'),status=section.querySelector('.copy-status');
 try{await navigator.clipboard.writeText(source.value);status.textContent='Copied';}
 catch{source.hidden=false;source.focus();source.select();status.textContent='Select and copy the Markdown below.';}
});

for(const scenario of document.querySelectorAll('.scenario')){
 const controls=scenario.querySelector('.scenario-controls');
 const buttons=[...controls.querySelectorAll('button')];
 const frames=[...scenario.querySelectorAll(':scope > .scenario-frame')];
 const select=index=>{
  buttons.forEach((button,i)=>button.setAttribute('aria-pressed',String(i===index)));
  frames.forEach((frame,i)=>frame.hidden=i!==index);
 };
 controls.hidden=false;scenario.dataset.enhanced='true';select(0);
 buttons.forEach((button,index)=>button.addEventListener('click',()=>select(index)));
}

// Verdict links open the finding they point at; findings otherwise start collapsed.
document.addEventListener('click',event=>{
 const link=event.target.closest('[data-open-finding]');
 const target=link&&document.getElementById(link.getAttribute('href').slice(1));
 if(target)target.open=true;
});

// Reader-advanced visual steps: numbered notes with instant, optional focus.
let stepperMarkerId=0;
for(const stepper of document.querySelectorAll('.stepper')){
 const texts=[...stepper.querySelectorAll('.stepper-texts > li')],picture=stepper.querySelector('.stepper-visual');
 const buttons=texts.map(text=>text.querySelector('.stepper-note'));
 const keys=JSON.parse(stepper.dataset.targets),kind=stepper.dataset.visual;
 let current=null;
 const targets=new Map(),companions=new Map(),units=new Set(),edges=[];
 const add=(key,element,related=[])=>{
  if(!element)return;
  targets.set(key,element);element.dataset.stepperTarget=String(key);
  companions.set(element,related.filter(Boolean));[element,...related].filter(Boolean).forEach(e=>units.add(e));
 };
 if(kind==='mermaid-sequence'){
  const messages=[...picture.querySelectorAll('[data-et="message"]')];
  const actors=[...picture.querySelectorAll('[data-et="participant"],[data-et="life-line"]')];
  messages.forEach((message,i)=>{
   // A wrapped message has multiple text siblings. Associate every line with
   // its message element, stopping at the preceding message rather than indexing labels.
   const labels=[];
   for(let node=message.previousElementSibling;node&&!node.matches('[data-et="message"]');node=node.previousElementSibling){
    if(node.matches('.messageText'))labels.push(node);
   }
   const number=message.nextElementSibling;
   add(i+1,message,[...labels,number?.matches('.sequenceNumber')?number:null,...actors.filter(a=>[message.dataset.from,message.dataset.to].includes(a.dataset.id))]);
  });
 }else if(kind==='mermaid-flowchart'){
  const nodes=[...picture.querySelectorAll('.node')];
  for(const key of keys)add(key,nodes.find(n=>n.id.match(/-flowchart-(.+)-[0-9]+$/)?.[1]===key));
  for(const edge of picture.querySelectorAll('[data-et="edge"]')){
   const pair=keys.flatMap(from=>keys.map(to=>({from,to}))).find(({from,to})=>edge.dataset.id?.startsWith('L_'+from+'_'+to+'_'));
   const named=JSON.parse(stepper.dataset.edges||'{}')[edge.dataset.id];
   const ends=pair?[pair.from,pair.to]:named;
   const label=[...picture.querySelectorAll('.edgeLabel .label')].find(e=>e.dataset.id===edge.dataset.id)?.closest('.edgeLabel');
   edges.push({element:edge,ends,label});units.add(edge);if(label)units.add(label);
  }
 }else if(kind==='diagram'){
  const ids=[...picture.querySelectorAll('[id]')];for(const key of keys)add(key,ids.find(e=>e.id===key));
 }else{
  picture.querySelectorAll('.flow-step,.sequence-step').forEach((e,i)=>add(i+1,e));
 }
 for(const unit of units)unit.dataset.stepperUnit='true';
 // Shared SVG arrowheads get local accent copies for focused arrows.
 const markerChanges=[];
 for(const element of picture.querySelectorAll('[marker-end],[marker-start]'))for(const attribute of ['marker-end','marker-start']){
  const original=element.getAttribute(attribute),id=original?.match(/^url\(#([^)]+)\)$/)?.[1];
  const marker=id&&[...picture.querySelectorAll('marker')].find(e=>e.id===id);if(!marker)continue;
  const copy=marker.cloneNode(true);copy.id='stepper-marker-'+(++stepperMarkerId);copy.classList.add('stepper-accent-marker');
  marker.parentElement.append(copy);markerChanges.push({element,attribute,original,accent:'url(#'+copy.id+')'});
 }
 const markerHost=picture.querySelector('.mermaid-body,.diagram-body')||picture;
 const markerLayer=document.createElement('div');markerLayer.className='stepper-markers';markerHost.append(markerLayer);
 const markers=[];
 texts.forEach((text,index)=>{
  for(const key of JSON.parse(text.dataset.focus)){
   const element=targets.get(key);if(!element)continue;
   const badge=document.createElement('button');badge.type='button';badge.className='stepper-marker';badge.textContent=String(index+1);
   badge.setAttribute('aria-label','Highlight note '+(index+1)+': '+buttons[index].querySelector('strong').textContent);
   badge.setAttribute('aria-pressed','false');badge.addEventListener('click',()=>select(current===index?null:index));
   markerLayer.append(badge);markers.push({badge,element,index});
  }
 });
 const positionMarkers=()=>{
  const origin=markerHost.getBoundingClientRect(),placed=new Map();
  for(const {badge,element} of markers){
   const box=element.getBoundingClientRect(),offset=placed.get(element)||0;placed.set(element,offset+1);
   // Keep badges on the target, above an arrow or at a node's upper corner.
   const arrow=element.matches('path,line,polyline,[data-et="message"]');
   badge.style.left=Math.max(12,(arrow?(box.left+box.right)/2:box.left+10)-origin.left+markerHost.scrollLeft+offset*25)+'px';
   badge.style.top=Math.max(12,box.top-origin.top+markerHost.scrollTop+(arrow?12:10))+'px';
   badge.hidden=box.width===0&&box.height===0;
  }
 };
 const select=index=>{
  current=index;
  const all=index===null,focus=all?[]:JSON.parse(texts[index].dataset.focus),focused=new Set();
  buttons.forEach((button,i)=>button.setAttribute('aria-pressed',String(i===index)));
  markers.forEach(({badge,index:i})=>badge.setAttribute('aria-pressed',String(i===index)));
  if(!all&&markerHost!==picture){
   const target=targets.get(focus[0]),box=target?.getBoundingClientRect(),host=markerHost.getBoundingClientRect();
   if(box&&(box.left<host.left||box.right>host.right))markerHost.scrollLeft+=(box.left+box.right-host.left-host.right)/2;
  }
  for(const key of focus){const item=targets.get(key);if(item){focused.add(item);companions.get(item).forEach(e=>focused.add(e));}}
  for(const {element,ends,label} of edges)if(ends?.every(key=>focus.includes(key))){focused.add(element);if(label)focused.add(label);}
  for(const item of units){
   const hot=focused.has(item)||[...focused].some(parent=>parent.contains(item));
   const ancestor=[...focused].some(child=>item.contains(child));
   item.classList.toggle('stepper-focus',!all&&hot);
   item.classList.toggle('stepper-dim',!all&&!hot&&!ancestor);
  }
  for(const item of units)if(item.classList.contains('stepper-dim')&&item.parentElement.closest('.stepper-dim'))item.classList.remove('stepper-dim');
  for(const {element,attribute,original,accent} of markerChanges)element.setAttribute(attribute,!all&&element.closest('.stepper-focus')?accent:original);
 };
 stepper.dataset.enhanced='true';select(null);
 buttons.forEach((button,index)=>button.addEventListener('click',()=>select(current===index?null:index)));
 stepper.addEventListener('keydown',event=>{if(event.key==='Escape'){select(null);event.stopPropagation();}});
 new ResizeObserver(positionMarkers).observe(picture);
 // Reposition when a closed disclosure/scene becomes visible or fonts finish loading.
 new IntersectionObserver(positionMarkers).observe(picture);
 document.fonts.ready.then(positionMarkers);positionMarkers();
}

// Paper responsive diagrams
// Keep SVG labels readable on phones. The sanitized, offline SVG stays intact.
for(const svg of document.querySelectorAll('.paper-page .mermaid-figure svg,.paper-page .diagram-body svg')){
 const host=svg.parentElement;
 host.classList.add('paper-diagram-scroll');host.tabIndex=0;
 host.setAttribute('role','region');host.setAttribute('aria-label','Scrollable diagram');
 const hint=document.createElement('p');hint.className='paper-diagram-hint';
 hint.textContent='Scroll the diagram →';hint.hidden=true;host.after(hint);
 const resize=()=>{
  svg.style.removeProperty('min-width');svg.style.removeProperty('max-width');
  if(innerWidth>480){hint.hidden=true;return;}
  const box=svg.getBoundingClientRect();if(!box.width||!box.height)return;
  const sizes=[...svg.querySelectorAll('text,tspan,foreignObject span,foreignObject p')].filter(e=>e.textContent.trim()).map(e=>{
   const matrix=e.getScreenCTM?.()||svg.getScreenCTM();
   return parseFloat(getComputedStyle(e).fontSize)*Math.hypot(matrix.a,matrix.b);
  }).filter(n=>n>0);
  const smallest=Math.min(...sizes);
  if(smallest<10){svg.style.minWidth=Math.ceil(box.width*10.05/smallest)+'px';svg.style.maxWidth='none';}
  hint.hidden=svg.getBoundingClientRect().width<=host.clientWidth+1;
 };
 new ResizeObserver(resize).observe(host);
 window.addEventListener('resize',resize);
 // Closed orientation and evidence can contain diagrams too.
 document.addEventListener('toggle',resize,true);document.fonts.ready.then(resize);resize();
}
