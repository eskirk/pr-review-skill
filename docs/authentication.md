# GitHub and AI authentication

[Back to the README](../README.md#install-and-run)


GitHub access and AI access are separate. The server runs local CLI/SDK processes
under your OS account; there is no dashboard account or token-entry form.
Authenticate in the terminal as the same user who runs the server.

| Connection | Used for | Authentication |
|---|---|---|
| GitHub CLI (`gh`) | Inbox, reporting, PR source, review threads and follow-up checks | Your GitHub CLI login |
| Codex | Triage, AI reviews and code chat | Your local Codex authentication |
| Claude Code | Triage, AI reviews and code chat | Your local Claude Code authentication |
| OpenAI API | Triage only | `OPENAI_API_KEY` in the server environment; separate API billing |

## GitHub

Install [GitHub CLI](https://cli.github.com/), then sign in and check access:

```sh
gh auth login --hostname github.com --web
gh auth status --hostname github.com
gh api user --jq .login
gh pr view https://github.com/OWNER/REPOSITORY/pull/123 --json url,title
```

Replace the example URL with a PR you can access. The dashboard uses `gh` for
REST/GraphQL reads and the code-chat checkout uses `gh auth git-credential` for
its HTTPS fetch. No separate GitHub OAuth app or copied token is needed.
Your GitHub account must have access to the repository, including any required
organization SSO authorization. An SSH key alone does not authenticate these API
reads. GitHub CLI manages stored credentials; `GH_TOKEN` or `GITHUB_TOKEN` can
also supply authentication to the server process. See [GitHub CLI authentication](https://cli.github.com/manual/gh_auth_login).

Dashboard actions read GitHub by default. An explicit confirmation on an embedded AI review finding can post its prepared comment or reply through `gh`; the dashboard does not approve, merge or resolve threads. Review agents themselves remain read-only.
This does not reduce the permissions of the underlying GitHub credential.
My reviews binds its queue to the first synced GitHub account. Switching accounts
produces an error; use a separate `PR_REVIEW_TRACKER_HOME` for another account.

## Codex

Install the [Codex CLI](https://developers.openai.com/codex/cli/), then authenticate:

```sh
codex login
codex login status
```

The browser login uses your ChatGPT account. Codex also supports API-key
credentials, with API billing; `codex login status` identifies the active method.
See [Codex authentication](https://developers.openai.com/codex/auth/).

Install the dashboard's pinned Python runtime from the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-triage.txt
.venv/bin/python scripts/pr_server.py
```

Use this interpreter for the server, or set `PR_REVIEW_PYTHON` to its absolute
path for workers. The `openai-codex` runtime starts local Codex sessions; full
reviews use its app-server connection and chat resumes a saved native session.
The dashboard relies on the local authentication available to that process,
including the same `CODEX_HOME` when customized. It does not copy Codex credentials
into tracker settings. An `OPENAI_API_KEY` for the separate Triage API provider
does not sign you into Codex.

## Claude Code

Install [Claude Code](https://code.claude.com/docs/en/setup), then authenticate:

```sh
claude auth login
claude auth status
```

Claude Code manages its login and billing mode. Console login is an API-billed
option; see the [Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference).
Install Node.js 22.16+ and the pinned review/chat bridge from the repository root:

```sh
npm ci --prefix scripts/claude-runtime
```

Triage runs the installed `claude` CLI with tools disabled. Reviews and chat use
the bundled Claude Agent SDK bridge with that executable and its normal
environment/login. The dashboard does not extract subscription tokens or send
them directly to Anthropic HTTP endpoints. `PR_REVIEW_CLAUDE` and `PR_REVIEW_NODE`
can select absolute executable paths if they are not on the server's `PATH`.

## Select providers and troubleshoot

In **Settings → AI settings**, select a provider, model and reasoning level for
each feature, then **Save all settings**. Triage supports all three AI providers;
AI review and Chat support Codex and Claude Code. Existing chats retain their
original provider and settings; start a new conversation to use a changed profile.

For OpenAI API triage, install `requirements-triage.txt`, supply `OPENAI_API_KEY`
through your server environment, and choose **OpenAI API** under Triage. There is
no key field in the UI, and a Codex/ChatGPT login does not authenticate this provider.

If a connection fails, check the relevant login command above and repository or
model access. Run the server from that same terminal to isolate service-environment
problems. A launchd service does not automatically inherit your interactive shell's
`PATH` or exported keys; see [service setup](../references/dashboard.md#automatic-startup-on-macos).
Restart the server after changing its environment or runtime installation.
Failures stay visible and never silently switch providers.

