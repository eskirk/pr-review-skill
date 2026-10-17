'use strict';
let aiDraft=null, aiSaved=null, aiRevision='', aiSaving=false;
const aiFeatures={triage:['Triage','Estimate the review load of a PR before any AI review.'],review:['AI review','Investigate changes and produce review notes.'],chat:['Chat','Ask questions about code in the review workspace.']};
function aiOptions(values,value,label){
 const options=[...new Set(values)];if(!options.includes(value))options.push(value);
 return options.map(v=>`<option value="${esc(v)}" ${v===value?'selected':''}>${esc(v?(values.includes(v)?v:v+' (saved · outside presets)'):label)}</option>`).join('');
}
function aiMarkDirty(){
 settingsDirty=JSON.stringify(aiDraft)!==JSON.stringify(aiSaved);
 triageDirty=JSON.stringify(aiDraft?.triage)!==JSON.stringify(aiSaved?.triage);
 $('ai-save').disabled=!settingsDirty||aiSaving;$('ai-discard').disabled=!settingsDirty||aiSaving;
 $('ai-save-state').textContent=aiSaving?'Saving…':settingsDirty?'Unsaved changes':'All settings saved';
 renderTriageSettings();
}
function aiValidateKnownRepositories(){
 const input=$('known-repositories'),values=aiDraft.known_repositories;
 const invalid=values.some(value=>!/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\/[A-Za-z0-9._-]{1,100}$/.test(value)||['.','..'].includes(value.split('/')[1]));
 const message=values.length>200?'Enter at most 200 repositories.':invalid?'Use owner/repo for each repository (no URLs or wildcards).':'';
 input.setCustomValidity(message);input.setAttribute('aria-invalid',String(Boolean(message)));
 $('known-repositories-error').textContent=message;
}
function aiCards(){
 if(!aiDraft)return;
 const catalog=state.ai.catalog;
 $('ai-cards').innerHTML=Object.entries(aiFeatures).map(([feature,[title,description]],index)=>{
  const entry=aiDraft[feature],profile=entry.profiles[entry.provider],provider=catalog[entry.provider];
  const efforts=provider.model_efforts[profile.model]||provider.efforts;
  const noEffort=efforts.length===1;
  return `<article class="feature-card" data-ai-feature="${feature}"><div class="feature-heading"><span class="feature-number">0${index+1}</span><div><h3>${title}</h3><p>${description}</p></div></div><div>
   <div class="feature-fields"><label>Provider<select id="${feature}-provider" data-ai-field="provider">${Object.entries(catalog).filter(([,v])=>v.features.includes(feature)).map(([key,v])=>`<option value="${key}" ${key===entry.provider?'selected':''}>${esc(v.label)}</option>`).join('')}</select></label>
   <label>Model<select id="${feature}-model" data-ai-field="model">${aiOptions(provider.models,profile.model,'Provider default')}</select></label>
   <label>Reasoning<select id="${feature}-effort" data-ai-field="effort" ${noEffort?'disabled':''}>${aiOptions(efforts,profile.effort,noEffort?'Not supported':'Model default')}</select></label></div>
   <p class="feature-note">${feature==='chat'?'Existing conversations keep their provider, model and reasoning. New conversations use these settings.':feature==='triage'?'A smaller model is usually enough. Completed estimates stay available.':'Runs in the dashboard with your selected provider’s local login.'}${noEffort?' This model has no reasoning override.':''}${entry.provider==='openai'?' Uses OPENAI_API_KEY and separate API billing.':''}</p>
   ${feature==='triage'?`<div class="feature-extra"><label><input id="triage-enabled" type="checkbox" ${entry.enabled?'checked':''}> Estimate after GitHub sync</label><label>Daily call limit <input id="triage-limit" type="number" min="1" max="100" required value="${entry.daily_limit}"></label></div>`:''}
   </div></article>`;
 }).join('')+`<section class="known-repositories-card" aria-labelledby="known-repositories-heading"><h3 id="known-repositories-heading">Repositories I know well</h3><p id="known-repositories-help">Explanations skip familiar repository basics for these repositories. Use one owner/repo per line, up to 200. Names are case-insensitive. Leave empty for introductions in every repository.</p><label for="known-repositories">Repositories</label><textarea id="known-repositories" rows="5" maxlength="40000" spellcheck="false" autocapitalize="none" aria-describedby="known-repositories-help known-repositories-error" placeholder="grafana/grafana\ngrafana/faro-web-sdk">${esc(aiDraft.known_repositories.join('\n'))}</textarea><p id="known-repositories-error" class="known-repositories-error" aria-live="polite"></p></section>`;
 aiValidateKnownRepositories();
 aiMarkDirty();
}
function renderAiSettings(){
 if(!state?.ai)return;
 if(!aiDraft||(!settingsDirty&&aiRevision!==state.ai.revision)){
  aiSaved=structuredClone(state.ai.settings);aiDraft=structuredClone(aiSaved);aiRevision=state.ai.revision;aiCards();
 }
}
document.addEventListener('DOMContentLoaded',()=>{
 $('ai-cards').addEventListener('change',event=>{
  const feature=event.target.closest('[data-ai-feature]')?.dataset.aiFeature;if(!feature)return;
  const field=event.target.dataset.aiField,entry=aiDraft[feature];
  if(field==='provider'){entry.provider=event.target.value;aiCards();$(feature+'-provider').focus();return;}
  if(field){
   const profile=entry.profiles[entry.provider];profile[field]=event.target.value;
   if(field==='model'){
    const provider=state.ai.catalog[entry.provider],efforts=provider.model_efforts[profile.model]||provider.efforts;
    if(!efforts.includes(profile.effort)){profile.effort='';notify('Reasoning reset to the model default.');}
    aiCards();$(feature+'-model').focus();return;
   }
  }else if(event.target.id==='triage-enabled')entry.enabled=event.target.checked;
  else if(event.target.id==='triage-limit')entry.daily_limit=Number(event.target.value);
  aiMarkDirty();
 });
 $('ai-cards').addEventListener('input',event=>{
  if(event.target.id==='known-repositories'){
   aiDraft.known_repositories=event.target.value.split(/\r?\n/).map(value=>value.trim()).filter(Boolean);
   aiValidateKnownRepositories();aiMarkDirty();
  }else if(event.target.id==='triage-limit'){aiDraft.triage.daily_limit=Number(event.target.value);aiMarkDirty();}
 });
 $('ai-discard').addEventListener('click',()=>{aiDraft=null;settingsDirty=false;renderAiSettings();});
 $('ai-form').addEventListener('submit',async event=>{
  event.preventDefault();if(aiSaving)return;aiSaving=true;aiMarkDirty();$('ai-fields').disabled=true;
  try{await post('/ai-config',{settings:aiDraft,revision:aiRevision});aiDraft=null;settingsDirty=false;triageDirty=false;await loadState();notify('AI settings saved. New work uses these choices.');}
  catch(error){notify(error.message);}
  finally{aiSaving=false;$('ai-fields').disabled=false;aiMarkDirty();}
 });
});
