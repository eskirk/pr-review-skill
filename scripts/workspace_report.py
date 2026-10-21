"""Add safe workspace entry points and local exploration affordances to reports."""
import html
import re
from urllib.parse import urlencode

PR_LINK = re.compile(r'<a href="(https://github\.com/[^"<>]+/pull/[1-9][0-9]*)"[^>]*>Open pull request</a>')

EMBED_STYLE = '''<style id="workspace-report-style">
html,body{margin:0!important;min-height:0!important;height:auto!important;background:var(--bg)!important}
body{display:flow-root;font:14px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
body>main{width:100%;max-width:none;margin:0;padding:0 0 32px}
.topbar,#theme,.pr-link{display:none!important}
h1{font-size:1.5rem;line-height:1.3;margin:0 0 16px}
.outcome{font-size:1rem;max-width:none}
/* Walk reports: no inner frame or paper background; the workspace is the frame. */
html[data-layout=walk] body{background-image:none!important;font-family:var(--w-sans)}
html[data-layout=walk] body>main.walk-page{max-width:none;padding:0 0 32px}
html[data-layout=walk] .walk{border:0;border-radius:0;box-shadow:none;background:transparent;overflow:visible}
html[data-layout=walk] .walk>header{padding:0 0 22px}
html[data-layout=walk] .walk>header h1{font-size:clamp(1.6rem,2.6vw,2.2rem);max-width:40ch}
html[data-layout=walk] .walk-body{border-top:1px solid var(--w-rule)}
html[data-layout=walk] .walk-rail{background:transparent;padding-left:0}
html[data-layout=walk] .walk-scenes{padding-right:0}
.workspace-finding-actions{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 0}
.workspace-finding-actions button{font:inherit;font-size:12px;padding:6px 10px}
</style>'''
BRIDGE = r'''<script>
(()=>{
 let lastHeight=0;
 const resize=()=>{const height=Math.ceil(Math.max(1,...[...document.body.children].filter(el=>el.getBoundingClientRect().height&&getComputedStyle(el).position!=='fixed').map(el=>el.getBoundingClientRect().bottom+window.scrollY+(parseFloat(getComputedStyle(el).marginBottom)||0))));if(height>0&&height!==lastHeight){lastHeight=height;parent.postMessage({type:'workspace-report-size',height},'*');}};
 const observer=new ResizeObserver(resize);
 observer.observe(document.body);
 for(const element of document.body.children)observer.observe(element);
 document.addEventListener('toggle',resize,true);
 window.addEventListener('message',event=>{
  if(event.source!==parent||event.data?.type!=='workspace-report-theme')return;
  const {theme,colors}=event.data;
  if(!['light','dark'].includes(theme))return;
  document.documentElement.dataset.theme=theme;
  for(const key of ['bg','panel','fg','muted','line','accent','soft']){
   if(typeof colors?.[key]==='string')document.documentElement.style.setProperty('--'+key,colors[key]);
  }
  // Walk reports take the workspace's surfaces and keep their own status colours.
  if(document.documentElement.dataset.layout==='walk')for(const [walk,key] of [['page','bg'],['paper','bg'],['paper-2','soft'],['ink','fg'],['muted','muted'],['rule','line']]){
   if(typeof colors?.[key]==='string')document.documentElement.style.setProperty('--w-'+walk,colors[key]);
  }
  resize();
 });
 parent.postMessage({type:'workspace-report-ready'},'*');
 if(document.documentElement.dataset.layout==='walk')parent.postMessage({type:'workspace-report-layout',layout:'walk'},'*');
 resize();
 document.addEventListener('click',event=>{
  const anchor=event.target.closest('a[href^="#"]');
  // The walk's scene rail handles its own links (and prevents the default).
  if(!anchor||event.defaultPrevented)return;
  let target;try{target=document.getElementById(decodeURIComponent(anchor.hash.slice(1)));}catch{return;}
  if(target){event.preventDefault();parent.postMessage({type:'workspace-report-scroll',top:target.getBoundingClientRect().top+window.scrollY},'*');}
 });
 const sourceLink=anchor=>{try{const u=new URL(anchor.href);return u.hostname==='github.com'&&/^\/[^/]+\/[^/]+\/blob\/[0-9a-f]{40}\//.test(u.pathname)&&/^#L\d+(?:-L\d+)?$/.test(u.hash);}catch{return false;}};
 const send=(anchor,action)=>parent.postMessage({type:'workspace-code',action,url:anchor.href},'*');
 const sendFinding=(finding,action,title='')=>parent.postMessage({type:'workspace-finding',action,finding,title},'*');
 document.addEventListener('click',event=>{
  const anchor=event.target.closest('a');
  if(event.isTrusted&&anchor&&sourceLink(anchor)){event.preventDefault();send(anchor,'inspect');}
 });
 for(const anchor of document.querySelectorAll('a[href]')){
  if(!sourceLink(anchor))continue;
  anchor.title='Explore these lines in Code changes';
  const ask=document.createElement('button');ask.type='button';ask.textContent='Ask AI';
  ask.style.cssText='margin-left:8px;font:inherit;font-size:12px';
  ask.addEventListener('click',event=>{if(event.isTrusted)send(anchor,'ask');});
  anchor.after(ask);
 }
 const findings=[...document.querySelectorAll('details.review-finding')];
 findings.forEach((finding,index)=>{
  const id=finding.id||`finding-${index+1}`;if(!finding.id)finding.id=id;
  const title=finding.querySelector(':scope > summary')?.textContent.trim()||`Finding ${index+1}`;
  const actions=document.createElement('div');actions.className='workspace-finding-actions';
  const ask=document.createElement('button');ask.type='button';ask.textContent='Ask AI about this finding';
  ask.addEventListener('click',event=>{if(event.isTrusted)sendFinding(id,'ask',title);});actions.append(ask);
  if(finding.querySelector('.review-comment')){
   const post=document.createElement('button');post.type='button';post.textContent='Post draft on my behalf';
   post.addEventListener('click',event=>{if(event.isTrusted)sendFinding(id,'post',title);});actions.append(post);
  }
  finding.querySelector(':scope > summary')?.after(actions);
 });
 window.addEventListener('message',event=>{
  if(event.source!==parent||event.data?.type!=='workspace-report-focus-finding')return;
  const finding=findings[Number(event.data.index)-1];
  if(!finding)return;
  finding.open=true;finding.scrollIntoView({block:'start'});
 });
})();
</script>'''


def standalone(body):
    """Add a navigation-only CTA without giving the opaque report API access."""
    if 'workspace-report-cta' in body:
        return body
    match = PR_LINK.search(body)
    if not match:
        return body
    href = '/workspace?' + urlencode({'url': html.unescape(match.group(1)), 'tab': 'review'})
    cta = ('<p class="workspace-report-cta"><a class="pr-link" href="' + html.escape(href, quote=True) +
           '" target="_blank" rel="noopener">Ask AI or post a finding in workspace</a></p>')
    marker = '<section id="review-findings"'
    if marker in body:
        return body.replace(marker, cta + marker, 1)
    return body.replace('</header>', cta + '</header>', 1)


def embed(body):
    # Appended after the report so links already exist. No report content is
    # interpolated into JavaScript; the parent validates every message/link.
    return body + EMBED_STYLE + BRIDGE
