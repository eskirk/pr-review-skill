import assert from "node:assert/strict";
import {
  diffEntries,
  splitPairs,
  selectionFor,
} from "../../assets/code-workspace/diff.mjs";
import {
  attach,
  removeContext,
  hydrate,
  uiState,
  isOlder,
} from "../../assets/code-workspace/model.mjs";
import { SaveQueue } from "../../assets/code-workspace/api.mjs";
const rows = Array.from({ length: 20 }, (_, id) => ({
  id,
  kind: id === 10 ? "add" : "context",
  old: id === 10 ? null : id + 1,
  new: id + 1,
  text: "line " + id,
}));
const file = { path: "a.ts", rows },
  data = { files: [file], base: "a", head: "b" };
const entries = diffEntries(file);
assert.equal(entries[0].gap, true);
assert.equal(entries[0].count, 7);
assert.equal(entries.at(-1).gap, true);
assert.equal(diffEntries(file, "head").length, 20);
const selection = selectionFor(data, 0, 10, 12, "head", true);
assert.deepEqual(selection.ids, [10, 11, 12]);
assert.equal(selection.label, "Head L11–13");
assert.deepEqual(selectionFor(data, 0, 10, 12, "base", true).ids, [11, 12]);
const pairs = splitPairs([
  { kind: "delete", id: 1 },
  { kind: "add", id: 2 },
  { kind: "add", id: 3 },
]);
assert.equal(pairs.length, 2);
assert.equal(pairs[1][0], undefined);
assert.equal(attach([selection], selection).length, 1);
const thread = {
  id: "one",
  context: selection,
  messages: [{ role: "user", text: "Old" }],
};
removeContext(thread, 0);
assert.equal(thread.contexts.length, 0);
assert.equal(thread.messages[0].contexts.length, 1);
const state = hydrate({
  threads: [thread],
  attachments: { one: [selection] },
  viewed: ["a.ts"],
});
assert.equal(state.threads[0].contexts.length, 1);
assert.equal(uiState(state).attachments.one.length, 1);
assert.equal(isOlder({ base: "a", head: "c" }, data), true);
let releases = [],
  calls = [];
const queue = new SaveQueue(
  {
    request: (_, body) =>
      new Promise((resolve) => {
        calls.push(body);
        releases.push(resolve);
      }),
  },
  "rev",
  2,
  (error) => {
    throw error;
  },
);
queue.enqueue({ viewed: ["a"] });
queue.enqueue({ viewed: ["a", "b"] });
queue.enqueue({ viewed: ["b"] });
assert.equal(calls.length, 1);
releases.shift()({ version: 3 });
await new Promise((resolve) => setImmediate(resolve));
assert.equal(calls.length, 2);
assert.equal(calls[1].version, 3);
assert.deepEqual(calls[1].viewed, ["b"]);
releases.shift()({ version: 4 });
await queue.flush();
assert.equal(queue.version, 4);
let failure;
const broken = new SaveQueue(
  {
    request: async () => {
      throw new Error("conflict");
    },
  },
  "rev",
  0,
  (e) => (failure = e),
);
broken.enqueue({});
await assert.rejects(() => broken.flush(), /could not be saved/);
assert.equal(failure.message, "conflict");
console.log(
  "Workspace model checks passed: diff projections, selections, attachment history, revisions and serialized saves.",
);

const {renderFileRows,contextHTML}=await import('../../assets/code-workspace/views.mjs');
const unsafe={...file,rows:[{id:0,old:null,new:1,kind:'add',text:'<img src=x onerror=alert(1)>'}]};
const rendered=renderFileRows(unsafe,0,{layout:'split',base:'a',head:'b'});
assert.ok(!rendered.includes('<img'));assert.ok(rendered.includes('&lt;img'));
assert.ok(contextHTML({...selection,path:'<img>.ts',snippet:'<script>bad()</script>'},0).includes('&lt;script&gt;'));
console.log('Workspace rendering checks passed: source and context escaping.');
const {sourceTarget}=await import('../../assets/code-workspace/model.mjs');
const pinned={repository:'owner/repo',head:'b'.repeat(40),base:'a'.repeat(40),files:[{path:'src/a.ts'}]};
assert.deepEqual(sourceTarget('https://github.com/owner/repo/blob/'+pinned.head+'/src/a.ts#L4-L7',pinned),{path:'src/a.ts',side:'head',start:4,end:7});
assert.equal(sourceTarget('https://github.com/elsewhere/repo/blob/'+pinned.head+'/src/a.ts#L4',pinned),null);
assert.equal(sourceTarget('https://github.com/owner/repo/blob/main/src/a.ts#L4',pinned),null);

const {reviewHTML, unavailableHTML} = await import('../../assets/code-workspace/review.mjs');
const {esc} = await import('../../assets/code-workspace/views.mjs');
const run = {run_id: 'saved-run', status: 'running', transport: 'terminal'};
assert.ok(!reviewHTML({run}, pinned, esc).includes('Review activity'));
assert.ok(reviewHTML({run: {...run, transport: 'in-app'}}, pinned, esc).includes('/?review=saved-run'));
const finished = {run: {...run, status: 'completed'}, artifact: {version: '1', head_sha: pinned.head, status: 'completed'}};
assert.ok(!reviewHTML(finished, pinned, esc).includes('data-continue'));
const resumable = reviewHTML({...finished, continuation: {agent: '<Claude>', command: 'claude', prompt: 'p'}}, pinned, esc);
assert.ok(resumable.includes('data-continue="command"') && resumable.includes('data-continue="prompt"'));
assert.ok(resumable.includes('Continue in &lt;Claude&gt;'));
const expired = reviewHTML({...finished, continuation: {agent: 'Codex', unavailable: 'Gone <now>'}}, pinned, esc);
assert.ok(expired.includes('disabled title="Gone &lt;now&gt;"') && !expired.includes('data-continue'));
assert.ok(!reviewHTML({run, continuation: {agent: 'Codex', command: 'c', prompt: 'p'}}, pinned, esc).includes('data-continue'));
const stalled = reviewHTML({run: {...run, status: 'no-activity'}}, pinned, esc);
assert.ok(stalled.includes('No recent activity') && stalled.includes('Start a new review.') && stalled.includes('id="generate-review"'));
// Reports of an older commit offer an update unless the fixed rules require a full review.
const older = {run: {...run, status: 'completed'}, artifact: {name: 'review-html', version: '1', head_sha: 'c'.repeat(40), status: 'completed'}};
assert.ok(!reviewHTML(finished, pinned, esc).includes('generate-review-update'));
assert.ok(reviewHTML(finished, pinned, esc).includes('Run full AI review'));
assert.ok(reviewHTML(older, pinned, esc).includes('id="generate-review-update"'));
assert.ok(!reviewHTML({...older, run}, pinned, esc).includes('generate-review-update'));
const advised = reviewHTML({...older, update_check: {scope: 'update', decided_by: 'model', reason: 'Small <fix>.'}}, pinned, esc);
assert.ok(advised.includes('Update suggested: Small &lt;fix&gt;.') && advised.includes('generate-review-update'));
const ruled = reviewHTML({...older, update_check: {scope: 'full', decided_by: 'rules', reason: 'Rebased.'}}, pinned, esc);
assert.ok(ruled.includes('Full review suggested: Rebased.') && !ruled.includes('generate-review-update'));
const fallback = unavailableHTML(new Error('<offline>'), {artifact: {path: '/tmp/review & notes.html'}}, esc);
assert.ok(fallback.includes('&lt;offline&gt;'));
assert.ok(fallback.includes('/artifact?path=%2Ftmp%2Freview+%26+notes.html'));
assert.ok(fallback.includes('Its commit could not be checked'));
assert.equal(unavailableHTML(new Error('Offline'), null, esc), 'Offline');

const {chatProgress, activityHTML, loadProgress} = await import('../../assets/code-workspace/progress.mjs');
assert.deepEqual(loadProgress(null), {percent:null, label:'Connecting to GitHub'});
assert.deepEqual(loadProgress({step:'Reading the base file tree', done:6, total:11}, 2500), {percent:55, label:'Reading the base file tree'});
assert.deepEqual(loadProgress({step:'Restoring your review state', done:11, total:11}, 65000), {percent:99, label:'Restoring your review state · 1m 5s'});
const progressThread = {status:'running', started_at:100, progress:'Reading file…', activity:[{at:102,text:'<source>'}]};
assert.equal(chatProgress(progressThread, 165000), 'Reading file… · 1m 5s');
assert.equal(chatProgress({...progressThread,status:'stopping'}), 'Stopping…');
assert.equal(chatProgress({...progressThread,status:'completed'}), '');
assert.ok(activityHTML(progressThread).includes('&lt;source&gt;'));
const {contextReadLabel} = await import('../../assets/code-workspace/model.mjs');
assert.equal(contextReadLabel({kind:'search_code',query:'flush',side:'head',path:''}), 'Search “flush” · head · /');
assert.equal(contextReadLabel({kind:'open_page',url:'https://example.com'}), 'Open page · https://example.com');
const {sourceLinksHTML} = await import('../../assets/code-workspace/views.mjs');
assert.equal(sourceLinksHTML([{title:'bad',url:'javascript:alert(1)'}]), '');
assert.equal(sourceLinksHTML([{title:'bad',url:'https://user:password@example.com/'}]), '');
assert.ok(sourceLinksHTML([{title:'<script>',url:'https://example.com/?a=1&b=2'}]).includes('&lt;script&gt;'));
assert.ok(sourceLinksHTML([{title:'Spec',url:'https://example.com'}]).includes('rel="noopener noreferrer"'));

assert.ok(!reviewHTML({run}, pinned, esc).includes("Explore code</button>"));

const comments = await import('../../assets/code-workspace/comments.mjs');
const commentFile = {path:'src/a.ts',rows:[
  {id:0,old:1,new:1,kind:'context',text:'a'},{id:1,old:2,new:null,kind:'delete',text:'b'},
  {id:2,old:null,new:2,kind:'add',text:'c'},{id:3,old:3,new:3,kind:'context',text:'d'}]};
const person = (author, body, extra = {}) => ({id:author+body,author,body,association:'MEMBER',created_at:'2026-01-01T00:00:00Z',url:'https://github.com/o/r/pull/1#x',...extra});
const reviewThread = (id, side, line, extra = {}) => ({id,path:'src/a.ts',side,line,start_line:null,original_line:line,outdated:false,resolved:false,file_level:false,hidden_comments:0,diff_hunk:'',comments:[person('sam','Look <img src=x onerror=alert(1)>')],...extra});
const threads = [reviewThread('head',  'head', 2), reviewThread('base', 'base', 2), reviewThread('ctx', 'base', 3),
  reviewThread('old', 'head', null, {outdated:true, original_line:9}), reviewThread('gone', 'head', 99),
  reviewThread('bot', 'head', 1, {comments:[person('ci[bot]','Coverage',{bot:true})]}), reviewThread('done','head',1,{resolved:true})];
const placed = comments.placeThreads(commentFile, threads);
assert.deepEqual([...placed.byRow.entries()].map(([id, list]) => [id, list.map(t => t.id)]), [[2,['head']],[1,['base']],[3,['ctx']],[0,['bot','done']]]);
assert.deepEqual(placed.other.map(t => t.id), ['old','gone']);
assert.deepEqual(comments.placeThreads(commentFile, threads, {mode:'head'}).other.map(t => t.id), ['base','ctx','old','gone']);
assert.equal(comments.placeThreads(commentFile, threads, {placed:false}).byRow.size, 0);
const filter = (mode, bots = true) => threads.filter(t => comments.isShown(t, {mode, bots})).map(t => t.id);
assert.ok(!filter('unresolved').includes('done'));
assert.ok(!filter('all', false).includes('bot'));
assert.deepEqual(filter('hidden'), []);
assert.ok(comments.isShown(threads[6], {mode:'hidden', bots:true}, 'done'));
const pinnedComparison = {base:'a'.repeat(40), head:'b'.repeat(40)};
const commentCtx = comments.commentContext({...threads[0], start_line:1}, pinnedComparison, commentFile, 0);
assert.deepEqual([commentCtx.kind, commentCtx.comment, commentCtx.ids, commentCtx.label], ['comment','head',[0,2],'@sam · Head L2']);
assert.notEqual((await import('../../assets/code-workspace/model.mjs')).contextKey(commentCtx), (await import('../../assets/code-workspace/model.mjs')).contextKey({...commentCtx, comment:'other'}));
const html = comments.threadHTML(threads[0], true);
assert.ok(!html.includes('<img') && html.includes('&lt;img'));
assert.ok(html.includes('data-comment-draft="head"') && html.includes('rel="noopener noreferrer"'));
assert.ok(!comments.threadHTML({...threads[0], comments:[person('x','y',{url:'javascript:alert(1)'})]}, true).includes('javascript:'));
assert.ok(comments.threadHTML(reviewThread('s','head',2,{comments:[person('sam','```suggestion\nfix\n```')]}), true).includes('Suggested change'));
// Split view inserts matching spacers so both panes keep the same row pairs.
const annotated = renderFileRows(commentFile, 0, {layout:'split', base:'a', head:'b', annotate:(row, side) => (placed.byRow.get(row.id) || []).filter(t => t.side === side).map(t => `<i data-t="${t.id}"></i>`).join('')});
const panes = annotated.split('class="split-pane"').slice(1).map(pane => (pane.match(/data-pair=/g) || []).length);
assert.equal(panes[0], panes[1]);
assert.ok(annotated.includes('data-t="head"') && annotated.includes('data-t="base"') && annotated.includes('annotation-blank'));
const unifiedHTML = renderFileRows(commentFile, 0, {layout:'unified', annotate:row => row.id === 2 ? '<i data-t="u"></i>' : ''});
assert.ok(unifiedHTML.indexOf('data-row="2"') < unifiedHTML.indexOf('data-t="u"'));
console.log('Workspace comment checks passed: placement, filters, attachments, escaping and split alignment.');
