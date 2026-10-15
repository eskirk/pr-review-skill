'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const notesArtifact = artifacts => artifacts['review-html'] || artifacts['review-markdown'];
const artifactLabel = name => name==='review-html'?'Review notes':name==='review-markdown'?'Legacy notes':'Legacy explanation';
const artifactUrl = path => '/artifact?path='+encodeURIComponent(path);
const safeUrl = value => {try {const u=new URL(value);return u.protocol==='https:'?u.href:'#';} catch{return '#';}};
const labels={requested:'Requested from you',watching:'Watching',mine:'Your PRs',snoozed:'Snoozed',hidden:'Hidden'};
const descriptions={requested:'PRs assigned to you or requesting your review.',watching:'Open PRs from repositories you follow.',mine:'Open pull requests you created.',snoozed:'Temporarily out of your inbox. Open PRs return after their snooze, once checked on GitHub.',hidden:'Set aside for now. Restore a PR to bring it back to its view.'};
const statusLabels={starting:'Starting',queued:'Starting',running:'Reviewing',completed:'Completed','completed-with-gaps':'Completed with gaps',blocked:'Needs input',failed:'Run failed',cancelled:'Cancelled',stopping:'Stopping','no-activity':'No recent activity'};
const active = run => run && ['starting','queued','running','stopping','no-activity'].includes(run.status);
const attention = run => run && ['blocked','failed','no-activity'].includes(run.status);
const defaults={view:'requested',search:'',reportRepositoriesOnly:[],reportRepositoriesExcluded:[],repositoriesOnly:[],repositoriesExcluded:[],authorsOnly:[],authorsExcluded:[],statusesOnly:[],statusesExcluded:[],drafts:'all',triageEffort:'all',sort:'updated'};
let filters={...defaults};
try {filters={...defaults,...JSON.parse(localStorage.getItem('pr-inbox-filters')||'{}')};}catch{}
delete filters.starred;
if(!['all','quick','moderate','involved','uncertain'].includes(filters.triageEffort))filters.triageEffort='all';
if(!['updated','oldest','effort'].includes(filters.sort))filters.sort='updated';
// Preserve selections saved by the earlier single-author filter.
const authorLogins = values => [...new Set((Array.isArray(values)?values:[]).filter(value=>typeof value==='string'&&value).map(value=>value.startsWith('app/')?value.slice(4)+'[bot]':value))];
filters.authorsOnly=authorLogins(Array.isArray(filters.authorsOnly)&&filters.authorsOnly.length?filters.authorsOnly:filters.author?[filters.author]:[]);
filters.authorsExcluded=authorLogins([...(Array.isArray(filters.authorsExcluded)?filters.authorsExcluded:[]),...(filters.hideRenovate?['renovate[bot]','renovate-sh-app[bot]']:[])]);
delete filters.author;delete filters.hideRenovate;
const selectedValues = values => [...new Set((Array.isArray(values)?values:[]).filter(value=>typeof value==='string'&&value))];
for(const key of ['reportRepositoriesOnly','reportRepositoriesExcluded'])filters[key]=selectedValues(filters[key]);
for(const [prefix,legacy] of [['repositories','repository'],['statuses','status']]){
 filters[prefix+'Only']=selectedValues(Array.isArray(filters[prefix+'Only'])&&filters[prefix+'Only'].length?filters[prefix+'Only']:filters[legacy]?[filters[legacy]]:[]);
 filters[prefix+'Excluded']=selectedValues(filters[prefix+'Excluded']);delete filters[legacy];
}
if(!labels[filters.view])filters.view='requested';
const presetKeys=['search','repositoriesOnly','repositoriesExcluded','authorsOnly','authorsExcluded','statusesOnly','statusesExcluded','drafts','triageEffort','sort'];
const filterPresetStorageKey='pr-inbox-filter-presets';
function normalizePresetFilters(value){
 const source=value&&typeof value==='object'?value:{};
 const result={search:typeof source.search==='string'?source.search:''};
 for(const key of ['repositoriesOnly','repositoriesExcluded','authorsOnly','authorsExcluded','statusesOnly','statusesExcluded'])result[key]=selectedValues(source[key]);
 result.drafts=['all','ready','only'].includes(source.drafts)?source.drafts:'all';
 result.triageEffort=['all','quick','moderate','involved','uncertain'].includes(source.triageEffort)?source.triageEffort:'all';
 result.sort=['updated','oldest','effort'].includes(source.sort)?source.sort:'updated';
 return result;
}
function readFilterPresets(){
 try{
  const value=JSON.parse(localStorage.getItem(filterPresetStorageKey)||'{}');
  if(!value||typeof value!=='object')return {version:1,defaultId:null,presets:[]};
  const seen=new Set(),presets=(Array.isArray(value.presets)?value.presets:[]).filter(item=>{
   if(!item||typeof item!=='object'||typeof item.id!=='string'||!item.id||seen.has(item.id)||typeof item.name!=='string'||!item.name.trim())return false;
   seen.add(item.id);return true;
  }).map(item=>({id:item.id,name:item.name.trim().slice(0,80),filters:normalizePresetFilters(item.filters)}));
  return {version:1,defaultId:presets.some(item=>item.id===value.defaultId)?value.defaultId:null,presets};
 }catch{return {version:1,defaultId:null,presets:[]};}
}
let filterPresets=readFilterPresets(),selectedPresetId='';
function saveFilterPresets(){try{localStorage.setItem(filterPresetStorageKey,JSON.stringify(filterPresets));}catch{}}
function presetSnapshot(value=filters){const result={};for(const key of presetKeys)result[key]=Array.isArray(value[key])?[...value[key]]:value[key];return result;}
function presetById(id){return filterPresets.presets.find(item=>item.id===id)||null;}
function randomPresetId(){return crypto.randomUUID?.()||Date.now().toString(36)+Math.random().toString(36).slice(2);}
let reportingData=null, reportingActive=false, state=null, listSignature='', settingsDirty=false, loading=false, toastTimer, undoAction=null, showAction=null;
const busy = new Set();
// Restore only after async PR data has rebuilt the overview's full height.
let overviewScrollPending=true;
history.scrollRestoration='manual';
function overviewScrollKey(){return 'pr-overview-scroll:'+JSON.stringify(queueActive?'queue':filters);}
window.addEventListener('pagehide',()=>{
 if(!state||overviewScrollPending||reportingActive)return;
 try{sessionStorage.setItem(overviewScrollKey(),JSON.stringify({x:scrollX,y:scrollY}));}catch{}
});
function restoreOverviewScroll(){
 if(!overviewScrollPending||reportingActive)return;
 overviewScrollPending=false;
 try{
  const saved=JSON.parse(sessionStorage.getItem(overviewScrollKey())||'null');
  if(saved&&Number.isFinite(saved.x)&&Number.isFinite(saved.y))window.scrollTo({left:saved.x,top:saved.y,behavior:'instant'});
 }catch{}
}
function saveFilters(){try{localStorage.setItem('pr-inbox-filters',JSON.stringify(filters));}catch{}}
function renderFilterPresets(){
 const select=$('filter-preset');if(!select)return;
 const current=presetById(selectedPresetId)?selectedPresetId:'';
 select.innerHTML='<option value="">No preset selected</option>'+filterPresets.presets.map(item=>`<option value="${esc(item.id)}">${esc(item.name)}${item.id===filterPresets.defaultId?' · default':''}</option>`).join('');
 selectedPresetId=current;select.value=current;
 const enabled=!!current;
 for(const id of ['filter-preset-apply','filter-preset-default','filter-preset-rename','filter-preset-delete'])$(id).disabled=!enabled;
 $('filter-preset-default').textContent=enabled&&current===filterPresets.defaultId?'Unset default':'Set as default';
 const selected=presetById(current);if(selected&&document.activeElement!==$('filter-preset-name'))$('filter-preset-name').value=selected.name;
}
function applyInboxFilters(value){
 const view=filters.view,reportOnly=[...filters.reportRepositoriesOnly],reportExcluded=[...filters.reportRepositoriesExcluded];
 filters={...defaults,...normalizePresetFilters(value),view,reportRepositoriesOnly:reportOnly,reportRepositoriesExcluded:reportExcluded};
 for(const id of Object.keys(pickerConfig))$(id+'-search').value='';
 syncFilterControls();saveFilters();renderList();
}
function resetToDefault(){
 const preset=presetById(filterPresets.defaultId);
 selectedPresetId=preset?.id||'';
 applyInboxFilters(preset?.filters||defaults);
 notify(preset?`Reset to “${preset.name}”.`:'Reset to built-in defaults.');
}
function saveCurrentPreset(){
 const input=$('filter-preset-name'),name=input.value.trim();
 if(!name){$('filter-preset-status').textContent='Enter a name for this preset.';input.focus();return;}
 if(filterPresets.presets.some(item=>item.name.toLowerCase()===name.toLowerCase())){$('filter-preset-status').textContent='A preset with that name already exists.';input.focus();return;}
 const preset={id:randomPresetId(),name:name.slice(0,80),filters:presetSnapshot()};filterPresets.presets.push(preset);selectedPresetId=preset.id;saveFilterPresets();renderFilterPresets();$('filter-preset-status').textContent=`Saved “${preset.name}”.`;
}
function applySelectedPreset(){const preset=presetById(selectedPresetId);if(!preset)return;applyInboxFilters(preset.filters);notify(`Applied “${preset.name}”.`);}
function toggleDefaultPreset(){const preset=presetById(selectedPresetId);if(!preset)return;filterPresets.defaultId=filterPresets.defaultId===preset.id?null:preset.id;saveFilterPresets();renderFilterPresets();$('filter-preset-status').textContent=filterPresets.defaultId===preset.id?`“${preset.name}” is now the default.`:'Default preset cleared.';}
function renameSelectedPreset(){
 const preset=presetById(selectedPresetId),input=$('filter-preset-name'),name=input.value.trim();
 if(!preset)return;
 if(!name){$('filter-preset-status').textContent='Enter a name for this preset.';input.focus();return;}
 if(filterPresets.presets.some(item=>item.id!==preset.id&&item.name.toLowerCase()===name.toLowerCase())){$('filter-preset-status').textContent='A preset with that name already exists.';input.focus();return;}
 preset.name=name.slice(0,80);saveFilterPresets();renderFilterPresets();$('filter-preset-status').textContent=`Renamed to “${preset.name}”.`;
}
function deleteSelectedPreset(){
 const preset=presetById(selectedPresetId);if(!preset)return;
 filterPresets.presets=filterPresets.presets.filter(item=>item.id!==preset.id);if(filterPresets.defaultId===preset.id)filterPresets.defaultId=null;selectedPresetId='';saveFilterPresets();renderFilterPresets();$('filter-preset-name').value='';$('filter-preset-status').textContent=`Deleted “${preset.name}”.`;
}
function when(stamp){if(!stamp)return 'Not yet checked';const date=new Date(stamp);return Number.isNaN(date.valueOf())?'Unknown date':date.toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});}
function since(stamp){if(!stamp)return 'Unknown';const minutes=Math.max(0,Math.floor((Date.now()-new Date(stamp))/60000));if(!Number.isFinite(minutes))return 'Unknown';if(minutes<1)return 'just now';if(minutes<60)return minutes+'m ago';if(minutes<1440)return Math.floor(minutes/60)+'h ago';return Math.floor(minutes/1440)+'d ago';}
function notify(text,undo,show){clearTimeout(toastTimer);undoAction=undo||null;showAction=show||null;$('toast').replaceChildren(document.createTextNode(text));for(const [id,label,enabled] of [['toast-show','Show',show],['undo','Undo',undo]])if(enabled){const button=document.createElement('button');button.textContent=label;button.id=id;$('toast').append(button);}$('toast').hidden=false;toastTimer=setTimeout(()=>$('toast').hidden=true,undo||show?10000:6000);}
async function post(action,data={}){const response=await fetch(action,{method:'POST',keepalive:action==='/artifact-opened',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify(data)});const result=await response.json();if(!response.ok)throw new Error(result.error||'The action failed.');return result;}
function artifactLink(a,label,pr){
 if(!a)return '';
 const freshness=a.freshness==='older'?'Older commit':a.freshness==='current'?'':'Commit unverified';
 const title=[when(a.created_at),a.tool,'Created for commit '+(a.head_sha?.slice(0,12)||'not recorded'),
  'Last fetched PR commit '+(pr?.head_sha?.slice(0,12)||'not recorded'),a.unread?'You have not opened this version.':'',
  a.freshness==='older'?'The PR has changed; parts of this result may no longer apply.':''].filter(Boolean).join(' · ');
 return `<a class="button artifact-link ${a.unread?'artifact-unread':''}" data-artifact-run="${esc(a.run_id)}" data-artifact-name="${esc(a.name)}" data-artifact-version="${esc(a.version)}" href="${esc(artifactUrl(a.path))}" target="_blank" rel="noopener" title="${esc(title)}"><span>${esc(label)}</span>${a.unread?'<span class="artifact-new">New<span class="sr-only"> — unopened version</span></span>':''}${freshness?`<span class="artifact-freshness ${a.freshness==='older'?'warn':''}">${esc(freshness)}</span>`:''}</a>`;
}
function artifactWarning(pr){
 const older=Object.entries(pr.artifacts).filter(([,a])=>a.freshness==='older').map(([name])=>artifactLabel(name));
 return older.length?`<p class="artifact-warning">${esc(older.join(' and '))} ${older.length===1&&older[0]==='Legacy explanation'?'was':'were'} created before the latest fetched PR commit. Some parts may no longer apply.</p>`:'';
}
async function acknowledgeArtifact(event){
 if(event.defaultPrevented||(event.type==='click'?event.button!==0:event.button!==1))return;
 const link=event.target.closest('[data-artifact-version]');if(!link)return;
 const {artifactRun:run_id,artifactName:name,artifactVersion:version}=link.dataset;
 // Leave native link navigation intact, including modifier and middle clicks.
 try{
  const result=await post('/artifact-opened',{run_id,name,version});
  if(!result.opened)return;
  const restoreFocus=document.activeElement===link, scope=link.closest('#queue-view')?'queue-view':'pr-list';
  for(const pr of state?.prs||[])for(const artifacts of [pr.artifacts,...pr.history.map(run=>run.artifacts)]){
   const a=artifacts[name];if(a?.run_id===run_id&&a.version===version)a.unread=false;
  }
  renderList();if(typeof renderQueue==='function')renderQueue();
  if(restoreFocus)[...$(scope).querySelectorAll('[data-artifact-version]')].find(a=>a.dataset.artifactRun===run_id&&a.dataset.artifactName===name&&a.dataset.artifactVersion===version)?.focus({preventScroll:true});
 }catch(error){notify('Could not save the opened indicator. '+error.message);}
}
document.addEventListener('click',acknowledgeArtifact);
document.addEventListener('auxclick',acknowledgeArtifact);
function copyPromptButton(pr,kind){return `<button class="button" data-copy-prompt="${kind}" data-url="${esc(pr.url)}" title="Copy the prompt to paste into an agent session of your choice">Copy ${kind} prompt</button>`;}
async function copyPrompt(button){
 if(button.disabled)return;
 button.disabled=true;
 try{
  const {prompt}=await post('/copy-prompt',{url:button.dataset.url,kind:button.dataset.copyPrompt});
  try{await navigator.clipboard.writeText(prompt);notify('Prompt copied. Paste it into your preferred agent session.');}
  catch{
   $('prompt-text').value=prompt;$('prompt-dialog').showModal();$('prompt-text').focus();$('prompt-text').select();
  }
 }catch(error){notify(error.message);}finally{button.disabled=false;}
}
function renderHistory(pr){return pr.history.map(run=>`<div class="history-entry"><div><p>${esc(when(run.created_at))} · ${esc(run.tool)} · ${esc(statusLabels[run.status]||run.status)}${run.cost?` · <span title="Estimated API cost">${esc(costMoney(run.cost.usd))}</span>`:''}</p><p class="muted">${esc(run.kind==='explainer'?'Legacy explanation':run.mode==='update'?'Review update':'Review')} · Commit <code>${esc(run.head_sha?.slice(0,12)||'not recorded')}</code></p></div><div class="history-links">${run.transport==='in-app'?`<button class="button" data-review-open="${esc(run.run_id)}">View activity</button>`:''}${Object.entries(run.artifacts).map(([name,a])=>artifactLink(a,artifactLabel(name),pr)).join('')}</div></div>`).join('');}
function authorBadge(pr){
 const login=pr.author_login||'';
 if(!login)return '<span class="pr-author unknown-author">Unknown author</span>';
 const encoded=encodeURIComponent(login), name=pr.author_name||login;
 const profileUrl=login.endsWith('[bot]')?'https://github.com/apps/'+encodeURIComponent(login.slice(0,-5)):'https://github.com/'+encoded;
 let avatar=`https://github.com/${encoded}.png?size=64`;
 try {const u=new URL(pr.author_avatar_url);if(u.protocol==='https:'&&u.hostname==='avatars.githubusercontent.com')avatar=u.href;}catch{}
 return `<a class="pr-author" href="${esc(profileUrl)}" target="_blank" rel="noopener" aria-label="Author: ${esc(name===login?login:name+' ('+login+')')}"><span class="avatar-wrap"><span class="avatar-fallback" aria-hidden="true">${esc(login.slice(0,1).toUpperCase())}</span><img class="author-avatar" src="${esc(avatar)}" alt="" width="28" height="28" loading="lazy" referrerpolicy="no-referrer"></span><span>${name!==login?esc(name)+' ':''}<span class="author-login">@${esc(login)}</span></span>${login.endsWith('[bot]')?'<span class="chip">Bot</span>':''}</a>`;
}
function prIdentity(pr){return `<div class="pr-identity"><a href="https://github.com/${esc(encodeURIComponent(pr.owner))}/${esc(encodeURIComponent(pr.repository))}" target="_blank" rel="noopener">${esc(pr.owner+'/'+pr.repository)}</a><a class="pr-number" href="${esc(safeUrl(pr.url))}" target="_blank" rel="noopener">#${esc(pr.number)}</a></div>`;}
function prAge(pr){return pr.pr_created_at?`<span title="Opened ${esc(new Date(pr.pr_created_at).toLocaleString())}">Opened ${esc(since(pr.pr_created_at))}</span>`:'<span title="Sync GitHub to fetch the opening date">Age unknown</span>';}
function snoozeControl(pr){
 if(pr.snoozed_until)return `<button class="button" data-action="/unsnooze" data-url="${esc(pr.url)}">Bring back now</button>`;
 return `<details class="snooze-picker"><summary class="button" aria-label="Snooze PR ${esc(pr.number)}">Snooze</summary><div class="snooze-options"><p class="muted">Snooze for</p>${[[1,'1 day'],[2,'2 days'],[7,'1 week']].map(([days,label])=>`<button class="button" data-action="/snooze" data-days="${days}" data-url="${esc(pr.url)}">${label}</button>`).join('')}</div></details>`;
}
function snoozeStatus(pr){
 if(!pr.snoozed_until)return '';
 const pending=new Date(pr.snoozed_until)<=Date.now();
 return `<span class="chip" title="${esc(new Date(pr.snoozed_until).toLocaleString())}">${pending?'Snooze ended · awaiting GitHub check':'Snoozed until '+esc(when(pr.snoozed_until))}</span>`;
}
function inView(pr,view){
 if(pr.discovered===false)return false;
 if(view==='hidden')return !!pr.hidden;
 if(pr.hidden)return false;
 return view==='snoozed'?!!pr.snoozed_until:!pr.snoozed_until&&pr.group===view;
}
let snoozeRefreshAttempt=0;
async function refreshExpiredSnoozes(){
 if(document.hidden||!state||state.refresh?.status==='running'||Date.now()-snoozeRefreshAttempt<300000)return;
 if(!state.prs.some(pr=>pr.discovered!==false&&!pr.hidden&&pr.snoozed_until&&new Date(pr.snoozed_until)<=Date.now()))return;
 snoozeRefreshAttempt=Date.now();
 try{await post('/refresh');}catch(error){notify('Could not check expired snoozes. '+error.message);}
}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)loadState();});
// Back from the workspace restores this page from the browser cache; refresh its data behind it.
window.addEventListener('pageshow',event=>{if(event.persisted){loadState();loadReporting();}});
document.addEventListener('click',event=>{for(const picker of document.querySelectorAll('.snooze-picker[open]'))if(!picker.contains(event.target))picker.open=false;});
document.addEventListener('keydown',event=>{if(event.key==='Escape')for(const picker of document.querySelectorAll('.snooze-picker[open]')){picker.open=false;picker.querySelector('summary').focus();}});
// A finished report of an older commit can be updated instead of redone, unless the fixed rules said no.
function canUpdate(pr){
 const a=pr.artifacts['review-html'],c=pr.update_check;
 return !active(pr.run)&&!!a&&a.status==='completed'&&a.freshness==='older'&&!(c?.decided_by==='rules'&&c.scope==='full');
}
function updateButton(pr,primary=false){return `<button class="button${primary?' primary':''}" data-action="/regenerate-review" data-mode="update" data-url="${esc(pr.url)}" title="Re-check the previous findings and review only the new commits and the code they affect">Update AI review</button>`;}
function aiReviewActions(pr){
 const running=active(pr.run),hasNotes=!!notesArtifact(pr.artifacts);
 return `${canUpdate(pr)?updateButton(pr):''}<button class="button" data-action="/regenerate-review" data-url="${esc(pr.url)}" ${running?'disabled':''}>${running?'AI review in progress':hasNotes?'Run full AI review':'Run AI review'}</button>${running?'':`<button class="button" data-review-guidance data-url="${esc(pr.url)}">Run with guidance…</button>`}${copyPromptButton(pr,'review')}`;
}
// The pre-check's recommendation; the review itself re-checks every finding either way.
function updateHint(pr){
 const a=pr.artifacts['review-html'],c=pr.update_check;
 if(active(pr.run)||!a||a.status!=='completed'||a.freshness!=='older')return '';
 const full=c?.scope==='full',hints=c?.findings||[];
 const addressed=hints.filter(f=>f.status==='likely-addressed').length;
 const detail=hints.length?` ${addressed} of ${hints.length} previous finding${hints.length===1?'':'s'} look${addressed===1?'s':''} addressed; the update re-checks all of them.`:'';
 const text=c?(full?'Full review suggested: ':'Update suggested: ')+c.reason+(full?'':detail):'New commits since the AI review. An update re-checks the previous findings and reviews the new commits; a full review starts over.';
 const fullButton=`<button class="button${full?' primary':''}" data-action="/regenerate-review" data-url="${esc(pr.url)}">Run full AI review</button>`;
 return `<div class="update-hint"><p>${esc(text)}${c?.hotspots?.length?` <span class="muted">Also check: ${esc(c.hotspots.join('; '))}</span>`:''}</p><div class="action-bar">${canUpdate(pr)?updateButton(pr,!full):''}${fullButton}</div></div>`;
}
function actionDisclosure(pr,label,contents,className='pr-overflow'){
 return `<details class="${className} action-disclosure"><summary class="button" aria-label="${esc(label==='•••'?'More actions for PR '+pr.number:label+' for PR '+pr.number)}">${label}</summary><div class="action-menu">${contents}</div></details>`;
}
function codeWorkspaceLink(pr){
 const ready=!!notesArtifact(pr.artifacts);
 const query='url='+encodeURIComponent(pr.url);
 return `<a class="button" href="/workspace?${query}&tab=${ready?'review':'code'}">Open review</a>`;
}
function workspaceStatusBadge(pr){
 const artifact=notesArtifact(pr.artifacts);
 const ready=!!artifact;
 const running=active(pr.run);
 const label=running?'AI review running':ready?(artifact?.freshness==='older'?'AI review · older commit':'AI review ready'):'No AI review yet';
 return `<span class="chip ${running?'run-live':ready&&artifact?.freshness!=='older'?'good':artifact?.freshness==='older'?'warn':''} workspace-status">${label}</span>${verdictBadge(artifact)}`;
}
// The report's advisory verdict, derived by the renderer from its findings and checks.
function verdictBadge(artifact){
 const v=artifact?.verdict;
 if(!v)return '';
 const mark={good:'✓',warn:'!',bad:'✕',muted:'–'}[v.tone]||'';
 const tone=v.tone==='muted'?'':v.tone;
 const older=artifact.freshness==='older'?' (older commit)':'';
 return `<span class="chip ${esc(tone)} verdict-badge" title="${esc('AI review verdict: '+v.headline+(v.confidence?' · '+v.confidence+' confidence':'')+older)}"><span aria-hidden="true">${mark}</span>${esc(v.short)}${v.confidence?' · '+esc(v.confidence):''}</span>`;
}
function card(pr){
 const run=pr.run, isActive=active(run), arts=pr.artifacts, hasNotes=!!notesArtifact(arts), hidden=!!pr.hidden;
 const workspaceLink=codeWorkspaceLink(pr);
 const organize=hidden?'':`<p class="detail-heading">Organize</p>${snoozeControl(pr)}<button class="button hide-pr" data-action="/hide" data-url="${esc(pr.url)}">Hide from inbox</button>`;
 const extra=`${organize}<p class="detail-heading">AI tools</p>${aiReviewActions(pr)}`;
 const buttons=hidden?`<button class="button primary" data-action="/unhide" data-url="${esc(pr.url)}">Restore PR</button>`:
  queueCaptureButton(pr)+workspaceLink+actionDisclosure(pr,'•••',extra);
 let status=run?`<span class="chip ${isActive?'run-live':attention(run)?'warn':''}">AI: ${esc(statusLabels[run.status]||run.status)}</span>`:'';
 if(hasNotes&&!run)status+='<span class="chip good">AI notes ready</span>';
 if(pr.mixed_artifacts)status+='<span class="chip warn">Results from different runs</span>';
 const history=pr.history.length?`<div><p class="detail-heading">Run history (${pr.history_total})</p>${renderHistory(pr)}</div>`:'';
 return `<article class="pr-card" data-pr="${esc(pr.url)}"><div class="pr-main"><div>${prIdentity(pr)}<a class="pr-title" href="${esc(safeUrl(pr.url))}" target="_blank" rel="noopener">${esc(pr.title)}</a><div class="pr-byline">${authorBadge(pr)}</div><div class="pr-meta">${prAge(pr)}${snoozeStatus(pr)}<span title="${esc(when(pr.pr_updated_at||pr.first_seen_at))}">${pr.pr_updated_at?'Updated':'First seen'} ${esc(since(pr.pr_updated_at||pr.first_seen_at))}</span>${pr.is_draft?'<span class="chip">Draft</span>':''}${triageBadge(pr)}${workspaceStatusBadge(pr)}</div></div><div class="pr-actions">${buttons}</div></div>
 <div class="pr-foot"><span title="Your participation on GitHub">GitHub: ${esc(pr.participation)}</span>${status}</div>
 ${triageCard(pr)}${artifactWarning(pr)}${updateHint(pr)}${reviewSummary(run)}
 ${run||history||Object.keys(arts).length?`<details class="run-details"><summary>AI run details & history</summary><div class="detail-content">
 ${run?`<section><p class="detail-heading">${esc(statusLabels[run.status]||run.status)} · ${esc(run.tool)}</p><p class="muted">Last recorded AI activity ${esc(since(run.updated_at))}. ${isActive&&run.transport!=='in-app'?'Status comes from the review tracker; it does not prove the terminal is still running.':''}</p>${run.message?`<p class="muted">${esc(run.message)}</p>`:''}${run.guidance?`<p class="muted run-guidance"><strong>Guidance:</strong> ${esc(run.guidance)}</p>`:''}${run.workspace_context?.notes?.length||run.workspace_context?.conversations?.length?`<p class="muted"><strong>Private context:</strong> ${run.workspace_context.notes?.length||0} note${(run.workspace_context.notes?.length||0)===1?'':'s'} and ${run.workspace_context.conversations?.length||0} conversation${(run.workspace_context.conversations?.length||0)===1?'':'s'}${run.workspace_context.truncated?' · truncated to the context limit':''}</p>`:''}<ul class="task-list">${run.tasks.filter(t=>t.status!=='skipped').map(t=>`<li title="${esc(t.message)}">${esc(t.name.replaceAll('-',' '))}: ${esc(t.status)}</li>`).join('')}</ul>${run.session_reference?`<div class="action-bar"><button class="button" data-copy="${esc(run.session_reference)}">Copy session reference</button>${safeUrl(run.session_reference)!=='#'?`<a class="button" href="${esc(safeUrl(run.session_reference))}" target="_blank" rel="noopener">Open session</a>`:''}</div>`:'<p class="muted">No session reference recorded.</p>'}
 ${run.transport!=='in-app'&&(attention(run)||['starting','queued'].includes(run.status))?`<button class="button" data-action="/regenerate-review" data-url="${esc(pr.url)}" data-retry="true">Retry after closing the previous terminal</button>`:''}</section>`:''}
 ${Object.keys(arts).length?`<section><p class="detail-heading">Results currently shown</p>${Object.entries(arts).map(([name,a])=>`<p class="muted">${artifactLabel(name)}: ${esc(when(a.created_at))} · ${esc(a.tool)} · commit ${esc(a.head_sha?.slice(0,12)||'not recorded')}${a.status!=='completed'?' · partial result':''}</p>`).join('')}</section>`:''}${history}</div></details>`:''}</article>`;
}
const statusOptions={unreviewed:'No GitHub feedback yet',reviewed:'Reviewed or commented on GitHub',ready:'AI notes available',unread:'New unopened AI results',running:'AI run active',attention:'AI run needs attention',older:'Older AI results'};
const pickerConfig={reportrepository:{prefix:'reportRepositories',title:'Repositories',empty:'All report repositories'},author:{prefix:'authors',title:'Authors',empty:'All authors'},repository:{prefix:'repositories',title:'Repositories',empty:'All repositories'},status:{prefix:'statuses',title:'Statuses',empty:'Any review status'}};
const pickerSignatures={};
function filterOptions(id){
 if(id==='reportrepository')return new Map((reportingData?.events||[]).map(event=>[event.repository,event.repository]));
 if(id==='status')return new Map(Object.entries(statusOptions));
 return new Map((state?.prs||[]).filter(pr=>id!=='author'||pr.author_login).map(pr=>id==='author'?[pr.author_login,pr.author_name||pr.author_login]:[pr.owner+'/'+pr.repository,pr.owner+'/'+pr.repository]));
}
function renderPicker(id){
 const {prefix,title,empty}=pickerConfig[id],only=filters[prefix+'Only'],excluded=filters[prefix+'Excluded'];
 const summary=[only.length?`${only.length} only`:'',excluded.length?`${excluded.length} excluded`:''].filter(Boolean).join(' · ');
 $(id+'-summary').textContent=summary?title+' · '+summary:empty;
 $(id+'-selection').textContent=summary||'No '+title.toLowerCase()+' filtered out';
 const options=filterOptions(id);
 for(const value of [...only,...excluded])if(!options.has(value))options.set(value,value);
 const query=$(id+'-search').value.trim().toLowerCase();
 const choices=[...options].filter(([value,name])=>`${name} ${value}`.toLowerCase().includes(query));
 if(id!=='status')choices.sort((a,b)=>a[1].localeCompare(b[1]));
 const signature=JSON.stringify([choices,only,excluded]);if(signature===pickerSignatures[id])return;pickerSignatures[id]=signature;
 const focused=document.activeElement,value=focused?.dataset?.filterValue,mode=focused?.dataset?.filterMode;
 const container=$(id+'-options'),scrollTop=container.scrollTop;
 container.innerHTML=choices.map(([value,name])=>{
  const label=id==='author'&&name!==value?name+' ('+value+')':name;
  return `<div class="filter-option"><div class="filter-option-name"><strong>${esc(name)}</strong>${id==='author'&&name!==value?`<span class="muted">@${esc(value)}</span>`:''}</div><button type="button" class="filter-choice" data-filter-value="${esc(value)}" data-filter-mode="only" aria-label="Show only ${esc(label)}" aria-pressed="${only.includes(value)}">Show only</button><button type="button" class="filter-choice exclude" data-filter-value="${esc(value)}" data-filter-mode="excluded" aria-label="Exclude ${esc(label)}" aria-pressed="${excluded.includes(value)}">Exclude</button></div>`;
 }).join('')||'<p class="muted">No '+title.toLowerCase()+' match your search.</p>';
 container.scrollTop=scrollTop;
 if(value&&mode)[...container.querySelectorAll('button')].find(button=>button.dataset.filterValue===value&&button.dataset.filterMode===mode)?.focus({preventScroll:true});
}
function renderPickers(){for(const id of Object.keys(pickerConfig))renderPicker(id);}
function updatePicker(id){saveFilters();renderPicker(id);if(id==='reportrepository')renderReporting();else renderList();}
function closePicker(id,focus=false){if($(id+'-picker').open){$(id+'-picker').open=false;if(focus)$(id+'-summary').focus();}}
for(const [id,{prefix}] of Object.entries(pickerConfig)){
 $(id+'-options').addEventListener('click',event=>{
  const button=event.target.closest('[data-filter-value]');if(!button)return;
  const value=button.dataset.filterValue,key=prefix+(button.dataset.filterMode==='only'?'Only':'Excluded');
  const other=prefix+(button.dataset.filterMode==='only'?'Excluded':'Only');
  filters[key]=filters[key].includes(value)?filters[key].filter(item=>item!==value):[...filters[key],value];
  filters[other]=filters[other].filter(item=>item!==value);updatePicker(id);
 });
 $(id+'-search').addEventListener('input',()=>renderPicker(id));
 $(id+'-clear').addEventListener('click',()=>{filters[prefix+'Only']=[];filters[prefix+'Excluded']=[];$(id+'-search').value='';updatePicker(id);});
 $(id+'-done').addEventListener('click',()=>closePicker(id,true));
}
$('exclude-renovate').addEventListener('click',()=>{
 const bots=authorLogins(['renovate[bot]','renovate-sh-app[bot]',...(state?.prs||[]).map(pr=>pr.author_login).filter(login=>/^renovate(?:[-\[]|$)/i.test(login||''))]);
 filters.authorsExcluded=authorLogins([...filters.authorsExcluded,...bots]);filters.authorsOnly=filters.authorsOnly.filter(login=>!bots.includes(login));updatePicker('author');
});
document.addEventListener('keydown',event=>{if(event.key==='Escape')for(const id of Object.keys(pickerConfig))if($(id+'-picker').open){event.preventDefault();closePicker(id,true);}});
document.addEventListener('click',event=>{for(const id of Object.keys(pickerConfig))if(!event.composedPath().includes($(id+'-picker')))closePicker(id);});
function matchesStatus(pr,status){
 switch(status){
  case 'unreviewed':return !pr.my_review_at&&!pr.my_comment_at;
  case 'reviewed':return !!(pr.my_review_at||pr.my_comment_at);
  case 'ready':return !!notesArtifact(pr.artifacts);
  case 'unread':return Object.values(pr.artifacts).some(a=>a.unread);
  case 'running':return !!active(pr.run);
  case 'attention':return !!attention(pr.run);
  case 'older':return pr.artifact_freshness==='older';
  default:return false;
 }
}
function matchesSelection(only,excluded,matches){return (!only.length||only.some(matches))&&!excluded.some(matches);}
function visiblePrs(view=filters.view){
 const text=filters.search.toLowerCase().trim().replace(/^#/,'');
 return state.prs.filter(pr=>inView(pr,view)).filter(pr=>{
  if(text&&!`${pr.title} ${pr.owner}/${pr.repository} ${pr.number} ${pr.author_login} ${pr.author_name||''}`.toLowerCase().includes(text))return false;
  if(!matchesSelection(filters.repositoriesOnly,filters.repositoriesExcluded,value=>value===pr.owner+'/'+pr.repository))return false;
  if(!matchesSelection(filters.authorsOnly,filters.authorsExcluded,value=>value===pr.author_login))return false;
  if(!matchesTriage(pr,filters.triageEffort))return false;
  if(filters.drafts==='ready'&&pr.is_draft || filters.drafts==='only'&&!pr.is_draft)return false;
  if(!matchesSelection(filters.statusesOnly,filters.statusesExcluded,value=>matchesStatus(pr,value)))return false;
  return true;
 }).sort((a,b)=>{
  if(filters.sort==='effort')return compareTriage(a,b);
  const field=filters.sort==='oldest'?'first_seen_at':'pr_updated_at';
  const left=a[field]||a.first_seen_at||'',right=b[field]||b.first_seen_at||'';
  return (filters.sort==='oldest'?left.localeCompare(right):right.localeCompare(left)) || a.url.localeCompare(b.url);
 });
}
function renderList(force=false){if(!state)return;const prs=visiblePrs();const signature=JSON.stringify([prs,filters,Math.floor(Date.now()/60000)]);
 renderWorkspaceNavigation();renderFilterSummary();
 $('result-count').textContent=`${prs.length} ${prs.length===1?'PR':'PRs'}`;
 $('view-heading').textContent=labels[filters.view];$('view-description').textContent=['snoozed','hidden'].includes(filters.view)?descriptions[filters.view]:'';
 document.querySelectorAll('[data-view]').forEach(button=>{const view=button.dataset.view;button.setAttribute('aria-pressed',!reportingActive&&(typeof queueActive==='undefined'||!queueActive)&&view===filters.view);const total=state.prs.filter(pr=>inView(pr,view)).length,shown=visiblePrs(view).length;button.querySelector('.count').textContent=shown===total?total:`${shown} of ${total}`;button.title=shown===total?'':`${shown} match your filters, ${total} in total`;});
 if(!force&&signature===listSignature)return;listSignature=signature;
 const restoreFocus=rememberCardFocus($('pr-list'));
 const expanded=new Map([...$('pr-list').querySelectorAll('[data-pr]')].map(el=>[el.dataset.pr,[...el.querySelectorAll('details[open]')].map(d=>d.className)]));
 const focused=document.activeElement,focusUrl=focused?.dataset?.url,focusAction=focused?.dataset?.action;
 $('pr-list').innerHTML=(prs.length?prTable(prs):'')||`<div class="empty"><h3>${filters.search||filters.repositoriesOnly.length||filters.repositoriesExcluded.length||filters.authorsOnly.length||filters.authorsExcluded.length||filters.statusesOnly.length||filters.statusesExcluded.length||filters.drafts!=='all'||filters.triageEffort!=='all'?'No PRs match these filters':'Nothing here right now'}</h3><p class="muted">${filters.view==='hidden'?'Hidden PRs can be restored here.':'Try another view, reset your filters, or sync GitHub.'}</p><button class="text-button" data-clear>Reset to default</button></div>`;
 $('pr-list').querySelectorAll('[data-pr]').forEach(el=>{for(const d of el.querySelectorAll('details'))if(expanded.get(el.dataset.pr)?.includes(d.className))d.open=true;});
 if(focusUrl&&focusAction&&$('pr-list').contains(focused)){const replacement=[...$('pr-list').querySelectorAll('[data-action]')].find(el=>el.dataset.url===focusUrl&&el.dataset.action===focusAction);replacement?.focus({preventScroll:true});}
 restoreFocus();
 renderDrawer();
 for(const button of document.querySelectorAll('[data-action]'))if(busy.has(button.dataset.url))button.disabled=true;
}
// Inbox and Your PRs are one table row per PR; the full card opens in a side panel.
function prSize(pr){
 if(!Number.isInteger(pr.additions))return '<span class="muted" title="Sync GitHub to fetch the size">–</span>';
 const files=pr.changed_files||0;
 return `<span class="row-size"><span class="row-add">+${pr.additions.toLocaleString()}</span> <span class="row-del">−${(pr.deletions||0).toLocaleString()}</span><small>${files} ${files===1?'file':'files'}</small></span>`;
}
function rowAvatar(pr){
 const login=pr.author_login||'';if(!login)return '';
 let avatar=`https://github.com/${encodeURIComponent(login)}.png?size=40`;
 try {const u=new URL(pr.author_avatar_url);if(u.protocol==='https:'&&u.hostname==='avatars.githubusercontent.com')avatar=u.href;}catch{}
 return `<span class="avatar-wrap row-avatar"><span class="avatar-fallback" aria-hidden="true">${esc(login.slice(0,1).toUpperCase())}</span><img class="author-avatar" src="${esc(avatar)}" alt="" width="20" height="20" loading="lazy" referrerpolicy="no-referrer"></span>`;
}
function rowIdentity(pr,extra=''){
 return `<div class="row-repo" title="${esc(pr.owner+'/'+pr.repository+' #'+pr.number)}"><span class="row-repo-name"><span class="row-owner">${esc(pr.owner)}/</span><span>${esc(pr.repository)}</span></span><a href="${esc(safeUrl(pr.url))}" target="_blank" rel="noopener">#${esc(pr.number)}</a>${pr.is_draft?' <span class="chip">Draft</span>':''}${extra}</div><a class="row-title" href="${esc(safeUrl(pr.url))}" target="_blank" rel="noopener">${esc(pr.title)}</a><div class="row-author">${rowAvatar(pr)}${esc(pr.author_login?'@'+pr.author_login:'Unknown author')}</div>`;
}
// AI review column: live progress while a review runs, otherwise its result and cost.
function aiCell(pr){
 const run=pr.run;
 if(run?.transport==='in-app'&&active(run)){
  const percent=run.progress?.percent||0,now=(run.progress?.stages||[]).filter(stage=>stage.status==='running').map(stage=>stage.label).join(' · ');
  return `<div class="queue-ai-run"><div class="queue-ai-top"><span class="chip run-live">${esc(statusLabels[run.status]||run.status)}</span><span class="queue-ai-percent">${percent}%</span><button type="button" class="text-button" data-review-open="${esc(run.run_id)}">Live ↗</button></div><progress max="100" value="${percent}" aria-label="AI review progress"></progress>${now?`<span class="queue-ai-now">${esc(now)}</span>`:''}</div>`;
 }
 if(run&&attention(run))return `<span class="chip warn">AI: ${esc(statusLabels[run.status]||run.status)}</span>`;
 const cost=run?.cost?.usd!=null?`<span class="queue-ai-cost">${esc(costMoney(run.cost.usd))}</span>`:'';
 // An older report shows the suggested next step right in the row; the side panel explains why.
 const next=canUpdate(pr)&&pr.update_check?.scope!=='full'?updateButton(pr):'';
 return `<div class="queue-ai-done">${workspaceStatusBadge(pr)}${cost}${next}</div>`;
}
function prRow(pr){
 const organize=pr.hidden?'':`<p class="detail-heading">Organize</p>${snoozeControl(pr)}<button class="button hide-pr" data-action="/hide" data-url="${esc(pr.url)}">Hide from inbox</button>`;
 const actions=pr.hidden?`<button class="button primary" data-action="/unhide" data-url="${esc(pr.url)}">Restore PR</button>`:
  queueCaptureButton(pr)+codeWorkspaceLink(pr)+actionDisclosure(pr,'•••',`${organize}<p class="detail-heading">AI tools</p>${aiReviewActions(pr)}`);
 const updated=pr.pr_updated_at||pr.first_seen_at;
 return `<tr class="pr-row" data-pr="${esc(pr.url)}" data-row-open="inbox" tabindex="0" aria-label="Show details for ${esc(pr.owner+'/'+pr.repository)} #${esc(pr.number)}">
  <td class="row-pr">${rowIdentity(pr,snoozeStatus(pr))}</td>
  <td>${prSize(pr)}</td>
  <td>${triageBadge(pr,true)}</td>
  <td class="row-ai">${aiCell(pr)}</td>
  <td class="row-updated" title="${esc(when(updated))}">${esc(since(updated))}</td>
  <td class="row-actions"><div class="pr-actions">${actions}</div></td></tr>`;
}
function prTable(prs){
 return `<div class="pr-table-wrap"><table class="pr-table"><thead><tr><th>Pull request</th><th>Size</th><th>Review load</th><th>AI review</th><th>Updated</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody>${prs.map(prRow).join('')}</tbody></table></div>`;
}
// The side panel re-renders with the list, keeping its open sections.
let drawerUrl=null,drawerKind='inbox';
function renderDrawer(){
 const dialog=$('pr-drawer');if(!dialog.open||!drawerUrl)return;
 const pr=state.prs.find(p=>p.url===drawerUrl);
 if(!pr||(drawerKind==='queue'&&!pr.workflow)){dialog.close();return;}
 const body=$('pr-drawer-body'),fresh=body.dataset.url!==drawerUrl,open=[...body.querySelectorAll('details[open]')].map(d=>d.className);
 const focused=body.contains(document.activeElement)?document.activeElement:null;
 const focusKey=focused&&[focused.tagName,JSON.stringify(focused.dataset),focused.textContent].join('|');
 body.dataset.url=drawerUrl;
 body.innerHTML=drawerKind==='queue'?queueDrawer(pr):card(pr);
 if(!fresh)for(const d of body.querySelectorAll('details'))d.open=open.includes(d.className);
 if(focusKey)[...body.querySelectorAll('button,a,summary')].find(n=>[n.tagName,JSON.stringify(n.dataset),n.textContent].join('|')===focusKey)?.focus({preventScroll:true});
}
function openDrawer(url,kind='inbox',section=''){
 drawerUrl=url;drawerKind=kind;$('pr-drawer-body').dataset.url='';
 if(!$('pr-drawer').open)$('pr-drawer').showModal();
 renderDrawer();
 const target=section&&$('pr-drawer-body').querySelector(section);
 if(target){for(let d=target;d;d=d.parentElement?.closest('details'))d.open=true;target.scrollIntoView({block:'nearest'});}
 $('pr-drawer-close').focus();
}
document.addEventListener('click',event=>{
 const drawer=$('pr-drawer');
 if(event.target.closest('#pr-drawer-close')){drawer.close();return;}
 // The panel is full height, so a click on the dialog itself may still be inside it.
 if(event.target===drawer){const box=drawer.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)drawer.close();return;}
 const row=event.target.closest('[data-row-open]'),control=event.target.closest('a,button,summary,details,input,select,label');
 // Sections are <details> too, so only controls inside the row count.
 if(row&&!(control&&row.contains(control)))openDrawer(row.dataset.pr||row.dataset.queuePr,row.dataset.rowOpen);
});
document.addEventListener('keydown',event=>{
 const row=event.target.closest?.('[data-row-open]');
 if(row&&event.target===row&&(event.key==='Enter'||event.key===' ')){event.preventDefault();openDrawer(row.dataset.pr||row.dataset.queuePr,row.dataset.rowOpen);}
});
$('pr-drawer').addEventListener('close',()=>{drawerUrl=null;});
function queueCaptureButton(pr){const tracked=pr.workflow&&pr.workflow.bucket!=='removed';return `<button class="button ${tracked?'':'primary'}" data-queue-action="${tracked?'show':'enqueue'}" data-url="${esc(pr.url)}">${tracked?'My reviews':'Add to Up next'}</button>`;}
function renderState(){
 const config=state.config;$('effective-agent').textContent=`${config.agent==='codex'?'Codex · in app':'Claude Code'} · ${config.model||'default model'}${config.effort?' · '+config.effort+' effort':''}`;
 const runs=state.prs.filter(pr=>active(pr.run)||attention(pr.run));$('active-runs').textContent=runs.length?'('+runs.length+')':'';
 $('active-run-list').innerHTML=runs.map(pr=>`<div class="activity-run"><a href="${esc(safeUrl(pr.url))}" target="_blank" rel="noopener">${esc(pr.owner+'/'+pr.repository)} #${esc(pr.number)}</a><p>${esc(pr.title)}</p><p class="muted">${esc(statusLabels[pr.run.status]||pr.run.status)} · Recorded ${esc(since(pr.run.updated_at))}</p></div>`).join('')||'<p class="muted">No active AI reviews.</p>';
 renderSyncStatus();
 renderAiSettings();
 renderTriageSettings();
 renderPickers();
 $('watched-repos').innerHTML=config.watched_repos.map(repo=>`<li><span>${esc(repo)}</span><button class="text-button" data-remove-repo="${esc(repo)}" aria-label="Stop watching ${esc(repo)}">Remove</button></li>`).join('')||'<li class="muted">No watched repositories yet.</li>';
 $('host-repos').innerHTML=(config.host_execution_repos||[]).map(repo=>`<li><span>${esc(repo)}</span><button class="text-button" data-remove-host-repo="${esc(repo)}" aria-label="Stop trusting ${esc(repo)}">Remove</button></li>`).join('')||'<li class="muted">No trusted repositories. Blocked checks are reported as blocked.</li>';
 renderList();
 if(typeof renderQueue==='function')renderQueue();
 restoreOverviewScroll();
}
let stateRequest=null;
function loadState(){if(stateRequest)return stateRequest;stateRequest=(async()=>{loading=true;try{const response=await fetch('/api/state');if(!response.ok)throw new Error('Could not read the inbox.');state=await response.json();$('connection').hidden=true;renderState();refreshExpiredSnoozes();}catch(error){$('connection').hidden=false;$('connection').textContent='Connection interrupted. Showing the last loaded inbox; retrying automatically. '+error.message;}finally{loading=false;stateRequest=null;}})();return stateRequest;}
function syncFilterControls(){ $('search').value=filters.search;renderPickers();$('drafts').value=filters.drafts;$('sort').value=filters.sort;$('triage-filter').value=filters.triageEffort;renderFilterPresets();}
function clearFilters(){resetToDefault();}
document.addEventListener('click',async event=>{
 const view=event.target.closest('[data-view]');if(view){if(typeof showQueue==='function')showQueue(false);showReporting(false);filters.view=view.dataset.view;saveFilters();renderList();return;}
 if(event.target.closest('[data-clear]')||event.target.closest('#clear-filters')){resetToDefault();return;}
 if(event.target.closest('#toast-show')){const action=showAction;showAction=null;$('toast').hidden=true;action?.();return;}
 if(event.target.closest('#undo')){const action=undoAction;undoAction=null;$('toast').hidden=true;try{await action?.();}catch(error){notify(error.message);}return;}
 const copy=event.target.closest('[data-copy]');if(copy){try{await navigator.clipboard.writeText(copy.dataset.copy);notify('Session reference copied.');}catch{notify('Could not access the clipboard. Session: '+copy.dataset.copy);}return;}
 const promptButton=event.target.closest('[data-copy-prompt]');if(promptButton){await copyPrompt(promptButton);return;}
 const remove=event.target.closest('[data-remove-repo]');if(remove){try{await post('/remove-repo',{repo:remove.dataset.removeRepo});notify('Repository removed. Sync GitHub to update the inbox.');await loadState();}catch(error){notify(error.message);}return;}
 const untrust=event.target.closest('[data-remove-host-repo]');if(untrust){try{await post('/remove-host-repo',{repo:untrust.dataset.removeHostRepo});notify('Repository removed. Its blocked checks stay blocked.');await loadState();}catch(error){notify(error.message);}return;}
 const guided=event.target.closest('[data-review-guidance]');if(guided){guided.closest('.action-disclosure')?.removeAttribute('open');openGuidance(guided.dataset.url);return;}
 const button=event.target.closest('[data-action]');if(!button||button.disabled)return;
 const {action,url,retry,days,mode}=button.dataset;const launching=action.startsWith('/regenerate-');
 if(launching&&settingsDirty){notify('Save or discard your AI settings before starting a review.');showSettings('ai-settings');return;}
 busy.add(url);button.disabled=true;
 try{const result=await post(action,{url,retry:retry==='true',...(days?{days:Number(days)}:{}),...(mode?{mode}:{})});
  if(launching)return await reviewLaunched(url,result);
  else if(action==='/snooze')notify('Snoozed until '+when(result.snoozed_until)+'.',async()=>{await post('/unsnooze',{url});await loadState();});
  else if(action==='/unsnooze')notify('PR returned to your inbox.');
  else if(action==='/hide')notify('PR hidden.',async()=>{await post('/unhide',{url});await loadState();});
  else if(action==='/unhide')notify('PR restored.');
  await loadState();
 }catch(error){notify(error.message);}finally{busy.delete(url);renderList(true);}
});
async function reviewLaunched(url,result){
 notify(result.existing?'This PR already has an active run.':result.mode==='update'?'AI review update started. You can follow it here.':'AI review started. You can follow it here.');
 await loadState();
 const run=state?.prs.find(p=>p.url===url)?.run;if(run?.transport==='in-app')openReview(run.run_id);
}
let guidanceUrl='',guidanceRequest=0;
function guidanceRevision(source){return source.revision||(!source.head?'Revision not recorded':`Commit ${source.head.slice(0,12)}`);}
function renderGuidanceSources(sources){
 const container=$('guidance-sources');
 const notes=(sources?.notes||[]).map(note=>`<label class="review-context-option"><input type="checkbox" data-guidance-note="${esc(note.id)}"><span><strong>Private note</strong><small>${esc(guidanceRevision(note))}${note.selections?` · ${note.selections} code ${note.selections===1?'selection':'selections'}`:''}</small><span>${esc(note.preview||'Empty note')}</span></span></label>`);
 const conversations=(sources?.conversations||[]).map(thread=>`<label class="review-context-option"><input type="checkbox" data-guidance-conversation="${esc(thread.id)}"><span><strong>Ask AI conversation</strong><small>${esc(guidanceRevision(thread))} · ${thread.messages||0} messages · ${thread.answers||0} ${thread.answers===1?'answer':'answers'}</small><span>${esc(thread.preview||'Conversation')}</span></span></label>`);
 container.innerHTML=notes.concat(conversations).join('')||'<p class="muted">No private notes or Ask AI conversations are saved for this PR.</p>';
 $('guidance-context-count').textContent='No private context selected.';
}
function selectedGuidanceContext(){
 const notes=[...document.querySelectorAll('#guidance-sources [data-guidance-note]:checked')].map(input=>input.dataset.guidanceNote);
 const conversations=[...document.querySelectorAll('#guidance-sources [data-guidance-conversation]:checked')].map(input=>input.dataset.guidanceConversation);
 return notes.length||conversations.length?{notes,conversations}:null;
}
function updateGuidanceSelectionCount(){const count=document.querySelectorAll('#guidance-sources input:checked').length;$('guidance-context-count').textContent=count?`${count} private source${count===1?'':'s'} selected.`:'No private context selected.';}
async function openGuidance(url){
 if(settingsDirty){notify('Save or discard your AI settings before starting a review.');showSettings('ai-settings');return;}
 guidanceUrl=url;const request=++guidanceRequest,pr=state?.prs.find(item=>item.url===url);
 $('guidance-title').textContent=pr?.title||url;$('guidance-text').value='';$('guidance-sources').innerHTML='<p class="muted">Loading saved notes and conversations…</p>';$('guidance-context-count').textContent='No private context selected.';$('guidance-dialog').showModal();$('guidance-text').focus();
 try{
  const query=new URLSearchParams({url,head:pr?.head_sha||''}),response=await fetch('/api/workspace-context?'+query);
  const result=await response.json();if(!response.ok)throw new Error(result.error||'Could not load private context.');
  if(request===guidanceRequest&&guidanceUrl===url)renderGuidanceSources(result);
 }catch(error){if(request===guidanceRequest&&guidanceUrl===url)$('guidance-sources').innerHTML=`<p class="muted">Could not load private context. You can still start the review without it.</p>`;}
}
$('guidance-text').addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.metaKey||event.ctrlKey)){event.preventDefault();$('guidance-form').requestSubmit();}});
$('guidance-sources').addEventListener('change',updateGuidanceSelectionCount);
$('guidance-form').addEventListener('submit',async event=>{
 event.preventDefault();
 const url=guidanceUrl,submit=event.submitter||$('guidance-form').querySelector('[type=submit]');
 if(!url||busy.has(url))return;
 busy.add(url);submit.disabled=true;
 try{const body={url,retry:false,guidance:$('guidance-text').value},context=selectedGuidanceContext();if(context)body.workspace_context=context;const result=await post('/regenerate-review',body);$('guidance-dialog').close();await reviewLaunched(url,result);}
 catch(error){notify(error.message);}finally{submit.disabled=false;busy.delete(url);renderList(true);}
});
for(const [id,key] of [['search','search'],['drafts','drafts'],['sort','sort'],['triage-filter','triageEffort']])$(id).addEventListener(id==='search'?'input':'change',()=>{filters[key]=$(id).value;saveFilters();renderList();});
$('filter-preset').addEventListener('change',()=>{selectedPresetId=$('filter-preset').value;renderFilterPresets();});
$('filter-preset-apply').addEventListener('click',applySelectedPreset);
$('filter-preset-default').addEventListener('click',toggleDefaultPreset);
$('filter-preset-rename').addEventListener('click',renameSelectedPreset);
$('filter-preset-delete').addEventListener('click',deleteSelectedPreset);
$('filter-preset-save').addEventListener('click',saveCurrentPreset);

// Keep a legible avatar fallback if a profile image is missing or unavailable.
document.addEventListener('error',event=>{if(event.target.matches?.('.author-avatar'))event.target.hidden=true;},true);
$('repo-form').addEventListener('submit',async event=>{event.preventDefault();try{await post('/add-repo',{repo:$('add-repo').value});$('add-repo').value='';notify('Repository added. Sync GitHub to load its PRs.');await loadState();}catch(error){notify(error.message);}});
$('host-repo-form').addEventListener('submit',async event=>{event.preventDefault();try{await post('/add-host-repo',{repo:$('add-host-repo').value});$('add-host-repo').value='';notify('Repository trusted. New AI reviews may run its blocked checks outside the sandbox.');await loadState();}catch(error){notify(error.message);}});
$('refresh').addEventListener('click',syncGitHub);
syncFilterControls();
document.addEventListener('DOMContentLoaded',()=>{(async function poll(){await Promise.allSettled([loadState(),loadReporting()]);setTimeout(poll,5000);})();});

// Workspace navigation and utilities are available from every view.
let lastInboxView=filters.view==='mine'?'requested':filters.view;
let syncStarting=false;
const syncRequestErrors={};
const dialogAnimations=new WeakMap();
function animateDialog(dialog,closing=false){
 // Start from the current position if Close interrupts the entrance animation.
 const from=getComputedStyle(dialog).transform;
 dialogAnimations.get(dialog)?.cancel();
 dialog.classList.toggle('is-closing',closing);
 if(matchMedia('(prefers-reduced-motion: reduce)').matches){
  dialogAnimations.delete(dialog);dialog.classList.remove('is-closing');
  if(closing)dialog.close();
  return;
 }
 const animation=dialog.animate(
  [{transform:closing?from:'translateX(100%)'},{transform:closing?'translateX(100%)':'translateX(0)'}],
  {duration:closing?180:220,easing:closing?'cubic-bezier(.4,0,1,1)':'cubic-bezier(.16,1,.3,1)',fill:'both'}
 );
 dialogAnimations.set(dialog,animation);
 animation.finished.then(()=>{
  if(dialogAnimations.get(dialog)!==animation)return;
  if(closing)dialog.close();
  dialogAnimations.delete(dialog);dialog.classList.remove('is-closing');animation.cancel();
 },()=>{}); // Replacing a panel or reversing its entrance cancels that animation.
}
function closeDialog(dialog){
 if(!dialog.open||dialog.classList.contains('is-closing'))return;
 if(dialog.classList.contains('workspace-dialog'))animateDialog(dialog,true);
 else dialog.close();
}
function showDialog(id){
 const dialog=$(id);
 for(const open of document.querySelectorAll('dialog[open]'))if(open!==dialog){
  dialogAnimations.get(open)?.cancel();dialogAnimations.delete(open);
  open.classList.remove('is-closing');open.close();
 }
 if(!dialog.open){dialog.showModal();if(dialog.classList.contains('workspace-dialog'))animateDialog(dialog);}
}
for(const dialog of document.querySelectorAll('.workspace-dialog'))dialog.addEventListener('cancel',event=>{
 event.preventDefault();closeDialog(dialog);
});
function showSettings(section='ai-settings'){
 showDialog('settings');
 document.querySelectorAll('[data-settings-section]').forEach(el=>el.hidden=el.id!==section);
 document.querySelectorAll('[data-settings-panel]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.settingsPanel===section)));
}
function renderWorkspaceNavigation(){
 const inbox=!reportingActive&&(typeof queueActive==='undefined'||!queueActive)&&filters.view!=='mine';
 $('inbox-tab').setAttribute('aria-pressed',String(inbox));
 $('inbox-sources').hidden=!inbox;
 if(inbox)lastInboxView=filters.view;
}
function renderFilterSummary(){
 const parts=[];
 if(filters.search)parts.push('Search: '+filters.search);
 for(const [prefix,label] of [['repositories','Repositories'],['authors','Authors'],['statuses','Statuses']]){
  const n=filters[prefix+'Only'].length+filters[prefix+'Excluded'].length;if(n)parts.push(label+': '+n+' selections');
 }
 if(filters.drafts!=='all')parts.push(filters.drafts==='ready'?'Ready for review':'Drafts only');
 if(filters.triageEffort!=='all')parts.push('Review load: '+(effortLabels[filters.triageEffort]||filters.triageEffort));
 $('filter-count').textContent=parts.length?'('+parts.length+')':'';
 $('active-filters').hidden=!parts.length;$('active-filter-description').textContent=parts.join(' · ');
}
function rememberCardFocus(container){
 const el=document.activeElement,card=el?.closest('.pr-card,.pr-row');if(!card||!container.contains(card))return ()=>{};
 const self=el===card;
 const identity=card.dataset.pr||card.dataset.queuePr, queueHistory=card.dataset.queueHistory, tag=el.tagName, data=JSON.stringify(el.dataset), text=el.textContent;
 return ()=>{const next=[...container.querySelectorAll('.pr-card,.pr-row')].find(c=>(c.dataset.pr||c.dataset.queuePr)===identity&&c.dataset.queueHistory===queueHistory);
  const replacement=next&&(self?next:[...next.querySelectorAll('button,a,summary')].find(n=>n.tagName===tag&&JSON.stringify(n.dataset)===data&&n.textContent===text));
  if(replacement)replacement.focus({preventScroll:true});
 };
}
function renderSyncStatus(){
 if(!state)return;
 const saved=state.prs.filter(pr=>pr.workflow&&pr.workflow.stage!=='removed');
 const queueStamp=(state.queue_refresh?.status==='completed'?state.queue_refresh.finished_at:null)||saved.map(pr=>pr.workflow.checked_at).filter(Boolean).sort()[0];
 const sources=[
  {key:'inbox',label:'Inbox discovery',status:state.refresh,at:state.last_github_refresh_at,error:state.warnings?.join(' ')},
  {key:'queue',label:'Saved reviews and replies',status:state.queue_refresh,at:queueStamp,error:saved.filter(pr=>pr.workflow.error).map(pr=>pr.owner+'/'+pr.repository+' #'+pr.number+': '+pr.workflow.error).join(' ')},
  {key:'reporting',label:'Reporting history',status:reportingData?.refresh,at:reportingData?.updated_at,error:reportLoadError}
 ];
 const problems=[];
 for(const source of sources){const err=syncRequestErrors[source.key]||(source.status?.status==='failed'?source.status.message||'Sync failed.':'')||source.error;if(err)problems.push(source.label+': '+err);source.error=err;}
 // Background checks of saved reviews keep Sync available; a Sync click queues one more pass.
 const running=syncStarting||sources.some(s=>s.status?.status==='running'&&(s.key!=='queue'||s.status.manual));
 $('refresh').disabled=running;$('refresh').querySelector('span').textContent=running?'Syncing…':'Sync GitHub';
 const stamps=sources.map(s=>s.at).filter(Boolean).sort();
 $('freshness').textContent=running?'Syncing GitHub…':problems.length?'Sync needs attention':stamps.length===3?'Synced '+since(stamps[0]):'Sync status';
 $('freshness').classList.toggle('sync-warning',!!problems.length);
 $('sync-sources').innerHTML=sources.map(s=>`<div><dt>${s.label}</dt><dd>${s.status?.status==='running'?'Syncing…':s.at?'Last success '+esc(since(s.at)):'Not synced yet'}${s.error?`<p class="sync-error">${esc(s.error)}</p>`:''}</dd></div>`).join('');
 $('sync-estimates').textContent=state.triage?.config.enabled?'Automatic review load estimates run after sync. Completed estimates are kept.':'Automatic review load estimates are off.';
 $('warnings').hidden=!problems.length;$('warnings').innerHTML=problems.length?`<details><summary>${problems.length} sync ${problems.length===1?'issue':'issues'} · previous data kept</summary><ul>${problems.map(p=>`<li>${esc(p)}</li>`).join('')}</ul></details>`:'';
}
async function syncGitHub(){
 if(syncStarting||$('refresh').disabled)return;
 syncStarting=true;for(const key of Object.keys(syncRequestErrors))delete syncRequestErrors[key];renderSyncStatus();
 const results=await Promise.allSettled([post('/refresh'),post('/refresh-reporting')]);
 if(results[0].status==='rejected')syncRequestErrors.inbox=syncRequestErrors.queue=results[0].reason.message;
 if(results[1].status==='rejected')syncRequestErrors.reporting=results[1].reason.message;
 await Promise.allSettled([loadState(),loadReporting()]);syncStarting=false;renderSyncStatus();
}
$('inbox-tab').addEventListener('click',()=>{showQueue(false);showReporting(false);filters.view=lastInboxView;saveFilters();renderList();});
$('views').addEventListener('click',()=>queueMicrotask(renderWorkspaceNavigation));
// Native dialogs retain edits when closed and provide keyboard focus containment.
document.addEventListener('click',event=>{
 const settings=event.target.closest('[data-settings-panel]');if(settings){showSettings(settings.dataset.settingsPanel);return;}
 const open=event.target.closest('[data-dialog]');if(open){open.dataset.dialog==='settings'?showSettings():showDialog(open.dataset.dialog);return;}
 const close=event.target.closest('[data-close-dialog]');if(close)closeDialog(close.closest('dialog'));
 for(const disclosure of document.querySelectorAll('.action-disclosure[open]'))if(!disclosure.contains(event.target))disclosure.open=false;
});
document.addEventListener('keydown',event=>{if(event.key==='Escape')for(const disclosure of document.querySelectorAll('.action-disclosure[open]')){disclosure.open=false;disclosure.querySelector('summary').focus();}});
