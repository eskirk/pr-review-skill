/** HTTP boundary plus serialized optimistic saves. Never retries model submissions. */
export class WorkspaceAPI {
  constructor(url, token, fetcher = (...args) => fetch(...args)) {
    this.url = url;
    this.token = token;
    this.fetcher = fetcher;
  }
  async request(path, data, signal) {
    const response = await this.fetcher(
      path,
      data
        ? {
            method: "POST",
            signal,
            headers: {
              "Content-Type": "application/json",
              "X-CSRF-Token": this.token,
            },
            body: JSON.stringify({ url: this.url, ...data }),
          }
        : { signal },
    );
    const result = await response.json();
    if (!response.ok)
      throw new Error(result.error || `Request failed (${response.status}).`);
    return result;
  }
  get(endpoint, query = {}) {
    return this.request(
      endpoint + "?" + new URLSearchParams({ url: this.url, ...query }),
    );
  }
  load(revision, load) {
    return this.get("/api/workspace", { ...(revision ? { revision } : {}), load });
  }
  loadProgress(load) {
    return this.get("/api/workspace-progress", { load });
  }
  file(revision, path) {
    return this.get("/api/workspace-file", { revision, path });
  }
  review(head) {
    return this.get("/api/workspace-review", { head });
  }
  comments(refresh) {
    return this.get("/api/workspace-comments", refresh ? { refresh: "1" } : {});
  }
  chat(threadId) {
    return this.get("/api/workspace-chat", { thread_id: threadId });
  }
  ask(revision, threadId, question, contexts) {
    return this.request("/workspace-chat", {
      revision,
      thread_id: threadId,
      question,
      contexts,
    });
  }
  stop(threadId) {
    return this.request("/workspace-chat-cancel", { thread_id: threadId });
  }
  finding(revision, version, finding) {
    return this.get("/api/workspace-finding", { revision, version, finding });
  }
  postComment(revision, version, finding, body) {
    return this.request("/workspace-comment", { revision, version, finding, body });
  }
}
export class SaveQueue {
  constructor(api, revision, version, onError) {
    Object.assign(this, {
      api,
      revision,
      version,
      onError,
      pending: null,
      running: null,
      failed: false,
    });
  }
  enqueue(state) {
    this.pending = structuredClone(state);
    if (!this.running && !this.failed) this.running = this.drain();
    return this.running;
  }
  async drain() {
    try {
      while (this.pending) {
        const state = this.pending;
        this.pending = null;
        const result = await this.api.request("/workspace-save", {
          ...state,
          revision: this.revision,
          version: this.version,
        });
        this.version = result.version;
      }
    } catch (error) {
      this.failed = true;
      this.onError(error);
    } finally {
      this.running = null;
    }
  }
  async flush() {
    await this.running;
    if (this.failed)
      throw new Error(
        "Private changes could not be saved. Reload to resolve the conflict before continuing.",
      );
  }
}
