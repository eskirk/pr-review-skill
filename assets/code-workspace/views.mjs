import { diffEntries, splitPairs } from "./diff.mjs";
import { contextsOf } from "./model.mjs";
export const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const basename = (path) => path.split("/").pop();
export function sourceLinksHTML(sources) {
  const links = (Array.isArray(sources) ? sources : []).slice(0, 12).map((source, index) => {
    try {
      const url = new URL(source.url);
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return '';
      return `<li value="${index + 1}"><a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${esc(source.title || url.hostname)}</a></li>`;
    } catch { return ''; }
  }).join('');
  return links ? `<div class="message-sources"><strong>Sources</strong><ol>${links}</ol></div>` : '';
}
function highlight(text) {
  return text
    .split(
      /('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|\b(?:export|import|from|interface|class|private|const|return|if|try|catch|finally|throw|new|async|await|void|number|boolean|undefined|false|true)\b)/g,
    )
    .map((part, i) =>
      i % 2
        ? `<span class="${/^['"]/.test(part) ? "token-string" : "token-keyword"}">${esc(part)}</span>`
        : esc(part),
    )
    .join("");
}
function gapHTML(index, gap, pair = "") {
  return `<button class="context-gap" ${pair} data-expand="${index}" data-start="${gap.start}" data-end="${gap.end}">↕ Show ${Math.min(12, gap.count)} more lines <span>(${gap.count} hidden)</span></button>`;
}
/** Annotations (review threads) follow their row; split lanes get matching spacers. */
function withAnnotations(pairs, annotate) {
  if (!annotate) return pairs;
  const result = [];
  for (const pair of pairs) {
    result.push(pair);
    const notes = ["base", "head"].map((side, lane) =>
      pair[lane] && !pair[lane].gap ? annotate(pair[lane], side) : "",
    );
    if (notes.some(Boolean)) result.push({ notes });
  }
  return result;
}
function splitRows(index, entries, base, head, annotate) {
  const pairs = withAnnotations(splitPairs(entries), annotate);
  return `<div class="split-diff">${["base", "head"]
    .map(
      (side, lane) =>
        `<section class="split-pane" aria-label="${side === "base" ? "Base" : "Head"} version"><div class="split-heading">${side === "base" ? "Base" : "Head"} <code>${esc((side === "base" ? base : head).slice(0,12))}</code></div><div class="split-line-list">${pairs
          .map((pair, n) => {
            if (pair.notes)
              return pair.notes[lane]
                ? `<div class="row-annotations" data-pair="${n}">${pair.notes[lane]}</div>`
                : `<div class="split-blank annotation-blank" data-pair="${n}" aria-hidden="true"></div>`;
            const row = pair[lane];
            if (!row)
              return `<div class="split-blank" data-pair="${n}" aria-hidden="true"></div>`;
            if (row.gap) return gapHTML(index, row, `data-pair="${n}"`);
            const number = side === "base" ? row.old : row.new;
            return `<div class="code-row split-cell ${row.kind}" data-pair="${n}" data-side="${side}" data-file="${index}" data-row="${row.id}"><button class="line-number" data-line="${side}" aria-label="Select ${side} line ${number}">${number}</button><span class="line-sign">${row.kind === "add" ? "+" : row.kind === "delete" ? "−" : " "}</span><code>${highlight(row.text) || " "}</code></div>`;
          })
          .join("")}</div></section>`,
    )
    .join("")}</div>`;
}
const annotationHTML = (html) =>
  html ? `<div class="row-annotations">${html}</div>` : "";
export function renderFileRows(
  file,
  index,
  { mode, layout, extra, base, head, loading, annotate },
) {
  if (!file.rows)
    return `<div class="empty-code"><p>${esc(file.error || "Load this file to explore its diff and complete source.")}</p><button class="button" data-load-file="${index}" ${loading ? "disabled" : ""}>${loading ? "Loading…" : file.error ? "Retry file" : "Load diff"}</button></div>`;
  const entries = diffEntries(file, mode, extra);
  if (layout === "split" && !mode)
    return splitRows(index, entries, base, head, annotate);
  return (
    entries
      .map((row) => {
        if (row.gap) return gapHTML(index, row);
        const kind = mode ? "context" : row.kind;
        return `<div class="code-row ${kind}" data-file="${index}" data-row="${row.id}"><button class="line-number" data-line="base" aria-label="Select base line ${row.old ?? "not present"}" ${row.old === null ? "disabled" : ""}>${row.old ?? ""}</button><button class="line-number" data-line="head" aria-label="Select head line ${row.new ?? "not present"}" ${row.new === null ? "disabled" : ""}>${row.new ?? ""}</button><span class="line-sign">${kind === "add" ? "+" : kind === "delete" ? "−" : " "}</span><code>${highlight(row.text) || " "}</code></div>${annotationHTML(annotate?.(row))}`;
      })
      .join("") ||
    '<p class="empty-code">This file does not exist at this revision.</p>'
  );
}
const contextName = (context) =>
  context.kind === "comment"
    ? "Comment" + (context.path ? " · " + basename(context.path) : "")
    : context.kind === "finding"
      ? "AI review finding"
      : basename(context.path);
/** "code selections" when every attachment is code; comments and findings are generic attachments. */
export function attachmentCount(contexts) {
  const code = contexts.every((c) => c.kind !== "comment" && c.kind !== "finding"),
    one = contexts.length === 1;
  return `${contexts.length} ${code ? (one ? "code selection" : "code selections") : one ? "attachment" : "attachments"}`;
}
export function contextHTML(context, index) {
  const comment = context.kind === "comment",
    finding = context.kind === "finding",
    label = finding ? "Review finding" : comment ? "GitHub comment" : `Selected code · ${context.ids.length} lines`;
  return `<div class="context-attachment"><div class="context-heading"><button data-context-jump="${index}">${esc(contextName(context))} · ${esc(context.label)}</button><button class="context-remove" data-remove-context="${index}" aria-label="Remove ${finding ? "finding" : comment ? "comment" : "code"} context: ${esc(contextName(context))} ${esc(context.label)}" title="Remove from future questions. Earlier messages keep their context.">×</button></div><p>${esc(finding ? "AI review report" : context.path || "Pull request conversation")} · ${esc(context.report_head || (context.side === "base" ? context.base : context.head))}</p><details><summary>${label}</summary><pre>${esc(context.snippet)}</pre></details></div>`;
}
export function messageContextHTML(message, index, thread) {
  const contexts = Array.isArray(message.contexts)
    ? message.contexts
    : contextsOf(thread);
  if (message.role !== "user" || !contexts.length) return "";
  return `<details class="message-contexts"><summary>${attachmentCount(contexts)} + PR diff</summary>${contexts.map((context, n) => `<button class="text-button" data-message-context="${index}" data-context-index="${n}">${esc(contextName(context))} · ${esc(context.label)}</button>`).join("")}</details>`;
}
