/** Pure workspace transformations; no DOM, network or storage. */
export const contextsOf = (value) =>
  Array.isArray(value?.contexts)
    ? value.contexts
    : value?.context
      ? [value.context]
      : [];
export const contextKey = (context) =>
  JSON.stringify([
    context.path,
    context.base,
    context.head,
    context.side,
    context.ids,
    context.comment || null,
    context.finding || null,
    context.report_head || null,
  ]);
export const emptyState = () => ({
  viewed: [],
  collapsed: [],
  threads: [],
  notes: [],
  attachments: {},
});
export const isRunning = (thread) =>
  thread && ["running", "stopping"].includes(thread.status);
export const isOlder = (thread, comparison) =>
  !!thread?.head &&
  (thread.head !== comparison.head || thread.base !== comparison.base);

export function contextReadLabel(request) {
  if (request.kind === "github_read") return "Authenticated GitHub read";
  if (request.kind === "repository_read") return "Repository source investigation";
  if (request.kind === 'web_search') return `Web search · ${request.query || ''}`;
  if (request.kind === 'open_page') return `Open page · ${request.url || ''}`;
  if (request.kind === 'find_in_page') return `Find “${request.query || ''}” · ${request.url || ''}`;
  const location = `${request.side} · ${request.path || '/'}`;
  if (request.kind === 'search_code') return `Search “${request.query}” · ${location}`;
  return `${request.kind === 'list_files' ? 'List files' : 'Read file'} · ${location}`;
}

export function attach(contexts, context) {
  return contexts.some((item) => contextKey(item) === contextKey(context))
    ? structuredClone(contexts)
    : [...structuredClone(contexts), structuredClone(context)];
}
export function preserveMessageContexts(thread) {
  for (const message of thread.messages) {
    if (!Array.isArray(message.contexts))
      message.contexts = structuredClone(contextsOf(thread));
  }
}
export function uiState(saved) {
  return {
    viewed: [...saved.viewed],
    collapsed: [...saved.collapsed],
    notes: structuredClone(saved.notes),
    attachments: Object.fromEntries(
      saved.threads.map((thread) => [
        thread.id,
        structuredClone(contextsOf(thread)),
      ]),
    ),
  };
}
export function hydrate(saved) {
  const result = { ...emptyState(), ...structuredClone(saved) };
  for (const thread of result.threads) {
    if (Object.hasOwn(result.attachments, thread.id))
      thread.contexts = result.attachments[thread.id];
  }
  return result;
}
export function upsertThread(saved, thread) {
  const index = saved.threads.findIndex((item) => item.id === thread.id);
  if (index < 0) saved.threads.push(thread);
  else saved.threads[index] = thread;
}
export function removeContext(thread, index) {
  preserveMessageContexts(thread);
  const contexts = structuredClone(contextsOf(thread));
  const removed = contexts.splice(index, 1)[0];
  thread.contexts = contexts;
  return removed;
}

/** Only immutable source links for this exact repository/comparison can navigate. */
export function sourceTarget(link, comparison) {
  try {
    const url=new URL(link);
    const prefix='/'+comparison.repository+'/blob/';
    if(url.protocol!=='https:'||url.hostname!=='github.com'||!url.pathname.startsWith(prefix))return null;
    const rest=url.pathname.slice(prefix.length),slash=rest.indexOf('/');
    const sha=rest.slice(0,slash),path=decodeURIComponent(rest.slice(slash+1));
    const lines=/^#L(\d+)(?:-L(\d+))?$/.exec(url.hash);
    const side=sha===comparison.head?'head':sha===comparison.base?'base':null;
    if(!side||!lines||!comparison.files.some(file=>file.path===path||side==='base'&&file.previous===path))return null;
    return {side,path,start:Number(lines[1]),end:Number(lines[2]||lines[1])};
  }catch{return null;}
}
