import {
  esc,
  renderFileRows,
  contextHTML,
  messageContextHTML,
  sourceLinksHTML,
  attachmentCount,
} from "./views.mjs";
import {
  COMMENT_MODES,
  DRAFT_PROMPT,
  ADDRESSED_PROMPT,
  placeable,
  isShown,
  placeThreads,
  findComment,
  commentContext,
  excerptOf,
  threadHTML,
  conversationHTML,
} from "./comments.mjs";
import {
  contextsOf,
  contextKey,
  contextReadLabel,
  attach,
  removeContext,
  preserveMessageContexts,
  uiState,
  hydrate,
  upsertThread,
  isRunning,
  isOlder,
  sourceTarget,
} from "./model.mjs";
import { visibleRows as projectRows, selectionFor } from "./diff.mjs";
import { WorkspaceAPI, SaveQueue } from "./api.mjs";
import { reviewHTML, unavailableHTML } from "./review.mjs";
import { chatProgress, activityHTML, loadProgress } from "./progress.mjs";
import { chatMarkdown } from "./chat-markdown.mjs";
import { installChatResize } from "./chat-resize.mjs";
(() => {
  const $ = (id) => document.getElementById(id);

  const initialControls = [
    ...document.querySelectorAll("button,select,input,textarea"),
  ];
  initialControls.forEach((control) => (control.disabled = true));
  installChatResize($("conversation"), $("chat-resize"), $("workspace-body"));
  const params = new URLSearchParams(location.search);
  const api = new WorkspaceAPI(
    params.get("url"),
    document.querySelector('meta[name="csrf-token"]').content,
  );
  let saver,
    chatStarting = false,
    chatTimer,
    reviewTimer;
  const loadingFiles = new Map();
  const fileObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const index = Number(entry.target.dataset.fileIndex);
        if (
          entry.isIntersecting &&
          loadingFiles.size < 3 &&
          !data.files[index].rows &&
          !data.files[index].error
        )
          ensureFile(index);
      }
    },
    { root: document.querySelector(".diff-column"), rootMargin: "250px" },
  );
  function storageError(error) {
    $("storage-error").textContent = error.message;
    $("storage-error").hidden = false;
  }
  async function ensureFile(index) {
    if (data.files[index]?.rows) return true;
    if (loadingFiles.has(index)) return loadingFiles.get(index);
    const task = (async () => {
      try {
        data.files[index] = await api.file(
          data.revision,
          data.files[index].path,
        );
        return true;
      } catch (error) {
        data.files[index].error = error.message;
        return false;
      } finally {
        loadingFiles.delete(index);
        renderFiles();
      }
    })();
    loadingFiles.set(index, task);
    return task;
  }
  async function updateReview() {
    try {
      data.review = await api.review(data.head);
      renderReview();
    } catch (error) {
      notify(error.message);
    }
    reviewTimer = setTimeout(updateReview, 15000);
  }
  async function pollChat(id) {
    clearTimeout(chatTimer);
    try {
      const next = await api.chat(id),
        existing = saved.threads.find((t) => t.id === id);
      if (existing) next.contexts = contextsOf(existing);
      upsertThread(saved, next);
      if (threadId === id) renderChat();
      if (isRunning(next)) chatTimer = setTimeout(() => pollChat(id), 1000);
    } catch (error) {
      $("chat-status").textContent = error.message + " Reconnecting…";
      chatTimer = setTimeout(() => pollChat(id), 3000);
    }
  }
  window.addEventListener("beforeunload", (event) => {
    if (saver?.running || saver?.failed) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  let data,
    saved = { viewed: [], collapsed: [], threads: [], notes: [] },
    selection = null,
    threadId = null,
    activeFile = 0,
    toastTimer;
  let tab = params.get("tab") === "review" ? "review" : "code";
  let layoutPreference = "unified",
    diffLayout = "unified";
  try {
    if (localStorage.getItem("pr-code-diff-layout") === "split")
      layoutPreference = "split";
  } catch {}
  const full = new Map(),
    revealed = new Map();
  // Review comments are read-only GitHub data; open state and filters stay in this browser.
  let comments = null,
    commentsLoading = false,
    commentsError = "",
    focusedThread = null;
  const openThreads = new Map(),
    commentFilter = { mode: "all", bots: true };
  try {
    const mode = localStorage.getItem("pr-code-comment-filter");
    if (COMMENT_MODES.includes(mode)) commentFilter.mode = mode;
    commentFilter.bots = localStorage.getItem("pr-code-comment-bots") !== "hidden";
  } catch {}
  let alignmentFrame;
  function alignSplitRows() {
    cancelAnimationFrame(alignmentFrame);
    alignmentFrame = requestAnimationFrame(() => {
      for (const grid of document.querySelectorAll(".split-diff")) {
        const left = [
          ...grid.querySelector(".split-pane").querySelectorAll("[data-pair]"),
        ];
        const right = [
          ...grid
            .querySelectorAll(".split-pane")[1]
            .querySelectorAll("[data-pair]"),
        ];
        [...left, ...right].forEach((row) => (row.style.minHeight = ""));
        const heights = left.map((row, i) =>
          Math.max(
            row.getBoundingClientRect().height,
            right[i].getBoundingClientRect().height,
          ),
        );
        left.forEach((row, i) => {
          row.style.minHeight = right[i].style.minHeight = heights[i] + "px";
        });
      }
    });
  }
  function updateLayout() {
    if (!data || $("code-view").hidden) return;
    const column = document.querySelector(".diff-column"),
      style = getComputedStyle(column);
    const width =
      column.clientWidth -
      parseFloat(style.paddingLeft) -
      parseFloat(style.paddingRight);
    const next = layoutPreference;
    $("diff-layout").value = next;
    $("layout-hint").textContent = next === "split" && width < 760
      ? "Scroll horizontally to see both sides, or hide Files for more room"
      : "";
    $("files-toggle").setAttribute(
      "aria-expanded",
      getComputedStyle(document.querySelector(".file-sidebar")).display !==
        "none",
    );
    if (next !== diffLayout) {
      const top = document
        .querySelector(".diff-toolbar")
        .getBoundingClientRect().bottom;
      const anchor = [...document.querySelectorAll(".code-row")].find(
        (row) =>
          row.getBoundingClientRect().bottom > top &&
          row.getBoundingClientRect().height > 0,
      );
      const position = anchor
        ? {
            file: anchor.dataset.file,
            row: anchor.dataset.row,
            side: anchor.dataset.side,
            top: anchor.getBoundingClientRect().top,
          }
        : null;
      diffLayout = next;
      renderFiles();
      if (position) {
        const targets = [
          ...document.querySelectorAll(
            `[data-file="${position.file}"][data-row="${position.row}"]`,
          ),
        ];
        const replacement =
          targets.find(
            (row) => !row.dataset.side || row.dataset.side === position.side,
          ) || targets[0];
        if (replacement)
          column.scrollTop +=
            replacement.getBoundingClientRect().top - position.top;
      }
    }
    alignSplitRows();
  }

  const basename = (path) => path.split("/").pop();
  function notify(text) {
    $("workspace-toast").textContent = text;
    $("workspace-toast").hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => ($("workspace-toast").hidden = true), 3500);
  }
  function persist() {
    saver.enqueue(uiState(saved));
  }
  function filteredFiles() {
    const term = $("file-filter").value.toLowerCase();
    return data.files
      .map((file, index) => ({ file, index }))
      .filter(
        ({ file }) =>
          file.path.toLowerCase().includes(term) &&
          (!$("unviewed-only").checked || !saved.viewed.includes(file.path)),
      );
  }
  function renderProgress() {
    const count = data.files.filter((f) =>
      saved.viewed.includes(f.path),
    ).length;
    $("viewed-progress").textContent =
      `${count} / ${data.files.length} files viewed`;
    $("sidebar-progress").textContent =
      `${count} of ${data.files.length} files viewed`;
    $("collapse-all").textContent = data.files.every((f) =>
      saved.collapsed.includes(f.path),
    )
      ? "Expand all"
      : "Collapse all";
    $("file-progress").value = count;
    $("file-progress").max = data.files.length;
    $("note-count").textContent = saved.notes.length;
    $("comment-count").textContent = comments
      ? (comments.threads || []).filter((t) => !t.resolved).length
      : "";
  }
  function threadBadge(file) {
    const count = shownThreads().filter((t) => t.path === file.path).length;
    return count
      ? `<span class="file-thread-count" title="${count} review ${count === 1 ? "thread" : "threads"}" aria-label="${count} review ${count === 1 ? "thread" : "threads"}">${count}</span>`
      : "";
  }
  function renderTree() {
    $("file-tree").innerHTML =
      filteredFiles()
        .map(
          ({ file, index }) =>
            `<button class="file-link" data-jump="${index}" aria-current="${index === activeFile}"><span class="${saved.viewed.includes(file.path) ? "viewed-icon" : ""}">${saved.viewed.includes(file.path) ? "✓" : "◇"}</span><span><span class="file-name">${esc(basename(file.path))}</span><span class="file-dir">${esc(file.path.split("/").slice(0, -1).join("/"))}</span></span>${threadBadge(file)}<span class="file-type">${{ added: "A", removed: "D", renamed: "R" }[file.status] || "M"}</span></button>`,
        )
        .join("") || '<p class="muted">No matching files.</p>';
  }
  function visibleRows(index) {
    return projectRows(data.files[index], full.get(index));
  }
  const shownThreads = () =>
    (comments?.threads || []).filter((t) =>
      isShown(t, commentFilter, focusedThread),
    );
  const threadOpen = (thread) =>
    thread.id === focusedThread || (openThreads.get(thread.id) ?? !thread.resolved);
  function placement(index) {
    return placeThreads(data.files[index], shownThreads(), {
      placed: placeable(comments, data),
      mode: full.get(index),
    });
  }
  function fileRows(index) {
    const { byRow, other } = placement(index);
    const extra = new Set([...(revealed.get(index) || []), ...byRow.keys()]);
    const annotate = (row, side) =>
      (byRow.get(row.id) || [])
        .filter((t) => !side || t.side === side)
        .map((t) => threadHTML(t, threadOpen(t)))
        .join("");
    const outside = other.length && data.files[index].rows
      ? `<details class="file-comments" ${other.some((t) => t.id === focusedThread) ? "open" : ""}><summary>${other.length} ${other.length === 1 ? "comment" : "comments"} not on current lines${placeable(comments, data) ? " · file-level or outdated" : " · from a newer commit"}</summary>${other.map((t) => threadHTML(t, threadOpen(t))).join("")}</details>`
      : "";
    return outside + renderFileRows(data.files[index], index, {
      mode: full.get(index),
      layout: diffLayout,
      extra,
      base: data.base,
      head: data.head,
      loading: loadingFiles.has(index),
      annotate: byRow.size ? annotate : null,
    });
  }
  function renderFiles() {
    $("files").innerHTML =
      filteredFiles()
        .map(({ file, index }) => {
          const collapsed = saved.collapsed.includes(file.path),
            mode = full.get(index);
          return `<article class="file-card ${collapsed ? "collapsed" : ""}" id="file-${index}" data-file-index="${index}"><header class="file-header"><button class="file-collapse" data-collapse="${index}" aria-expanded="${!collapsed}"><span aria-hidden="true">${collapsed ? "›" : "⌄"}</span><code>${esc(file.path)}</code></button><span class="file-stats"><span class="added">+${file.additions}</span><span class="deleted">−${file.deletions}</span></span><div class="file-actions">${file.status !== "modified" ? `<span class="file-status">${esc(file.status)}</span>` : ""}${file.previous ? `<span title="${esc(file.previous)}">Renamed</span>` : ""}${mode ? `<select data-revision="${index}" aria-label="Full file revision"><option value="head" ${mode === "head" ? "selected" : ""}>Head ${esc(data.head.slice(0, 12))}</option><option value="base" ${mode === "base" ? "selected" : ""}>Base ${esc(data.base.slice(0, 12))}</option></select>` : ""}<button data-full="${index}" aria-pressed="${!!mode}">${mode ? "Back to diff" : "Full file"}</button><label><input data-viewed="${index}" type="checkbox" ${saved.viewed.includes(file.path) ? "checked" : ""} ${params.has("revision") ? "disabled" : ""}>Viewed</label></div></header><div class="code-lines" ${collapsed ? "hidden" : ""}>${collapsed ? "" : fileRows(index)}${file.baseNoNewline || file.headNoNewline ? '<p class="muted">No final newline: ' + (file.baseNoNewline ? "base " : "") + (file.headNoNewline ? "head" : "") + "</p>" : ""}</div></article>`;
        })
        .join("") ||
      '<div class="empty-code"><h3>No files to show</h3><p>Clear the file filter or turn off Only unviewed.</p><button class="button" id="reset-filters">Show all files</button></div>';
    paintSelection();
    renderTree();
    renderProgress();
    alignSplitRows();
    fileObserver.disconnect();
    for (const card of document.querySelectorAll(
      ".file-card:not(.collapsed)",
    )) {
      if (!data.files[Number(card.dataset.fileIndex)].rows)
        fileObserver.observe(card);
    }
  }
  function renderAfterFileToggle(index) {
    const card = $(`file-${index}`);
    const pinned = card && card.getBoundingClientRect().top < document.querySelector(".diff-toolbar").getBoundingClientRect().bottom;
    const nextId = card?.nextElementSibling?.id;
    renderFiles();
    // Collapsing a file from its sticky header must not skip the next file.
    if (pinned) ($(`file-${index}`) || $(nextId))?.scrollIntoView({block: "start", behavior: "instant"});
  }
  function paintSelection() {
    for (const row of document.querySelectorAll(".code-row"))
      row.classList.toggle(
        "selected",
        !!selection &&
          Number(row.dataset.file) === selection.file &&
          selection.ids.includes(Number(row.dataset.row)) &&
          (!row.dataset.side || row.dataset.side === selection.side),
      );
    $("selection-bar").hidden = !selection || tab !== "code";
    $("ask-selection").textContent =
      currentThread() || activeContexts().length
        ? "Add selection to chat"
        : "Ask about selection";
    if (selection)
      $("selection-label").textContent =
        `${basename(data.files[selection.file].path)} · ${selection.label}`;
  }
  function makeSelection(file, start, end, side = "head", sideOnly = false) {
    return selectionFor(data, file, start, end, side, sideOnly, full.get(file));
  }
  function selectRows(file, start, end, side) {
    selection = makeSelection(
      file,
      start,
      end,
      side,
      diffLayout === "split" && !full.has(file),
    );
    paintSelection();
  }
  function setTab(value) {
    tab = value;
    $("code-view").hidden = tab !== "code";
    $("ai-view").hidden = tab !== "review";
    $("code-tab").setAttribute("aria-pressed", tab === "code");
    $("review-tab").setAttribute("aria-pressed", tab === "review");
    if (tab === "review") markReportRead();
    const url = new URL(location.href);
    url.searchParams.set("tab", tab);
    history.replaceState(null, "", url);
    paintSelection();
    updateLayout();
  }
  // The current file follows scrolling: the last card whose header has reached the toolbar.
  let scrollFrame = 0,
    followScrollAfter = 0;
  function followScroll() {
    scrollFrame = 0;
    if (performance.now() < followScrollAfter) return;
    const column = document.querySelector(".diff-column");
    const edge = document.querySelector(".diff-toolbar").getBoundingClientRect().bottom + 1;
    const cards = [...column.querySelectorAll(".file-card")];
    let current = cards[0];
    // Short files at the end never reach the toolbar, so the bottom selects the last file.
    if (column.scrollTop + column.clientHeight >= column.scrollHeight - 2) current = cards.at(-1);
    else
      for (const card of cards) {
        if (card.getBoundingClientRect().top > edge) break;
        current = card;
      }
    const index = Number(current?.dataset.fileIndex);
    if (!current || index === activeFile) return;
    activeFile = index;
    for (const link of $("file-tree").querySelectorAll(".file-link"))
      link.setAttribute("aria-current", String(Number(link.dataset.jump) === index));
    // Scroll only the sidebar; scrollIntoView could also move the clipped page containers.
    const link = $("file-tree").querySelector('[aria-current="true"]');
    const sidebar = document.querySelector(".file-sidebar");
    if (!link || !sidebar.offsetParent) return;
    const l = link.getBoundingClientRect(),
      s = sidebar.getBoundingClientRect();
    if (l.top < s.top) sidebar.scrollTop -= s.top - l.top;
    else if (l.bottom > s.bottom) sidebar.scrollTop += l.bottom - s.bottom;
  }
  document.querySelector(".diff-column").addEventListener(
    "scroll",
    () => (scrollFrame ||= requestAnimationFrame(followScroll)),
    { passive: true },
  );
  async function jump(file, ids = null, side = "head") {
    if (!(await ensureFile(file))) return;
    activeFile = file;
    // Keep the chosen file current even when it cannot scroll up to the toolbar.
    followScrollAfter = performance.now() + 200;
    $("file-filter").value = "";
    $("unviewed-only").checked = false;
    saved.collapsed = saved.collapsed.filter(
      (p) => p !== data.files[file].path,
    );
    persist();
    setTab("code");
    if (ids) {
      full.delete(file);
      const extra = revealed.get(file) || new Set();
      for (const id of ids) extra.add(id);
      revealed.set(file, extra);
      selection = makeSelection(file, ids[0], ids.at(-1), side);
    }
    $("code-view").classList.remove("files-open");
    $("files-toggle").setAttribute("aria-expanded", "false");
    renderFiles();
    updateLayout();
    const target = ids
      ? document.querySelector(`[data-file="${file}"][data-row="${ids[0]}"]`)
      : $(`file-${file}`);
    target?.scrollIntoView({ block: "start", behavior: "instant" });
    if (ids && target) document.querySelector(".diff-column").scrollTop -= $(`file-${file}`).querySelector(".file-header").offsetHeight + 8;
  }
  function showRail(kind = "chat") {
    $("conversation").hidden = false;
    $("workspace-body").classList.add("rail-open");
    $("chat-toggle").setAttribute("aria-expanded", "true");
    $("chat-content").hidden = kind !== "chat";
    $("notes-content").hidden = kind !== "notes";
    $("comments-content").hidden = kind !== "comments";
    $("rail-title").textContent =
      { chat: "Ask about this code", notes: "Private notes", comments: "GitHub comments" }[kind];
    if (kind === "chat") renderChat();
    else if (kind === "comments") renderComments();
    else renderNotes();
    updateLayout();
  }
  function closeRail() {
    $("conversation").hidden = true;
    $("workspace-body").classList.remove("rail-open");
    $("chat-toggle").setAttribute("aria-expanded", "false");
    $("chat-toggle").focus();
    updateLayout();
  }
  async function refreshChatConfig() {
    if (!data || threadId) return;
    try { data.chat_config = await api.get("/api/workspace-ai"); renderChat(); }
    catch { /* Starting a conversation still validates its saved provider on the server. */ }
  }
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshChatConfig();
  });
  function selectThread(id) {
    threadId = id;
    if (!id) refreshChatConfig();
    const url = new URL(location.href);
    if (id) url.searchParams.set("chat", id);
    else url.searchParams.delete("chat");
    history.replaceState(null, "", url);
  }
  function currentThread() {
    return saved.threads.find((t) => t.id === threadId);
  }
  let draftContexts = [];
  const activeContexts = () =>
    currentThread() ? contextsOf(currentThread()) : draftContexts;
  function beginThread(context = null) {
    selectThread(null);
    draftContexts = context ? [structuredClone(context)] : [];
    $("question").value = "";
    showRail();
    $("question").focus({ preventScroll: true });
  }
  function attachContext(context) {
    if (!context) return;
    const thread = currentThread();
    if (isOlder(thread, data)) {
      notify("Start a new conversation to discuss the current revision.");
      return;
    }
    const contexts = attach(activeContexts(), context);
    if (thread) {
      preserveMessageContexts(thread);
      thread.contexts = contexts;
      persist();
    } else draftContexts = contexts;
    showRail();
    $("question").focus({ preventScroll: true });
  }
  function renderChat() {
    const scroll = $("message-scroll");
    const nearBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 60;
    const thread = currentThread(),
      contexts = activeContexts();
    const ai = thread?.ai_config || data.chat_config;
    if ($("chat-provider")) $("chat-provider").textContent = ai
      ? `${ai.provider === 'claude' ? 'Claude Code' : 'Codex'} · ${ai.model || 'default model'} · ${ai.effort || 'default reasoning'}${thread ? ' · Pinned to this conversation' : ''}` : '';
    $("thread-picker").innerHTML =
      '<option value="">New conversation</option>' +
      saved.threads
        .map(
          (t) =>
            `<option value="${esc(t.id)}" ${t.id === threadId ? "selected" : ""}>${esc((contextsOf(t)[0] ? basename(contextsOf(t)[0].path) : "PR") + " · " + (t.messages[0]?.text || "Conversation").slice(0, 42) + (isOlder(t, data) ? " · Older commit " + t.head.slice(0, 7) : ""))}</option>`,
        )
        .join("");
    $("chat-context").innerHTML = contexts.length
      ? `<p class="context-count">${attachmentCount(contexts)} + PR diff</p>` +
        contexts.map(contextHTML).join("")
      : `<strong>Entire pull request</strong><p>Comparison ${esc((thread?.base || data.base).slice(0, 12))} → ${esc((thread?.head || data.head).slice(0, 12))}</p>`;
    let messagesHTML = thread
      ? thread.messages
          .map(
            (m, index) =>
              `<article class="message ${m.role === "user" ? "user" : "assistant"}"><header>${m.role === "user" ? "You" : "AI"}</header>${messageContextHTML(m, index, thread)}${m.role === "user" ? `<p>${esc(m.text)}</p>` : `<div class="chat-markdown">${chatMarkdown(m.text)}</div>`}${sourceLinksHTML(m.sources)}${m.reads?.length ? `<details class="message-contexts"><summary>Additional context · ${m.reads.length} requests</summary>${m.reads.map((r) => `<p>${esc(contextReadLabel(r))}</p>`).join("")}</details>` : ""}${m.role === "assistant" ? `<button class="text-button" data-save-message="${index}">Save to private notes</button>` : ""}</article>`,
          )
          .join("")
      : `<div class="chat-empty"><strong>${contexts.length ? "Start with a question." : "A second pair of eyes."}</strong><p>${contexts.length ? "Ask about these lines. Add more selections from any file to keep exploring in this conversation." : "Select lines in the diff for a focused conversation, or ask about the whole change."}</p></div>`;
    if (thread?.draft && isRunning(thread))
      messagesHTML += `<article class="message assistant streaming"><header>AI · Responding</header><div class="chat-markdown">${chatMarkdown(thread.draft)}</div></article>`;
    if ($("messages").innerHTML !== messagesHTML)
      $("messages").innerHTML = messagesHTML;
    $("question").placeholder = thread
      ? "Ask a follow-up…"
      : contexts.length
        ? "Ask about the selected code…"
        : "Ask about this pull request…";
    $("ask-selection").textContent =
      thread || contexts.length
        ? "Add selection to chat"
        : "Ask about selection";
    $("prompt-addressed").hidden = !contexts.some((c) => c.kind === "comment");
    $("send-question").disabled = chatStarting || isRunning(thread);
    $("stop-chat").hidden = !isRunning(thread);
    $("stop-chat").disabled = thread?.status === "stopping";
    $("chat-status").classList.toggle("working", isRunning(thread));
    $("chat-status").textContent = chatProgress(thread) ||
        (isOlder(thread, data)
          ? "Older commit · follow-ups use the original revision. Start New to discuss current code."
          : "");
    $("chat-activity").hidden = !thread?.activity?.length;
    const activity = activityHTML(thread);
    if ($("chat-activity-items").innerHTML !== activity)
      $("chat-activity-items").innerHTML = activity;
    if (nearBottom) scroll.scrollTop = scroll.scrollHeight;
  }
  async function ask(question) {
    question = question.trim();
    if (!question || chatStarting || isRunning(currentThread())) return;
    chatStarting = true;
    renderChat();
    try {
      await saver.flush();
      const thread = currentThread(),
        next = await api.ask(
          thread?.revision || data.revision,
          threadId,
          question,
          activeContexts(),
        );
      upsertThread(saved, next);
      selectThread(next.id);
      draftContexts = [];
      $("question").value = "";
      persist();
      pollChat(next.id);
    } catch (error) {
      notify(error.message);
    } finally {
      chatStarting = false;
      renderChat();
    }
  }
  async function jumpContext(context) {
    if (context.kind === "comment" && context.head === data.head && context.base === data.base) {
      await focusThread(context.comment);
      return;
    }
    if (context.head !== data.head || context.base !== data.base) {
      const query = new URLSearchParams({
        url: data.url,
        revision: context.base + "-" + context.head,
        tab: "code",
        path: context.path,
        side: context.side,
      });
      if (context.ids.length) query.set("line", context.ids[0]);
      location.href = "/workspace?" + query;
      return;
    }
    const index = data.files.findIndex((f) => f.path === context.path);
    if (index >= 0) {
      await jump(index, context.ids, context.side);
      if (innerWidth <= 750) closeRail();
    }
  }
  async function loadComments(refresh = false) {
    if (commentsLoading) return;
    commentsLoading = true;
    commentsError = "";
    renderComments();
    try {
      comments = await api.comments(refresh);
    } catch (error) {
      commentsError = error.message;
    } finally {
      commentsLoading = false;
      renderFiles();
      renderComments();
    }
  }
  function renderComments() {
    if (!data) return;
    const status = commentsLoading
      ? "Loading comments from GitHub…"
      : commentsError ||
        (comments
          ? `Read from GitHub ${new Date(comments.fetched_at * 1000).toLocaleTimeString(undefined, { timeStyle: "short" })}${comments.incomplete ? " · very long discussions are cut off; see GitHub for the rest" : ""}`
          : "");
    $("comments-status").textContent = status;
    $("comments-status").classList.toggle("warning", !!commentsError);
    $("refresh-comments").disabled = commentsLoading;
    $("comments-placement").hidden = !comments || placeable(comments, data);
    if (comments && !placeable(comments, data))
      $("comments-placement").textContent = `Comments refer to commit ${comments.head.slice(0, 12)}, not the ${data.head.slice(0, 12)} shown here. They're listed under each file instead of on lines. Check for new commits to place them.`;
    if ($("conversation").hidden || $("comments-content").hidden) return;
    const listed = (comments?.threads || []).filter((t) =>
      isShown(t, { ...commentFilter, mode: commentFilter.mode === "hidden" ? "all" : commentFilter.mode }),
    );
    $("comment-threads").innerHTML = comments
      ? listed.length
        ? listed
            .map((t) => {
              const first = t.comments[0] || { author: "ghost", body: "" };
              const line = t.line || t.original_line;
              return `<button class="thread-link${t.resolved ? " resolved" : ""}" data-thread-jump="${esc(t.id)}"><span><strong>@${esc(first.author)}</strong> · ${esc(basename(t.path))}${line && !t.file_level ? ":" + line : ""}${t.resolved ? " · Resolved" : ""}${t.outdated ? " · Outdated" : ""}</span><span class="muted">${esc(excerptOf(first.body, 140))}</span></button>`;
            })
            .join("")
        : `<p class="muted">${comments.threads.length ? "No threads match the comment filter." : "No review threads on code yet."}</p>`
      : "";
    $("comment-conversation").innerHTML = comments
      ? comments.conversation.length
        ? comments.conversation
            .filter((c) => commentFilter.bots || !c.bot)
            .map(conversationHTML)
            .join("") || '<p class="muted">Only bot comments. Turn on Bots to see them.</p>'
        : '<p class="muted">No general PR comments or review summaries.</p>'
      : "";
  }
  function contextForComment(id) {
    const item = findComment(comments, id);
    if (!item) return null;
    const index = item.comments ? data.files.findIndex((f) => f.path === item.path) : -1;
    const context = commentContext(item, data, data.files[index], index);
    if (!placeable(comments, data)) context.ids = [];
    return context;
  }
  async function focusThread(id) {
    const thread = comments?.threads.find((t) => t.id === id);
    if (!thread) {
      showRail("comments");
      document
        .querySelector(`[data-conversation="${CSS.escape(id)}"]`)
        ?.scrollIntoView({ block: "center" });
      return;
    }
    const index = data.files.findIndex((f) => f.path === thread.path);
    if (index < 0) {
      notify("This comment is on a file outside the current comparison. Open it on GitHub.");
      return;
    }
    focusedThread = id;
    openThreads.set(id, true);
    await jump(index);
    if (innerWidth <= 750) closeRail();
    const target = document.querySelector(`.review-thread[data-thread="${CSS.escape(id)}"]`);
    target?.scrollIntoView({ block: "center", behavior: "instant" });
    target?.querySelector("summary")?.focus({ preventScroll: true });
  }
  function sourceRevision(head) {
    if (!head) return "Revision not recorded";
    return head === data.head ? "Current commit" : `Older commit ${head.slice(0, 12)}`;
  }
  function noteRevision(note) {
    if (typeof note.head === "string" && note.head) return note.head;
    return contextsOf(note).find((context) => typeof context.head === "string" && context.head)?.head || "";
  }
  function noteId() {
    return crypto.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2);
  }
  function renderGuidanceSources() {
    const container = $("guidance-sources");
    if (!container || !data) return;
    const notes = saved.notes.map((note) => {
      const head = noteRevision(note);
      const preview = String(note.text || "").replace(/\s+/g, " ").trim();
      return `<label class="review-context-option"><input type="checkbox" data-guidance-note="${esc(note.id || "")}"><span><strong>Private note</strong><small>${esc(sourceRevision(head))}${contextsOf(note).length ? ` · ${contextsOf(note).length} code ${contextsOf(note).length === 1 ? "selection" : "selections"}` : ""}</small><span>${esc(preview.slice(0, 220) + (preview.length > 220 ? "…" : ""))}</span></span></label>`;
    });
    const conversations = saved.threads.map((thread) => {
      const messages = thread.messages.filter((message) => ["user", "assistant"].includes(message.role));
      const first = messages.find((message) => message.role === "user");
      const preview = String(first?.text || "Conversation").replace(/\s+/g, " ").trim();
      const answers = messages.filter((message) => message.role === "assistant").length;
      return `<label class="review-context-option"><input type="checkbox" data-guidance-conversation="${esc(thread.id)}"><span><strong>Ask AI conversation</strong><small>${esc(sourceRevision(thread.head))} · ${messages.length} messages · ${answers} ${answers === 1 ? "answer" : "answers"}</small><span>${esc(preview.slice(0, 220) + (preview.length > 220 ? "…" : ""))}</span></span></label>`;
    });
    container.innerHTML = notes.concat(conversations).join("") || '<p class="muted">No private notes or Ask AI conversations are saved for this PR.</p>';
    $("guidance-context-count").textContent = "No private context selected.";
  }
  function selectedGuidanceContext() {
    const notes = [...document.querySelectorAll("#guidance-sources [data-guidance-note]:checked")].map((input) => input.dataset.guidanceNote);
    const conversations = [...document.querySelectorAll("#guidance-sources [data-guidance-conversation]:checked")].map((input) => input.dataset.guidanceConversation);
    return notes.length || conversations.length ? { notes, conversations } : null;
  }
  function updateGuidanceSelectionCount() {
    const count = document.querySelectorAll("#guidance-sources input:checked").length;
    $("guidance-context-count").textContent = count ? `${count} private source${count === 1 ? "" : "s"} selected.` : "No private context selected.";
  }
  function renderNotes() {
    $("saved-notes").innerHTML = saved.notes.length
      ? saved.notes
          .map((note, index) => {
            const contexts = contextsOf(note);
            return `<article class="saved-note"><small>${contexts.length ? esc(contexts.length + " code " + (contexts.length === 1 ? "selection" : "selections")) : "Pull request note"} · ${esc(sourceRevision(noteRevision(note)))}</small><p>${esc(note.text)}</p><div class="note-actions">${contexts.map((context, n) => `<button class="text-button" data-note-jump="${index}" data-context-index="${n}">${esc(basename(context.path))} · ${esc(context.label)}</button>`).join("")}<button class="text-button" data-note-edit="${index}">Edit</button><button class="text-button" data-note-delete="${index}">Delete</button></div></article>`;
          })
          .join("")
      : '<p class="muted">No notes yet. Save an answer or write your own.</p>';
    renderProgress();
  }
  let editingNote = null;
  function syncReportTheme() {
    const frame = document.querySelector(".review-frame");
    if (!frame) return;
    const style = getComputedStyle(document.body);
    const colors = {};
    for (const [key, source] of Object.entries({bg:"surface",panel:"surface",fg:"fg",muted:"muted",line:"line",accent:"selection",soft:"soft"})) {
      colors[key] = style.getPropertyValue("--" + source).trim();
    }
    frame.contentWindow?.postMessage({type:"workspace-report-theme",theme:document.documentElement.dataset.theme,colors}, "*");
  }
  new MutationObserver(syncReportTheme).observe(document.documentElement, {attributes:true,attributeFilter:["data-theme"]});
  function renderReview() {
    $("review-count").textContent = data.review?.artifact ? "Ready" : "Not run";
    const next = JSON.stringify(data.review);
    if (next !== reviewSignature) {
      $("ai-view").classList.remove("ai-view-wide");
      $("ai-view").innerHTML = reviewHTML(data.review, data, esc);
      reviewSignature = next;
    }
  }
  let reviewSignature = "",
    readVersion = "";
  async function markReportRead() {
    const artifact = data.review?.artifact;
    if (!artifact || artifact.version === readVersion) return;
    try {
      await api.request("/artifact-opened", {
        run_id: artifact.run_id,
        name: artifact.name,
        version: artifact.version,
      });
      readVersion = artifact.version;
    } catch {
      /* Reading remains usable when acknowledgment fails. */
    }
  }

  document.addEventListener("click", async (event) => {
    if (!data) return;
    const button = event.target.closest("button");
    if (!button) return;
    const d = button.dataset;
    if (d.jump !== undefined) jump(Number(d.jump));
    if (d.collapse !== undefined) {
      const path = data.files[Number(d.collapse)].path;
      saved.collapsed = saved.collapsed.includes(path)
        ? saved.collapsed.filter((p) => p !== path)
        : [...saved.collapsed, path];
      persist();
      renderAfterFileToggle(Number(d.collapse));
      document
        .querySelector(`[data-collapse="${d.collapse}"]`)
        ?.focus({ preventScroll: true });
    }
    if (d.expand !== undefined) {
      const index = Number(d.expand),
        extra = revealed.get(index) || new Set(),
        start = Number(d.start),
        end = Number(d.end);
      for (let i = start; i <= Math.min(start + 11, end); i++) extra.add(i);
      revealed.set(index, extra);
      renderFiles();
      document
        .querySelector(
          `[data-file="${index}"][data-row="${start}"] .line-number:not(:disabled)`,
        )
        ?.focus({ preventScroll: true });
    }
    if (d.loadFile !== undefined) {
      await ensureFile(Number(d.loadFile));
      return;
    }
    if (d.full !== undefined) {
      const index = Number(d.full);
      if (!(await ensureFile(index))) return;
      full.has(index) ? full.delete(index) : full.set(index, "head");
      saved.collapsed = saved.collapsed.filter(
        (p) => p !== data.files[index].path,
      );
      persist();
      renderFiles();
      document
        .querySelector(`[data-full="${index}"]`)
        ?.focus({ preventScroll: true });
    }
    if (d.prompt) ask(d.prompt);
    if (d.saveMessage !== undefined) {
      const t = currentThread(),
        message = t.messages[Number(d.saveMessage)];
      const contexts = structuredClone(
        Array.isArray(message.contexts) ? message.contexts : contextsOf(t),
      );
      saved.notes.push({
        id: noteId(),
        created_at: new Date().toISOString(),
        base: data.base,
        head: data.head,
        text: message.text,
        contexts,
        context: contexts.at(-1) || null,
      });
      persist();
      renderProgress();
      notify("Saved to private notes.");
    }
    if (d.removeContext !== undefined) {
      const thread = currentThread();
      let removed;
      if (thread) {
        removed = removeContext(thread, Number(d.removeContext));
        persist();
      } else removed = draftContexts.splice(Number(d.removeContext), 1)[0];
      if (selection && removed && contextKey(selection) === contextKey(removed))
        selection = null;
      paintSelection();
      renderChat();
      $("question").focus({ preventScroll: true });
      notify("Code detached. Your draft and conversation are kept.");
    }
    if (d.contextJump !== undefined) {
      const context = activeContexts()[Number(d.contextJump)];
      if (context) {
        jumpContext(context);
      }
    }
    if (d.messageContext !== undefined) {
      const thread = currentThread(),
        message = thread.messages[Number(d.messageContext)],
        context = (message.contexts || contextsOf(thread))[
          Number(d.contextIndex)
        ];
      if (context) {
        jumpContext(context);
      }
    }
    if (d.noteJump !== undefined) {
      const c = contextsOf(saved.notes[Number(d.noteJump)])[
        Number(d.contextIndex)
      ];
      jumpContext(c);
    }
    if (d.noteDelete !== undefined) {
      saved.notes.splice(Number(d.noteDelete), 1);
      editingNote = null;
      $("note-text").value = "";
      persist();
      renderNotes();
    }
    if (d.noteEdit !== undefined) {
      editingNote = Number(d.noteEdit);
      $("note-text").value = saved.notes[editingNote].text;
      $("note-text").focus();
    }
    if (d.showCode !== undefined) setTab("code");
    if (d.threadJump !== undefined) focusThread(d.threadJump);
    if (d.commentAsk !== undefined) {
      const context = contextForComment(d.commentAsk);
      if (context) attachContext(context);
    }
    if (d.commentDraft !== undefined) {
      const context = contextForComment(d.commentDraft);
      if (context && !chatStarting) {
        // Drafts get a fresh conversation so they never inherit unrelated selections.
        beginThread(context);
        ask(DRAFT_PROMPT);
      }
    }
    if (button.id === "refresh-comments") loadComments(true);
    if (d.continue !== undefined) {
      const continuation = data.review?.continuation;
      try {
        await navigator.clipboard.writeText(continuation[d.continue]);
        notify(d.continue === "command"
          ? `Command copied. Paste it into a terminal to continue in ${continuation.agent}.`
          : "Handoff prompt copied. Paste it into a new Claude Code or Codex session.");
      } catch { notify("Could not copy. Reload the AI review tab and try again."); }
    }
    if (button.id === "generate-review" || button.id === "generate-review-update") {
      button.disabled = true;
      if (!(await startReview(button.id === "generate-review-update" ? { mode: "update" } : {})))
        button.disabled = false;
    }
    if (button.id === "generate-review-guided") {
      $("guidance-text").value = "";
      $("guidance-deep").checked = false;
      renderGuidanceSources();
      $("guidance-dialog").showModal();
      $("guidance-text").focus();
    }
    if (button.id === "guidance-cancel") $("guidance-dialog").close();
    if (button.id === "refresh-comparison") {
      button.disabled = true;
      try {
        await saver?.flush();
        location.href =
          "/workspace?" + new URLSearchParams({ url: data.url, tab });
      } catch (error) {
        notify(error.message);
        button.disabled = false;
      }
    }
    if (button.id === "stop-chat") {
      try {
        await api.stop(threadId);
        pollChat(threadId);
      } catch (error) {
        notify(error.message);
      }
    }
    if (button.id === "reset-filters") {
      $("file-filter").value = "";
      $("unviewed-only").checked = false;
      renderFiles();
    }
  });
  document.addEventListener("change", (event) => {
    const d = event.target.dataset;
    if (!data) return;
    if (d.viewed !== undefined) {
      const file = data.files[Number(d.viewed)];
      saved.viewed = saved.viewed.filter((p) => p !== file.path);
      saved.collapsed = saved.collapsed.filter((p) => p !== file.path);
      if (event.target.checked) {
        saved.viewed.push(file.path);
        saved.collapsed.push(file.path);
      }
      persist();
      renderAfterFileToggle(Number(d.viewed));
      document
        .querySelector(`[data-viewed="${d.viewed}"]`)
        ?.focus({ preventScroll: true });
    }
    if (d.revision !== undefined) {
      full.set(Number(d.revision), event.target.value);
      renderFiles();
      document
        .querySelector(`[data-revision="${d.revision}"]`)
        ?.focus({ preventScroll: true });
    }
  });
  let drag = null;
  document.addEventListener("pointerdown", (event) => {
    const gutter = event.target.closest("[data-line]");
    if (!gutter || gutter.disabled || event.button !== 0) return;
    const row = gutter.closest(".code-row"),
      file = Number(row.dataset.file),
      id = Number(row.dataset.row),
      side = gutter.dataset.line;
    const start =
      event.shiftKey && selection?.file === file && selection.side === side
        ? selection.ids[0]
        : id;
    drag = { file, start, side };
    selectRows(file, start, id, side);
    event.preventDefault();
    gutter.focus({ preventScroll: true });
  });
  document.addEventListener("pointerover", (event) => {
    if (!drag) return;
    const row = event.target.closest(".code-row");
    if (
      row &&
      Number(row.dataset.file) === drag.file &&
      (!row.dataset.side || row.dataset.side === drag.side)
    )
      selectRows(drag.file, drag.start, Number(row.dataset.row), drag.side);
  });
  document.addEventListener("pointerup", () => {
    drag = null;
  });
  document.addEventListener("pointercancel", () => {
    drag = null;
  });
  document.addEventListener("click", async (event) => {
    const gutter = event.target.closest("[data-line]");
    if (!gutter || event.detail !== 0 || gutter.disabled) return;
    const row = gutter.closest(".code-row"),
      file = Number(row.dataset.file),
      id = Number(row.dataset.row);
    selectRows(
      file,
      event.shiftKey &&
        selection?.file === file &&
        selection.side === gutter.dataset.line
        ? selection.ids[0]
        : id,
      id,
      gutter.dataset.line,
    );
  });
  document.addEventListener("mouseup", () => {
    const text = window.getSelection();
    if (!text || text.isCollapsed || !text.toString().trim()) return;
    const parent = (node) =>
      node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
    const a = parent(text.anchorNode)?.closest(".code-row"),
      b = parent(text.focusNode)?.closest(".code-row");
    if (
      a &&
      b &&
      a.dataset.file === b.dataset.file &&
      a.dataset.side === b.dataset.side
    )
      selectRows(
        Number(a.dataset.file),
        Number(a.dataset.row),
        Number(b.dataset.row),
        a.dataset.side ||
          (full.get(Number(a.dataset.file)) === "base" ? "base" : "head"),
      );
  });
  async function startReview(body) {
    try {
      await saver.flush();
      await api.request("/regenerate-review", body);
      notify(
        body.mode === "update"
          ? "AI review update started. Follow its activity in the dashboard."
          : "AI review started. Follow its activity in the dashboard.",
      );
      clearTimeout(reviewTimer);
      await updateReview();
      return true;
    } catch (error) {
      notify(error.message);
      return false;
    }
  }
  $("guidance-text").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      $("guidance-form").requestSubmit();
    }
  });
  $("guidance-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = $("guidance-form").querySelector("[type=submit]");
    submit.disabled = true;
    const context = selectedGuidanceContext();
    const body = { guidance: $("guidance-text").value, deep_explanation: $("guidance-deep").checked };
    if (context) body.workspace_context = context;
    if (await startReview(body)) $("guidance-dialog").close();
    submit.disabled = false;
  });
  $("guidance-sources").addEventListener("change", updateGuidanceSelectionCount);
  $("files-toggle").addEventListener("click", () => {
    const overlay =
      innerWidth <= 750 || (innerWidth <= 1150 && !$("conversation").hidden);
    if (overlay) {
      $("code-view").classList.remove("files-hidden");
      $("code-view").classList.toggle("files-open");
    } else $("code-view").classList.toggle("files-hidden");
    updateLayout();
  });
  $("diff-layout").addEventListener("change", (event) => {
    layoutPreference = event.target.value;
    try {
      localStorage.setItem("pr-code-diff-layout", layoutPreference);
    } catch {
      notify(
        "Diff layout applies for this session; browser storage is unavailable.",
      );
    }
    updateLayout();
  });
  const diffToolbar = document.querySelector(".diff-toolbar");
  new ResizeObserver(() => {
    document.querySelector(".diff-column").style.setProperty("--diff-toolbar-height", `${diffToolbar.offsetHeight}px`);
  }).observe(diffToolbar);
  new ResizeObserver(updateLayout).observe(
    document.querySelector(".diff-column"),
  );
  $("comment-filter").addEventListener("change", (event) => {
    commentFilter.mode = event.target.value;
    focusedThread = null;
    try {
      localStorage.setItem("pr-code-comment-filter", commentFilter.mode);
    } catch {}
    renderFiles();
    renderComments();
  });
  $("comment-bots").addEventListener("change", (event) => {
    commentFilter.bots = event.target.checked;
    focusedThread = null;
    try {
      localStorage.setItem("pr-code-comment-bots", commentFilter.bots ? "shown" : "hidden");
    } catch {}
    renderFiles();
    renderComments();
  });
  // Toggle does not bubble; capture it to remember each thread's open state.
  document.addEventListener(
    "toggle",
    (event) => {
      const thread = event.target.closest?.(".review-thread");
      if (thread === event.target) {
        openThreads.set(thread.dataset.thread, thread.open);
        if (!thread.open && focusedThread === thread.dataset.thread) focusedThread = null;
      }
      alignSplitRows();
    },
    true,
  );
  $("comments-toggle").addEventListener("click", () => showRail("comments"));
  $("file-filter").addEventListener("input", renderFiles);
  $("unviewed-only").addEventListener("change", renderFiles);
  $("wrap-lines").addEventListener("change", (event) => {
    $("files").classList.toggle("wrap-code", event.target.checked);
    alignSplitRows();
  });
  $("collapse-all").addEventListener("click", () => {
    const all = data.files.every((f) => saved.collapsed.includes(f.path));
    saved.collapsed = all ? [] : data.files.map((f) => f.path);
    $("collapse-all").textContent = all ? "Collapse all" : "Expand all";
    persist();
    renderFiles();
  });
  $("code-tab").addEventListener("click", () => setTab("code"));
  $("review-tab").addEventListener("click", () => setTab("review"));
  $("chat-toggle").addEventListener("click", () => {
    showRail();
    $("question").focus({ preventScroll: true });
  });
  $("notes-toggle").addEventListener("click", () => showRail("notes"));
  $("close-rail").addEventListener("click", closeRail);
  $("ask-selection").addEventListener("click", () => {
    attachContext(selection);
    $("selection-bar").hidden = true;
    window.getSelection()?.removeAllRanges();
  });
  $("clear-selection").addEventListener("click", () => {
    selection = null;
    paintSelection();
  });
  // Code blocks in chat answers and GitHub comments (including suggestions).
  document.addEventListener("click", async event => {
    const button = event.target.closest("[data-copy-code]");
    if (!button) return;
    try {
      await navigator.clipboard.writeText(button.closest(".chat-code").querySelector("code").textContent);
      notify("Code copied.");
    } catch { notify("Could not copy code. Select it and copy manually."); }
  });
  $("new-thread").addEventListener("click", () => beginThread());
  $("thread-picker").addEventListener("change", (event) => {
    selectThread(event.target.value || null);
    draftContexts = [];
    $("question").value = "";
    renderChat();
    if (isRunning(currentThread())) pollChat(threadId);
  });
  $("chat-form").addEventListener("submit", (event) => {
    event.preventDefault();
    ask($("question").value);
  });
  $("question").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      ask($("question").value);
    }
  });
  $("note-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const text = $("note-text").value.trim();
    if (!text) return;
    if (editingNote !== null) {
      saved.notes[editingNote].text = text;
      editingNote = null;
    } else
      saved.notes.push({
        id: noteId(),
        created_at: new Date().toISOString(),
        base: data.base,
        head: data.head,
        text,
        context: selection ? structuredClone(selection) : null,
      });
    persist();
    $("note-text").value = "";
    renderNotes();
    notify("Private note saved.");
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (!$("conversation").hidden) closeRail();
      else {
        selection = null;
        paintSelection();
      }
    }
  });
  function watchLoad(loadId) {
    const started = Date.now();
    let timer;
    let stopped = false;
    const poll = async () => {
      try {
        const snapshot = await api.loadProgress(loadId);
        if (stopped) return;
        const view = loadProgress(snapshot, Date.now() - started);
        const bar = $("loading-bar");
        bar.classList.toggle("indeterminate", view.percent === null);
        if (view.percent === null) bar.removeAttribute("aria-valuenow");
        else bar.setAttribute("aria-valuenow", view.percent);
        bar.style.setProperty("--loaded", (view.percent ?? 0) / 100);
        $("loading-percent").textContent = view.percent === null ? "" : view.percent + "%";
        $("loading-step").textContent = view.label;
        // Show what is loading as soon as GitHub returns the pull request.
        if (snapshot.title) {
          $("pr-title").textContent = snapshot.title;
          $("pr-identity").textContent = `${snapshot.repository} #${snapshot.number}`;
        }
      } catch {
        // Progress is decorative; the load request reports real failures.
      }
      if (!stopped) timer = setTimeout(poll, 400);
    };
    timer = setTimeout(poll, 150);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }
  async function init() {
    const loadId =
      crypto.randomUUID?.() ||
      Date.now().toString(36) + Math.random().toString(36).slice(2);
    const stopWatching = watchLoad(loadId);
    try {
      data = await api.load(params.get("revision"), loadId).finally(stopWatching);
      saved = hydrate(data.saved);
      saver = new SaveQueue(
        api,
        data.revision,
        data.saved.version,
        storageError,
      );
      $("refresh-comparison").hidden = false;
      if (params.has("revision")) {
        $("storage-error").textContent =
          "Historical comparison. Viewed status is read-only. Notes and chat stay available; check for new commits to return to latest.";
        $("storage-error").hidden = false;
      }
      const selected =
        saved.threads.find((t) => t.id === params.get("chat")) ||
        saved.threads.find(isRunning);
      if (selected) {
        selectThread(selected.id);
        showRail();
        if (isRunning(selected)) pollChat(threadId);
      }
      reviewTimer = setTimeout(updateReview, 15000);
      $("pr-identity").textContent = `${data.repository} #${data.number} ↗`;
      $("pr-identity").href = data.url;
      $("pr-identity").setAttribute("aria-label", `Open ${data.repository} #${data.number} on GitHub (new tab)`);
      $("pr-title").textContent = data.title;
      $("pr-author").textContent = data.author;
      $("pr-state").textContent = data.prState || "Open";
      $("pr-state").hidden = false;
      $("comparison").textContent =
        data.base.slice(0, 12) + " → " + data.head.slice(0, 12);
      $("file-count").textContent = data.files.length;
      $("diff-totals").innerHTML =
        `<span class="added">+${data.files.reduce((sum, f) => sum + f.additions, 0)}</span><span class="deleted">−${data.files.reduce((sum, f) => sum + f.deletions, 0)}</span>`;
      initialControls.forEach((control) => (control.disabled = false));
      $("prompt-addressed").dataset.prompt = ADDRESSED_PROMPT;
      $("comment-filter").value = commentFilter.mode;
      $("comment-bots").checked = commentFilter.bots;
      $("loading-workspace").hidden = true;
      $("workspace-body").hidden = false;
      renderReview();
      renderFiles();
      if (currentThread()) renderChat();
      setTab(tab);
      loadComments();
      if (data.files.length) {
        const index = Math.max(
          0,
          data.files.findIndex((f) => f.path === params.get("path")),
        );
        await ensureFile(index);
        if (params.has("line"))
          await jump(
            index,
            [Number(params.get("line"))],
            params.get("side") || "head",
          );
      }
    } catch (error) {
      $("loading-workspace").hidden = true;
      $("load-error").textContent = error.message;
      $("load-error").hidden = false;
      $("workspace-body").hidden = true;
      try {
        const info = await api.review("");
        $("load-error").innerHTML = unavailableHTML(error, info, esc);
      } catch {
        // Keep the original loading error if saved reports are unavailable too.
      }
    }
  }
  window.addEventListener("message", async (event) => {
    const frame = document.querySelector(".review-frame");
    if (!frame || event.source !== frame.contentWindow) return;
    if (event.data?.type === "workspace-report-ready") { syncReportTheme(); return; }
    // Walk reports use the full width of the AI review tab.
    if (event.data?.type === "workspace-report-layout") { $("ai-view").classList.toggle("ai-view-wide", event.data.layout === "walk"); return; }
    if (event.data?.type === "workspace-report-size") {
      const height = event.data.height;
      if (Number.isFinite(height) && height > 0 && height <= 1000000) frame.style.height = Math.ceil(height) + "px";
      return;
    }
    if (event.data?.type === "workspace-report-scroll") {
      const top = event.data.top;
      if (Number.isFinite(top) && top >= 0 && top <= frame.offsetHeight) {
        const view = $("ai-view");
        view.scrollTop += frame.getBoundingClientRect().top - view.getBoundingClientRect().top + top;
      }
      return;
    }
    if (event.data?.type !== "workspace-code") return;
    const target = sourceTarget(event.data.url, data);
    if (!target) {
      notify(
        "This source link is outside the current comparison. Check the report revision.",
      );
      return;
    }
    const index = data.files.findIndex(
      (file) =>
        file.path === target.path ||
        (target.side === "base" && file.previous === target.path),
    );
    if (!(await ensureFile(index))) return;
    const rows = data.files[index].rows.filter((row) => {
      const number = target.side === "base" ? row.old : row.new;
      return number !== null && number >= target.start && number <= target.end;
    });
    if (!rows.length) {
      notify("The referenced lines are unavailable in this comparison.");
      return;
    }
    await jump(
      index,
      rows.map((row) => row.id),
      target.side,
    );
    if (event.data.action === "ask") attachContext(selection);
  });
  init();
})();
