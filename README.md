# PR Review Skill

A local dashboard and AI review skill for GitHub pull requests. Find what needs
your attention, understand a change, inspect its code and discussion, and turn
verified findings into review comments you can edit and post yourself.

Use the dashboard with your GitHub CLI login. Add Codex or Claude Code for AI
reviews, review load estimates and code chat. You can also run the review skill
directly from an AI coding agent, without the dashboard.

The app runs on your machine: a Python server with plain HTML, CSS and JavaScript.
No frontend build or database service is required. GitHub operations are read-only;
the dashboard does not post comments, approve or merge PRs.

[Features](#what-it-does) · [Screenshots](#screenshots) ·
[Install and run](#install-and-run) · [First review](#run-your-first-review) ·
[Authentication](docs/authentication.md) · [Documentation](#documentation)

## What it does

| Feature | What you can do |
|---|---|
| **PR inbox** | Browse review requests, watched repositories and your own PRs. Filter by author, repository, review status or draft state; save named filter presets; snooze or hide items. |
| **My reviews** | Keep an ordered queue, save private notes and reminders, snooze PRs you'll get to later, and see when new commits or replies bring a PR back to you. |
| **Review load** | Get optional Low, Medium, High or Unsure estimates of how much reviewing a PR will take, split into change scope, required context, complexity and risk, with reasons, filters and a daily call limit. |
| **AI reviews** | Run Codex or Claude Code, follow live progress, add guidance, optionally include selected private notes or Ask AI conversations, ask questions, wrap up early or stop a run. Existing PR comments are read first, so findings already raised become replies to their threads. Continue a finished review's session in either agent. After small follow-up commits, update a review instead of redoing it: previous findings are re-checked and only the affected parts are redone. Keep the newest reports and run history. |
| **Review reports** | One scrolling page: why the PR exists (sourced from the PR, issue or commits), what is different now, an at-a-glance strip with findings and judgment calls, background with a where-it-sits map for repositories you don't know, the change with a visual that fits it, the key code inline and the blast radius, followed by step-by-step findings with fix sketches, copyable draft comments, a short self-check and verification limits. |
| **Code workspace** | Read unified or side-by-side diffs, expand context, open full files and track viewed files. Inspect inline GitHub threads and the PR conversation. |
| **Code chat** | Ask about selected lines or comments, investigate the pinned revision and draft replies. Conversations persist with their original provider, model and revision. |
| **Reporting** | Explore daily and weekly review/merge activity, completed-week comparisons and workday trends with time-off exclusions, plus estimated AI review cost for the last 30 days. |
| **Settings** | Choose providers, models and reasoning independently for Triage, AI review and Chat. Configure watched repositories, repositories trusted to run blocked checks outside the sandbox, and light, dark or system appearance. |

AI reviews cover the full diff through correctness, contracts and security lenses,
verify candidate findings, and record what was actually checked. The result is
review assistance; you decide which comments to send and whether to approve.

## Screenshots

**Inbox:** one row per review request with its size, review load and AI review state, and an entry into each PR's workspace.

![PR inbox with fictional pull requests, review load estimates and Open review actions](docs/screenshots/inbox-light.jpg)

**Code workspace:** the diff, inline review threads and GitHub discussion together.

![Code workspace with a fictional batch transport diff, inline thread and Comments rail](docs/screenshots/code-workspace-light.jpg)

<details>
<summary>More screenshots: reports, review queue, live AI reviews, settings, reporting and AI cost</summary>

**Review report:** why the PR exists, the current assessment, what is different now and an at-a-glance strip, all on one scrolling page.

![Review report opening with a sourced why, its assessment, the outcome and At a glance for a fictional parser](docs/screenshots/review-overview-light.jpg)

**The change:** a claim heading, the rule in plain words, an approach note, before/after diagrams and a grid of each situation with the finding it hits.

![Fictional parser change with an approach note, before/after flowcharts and a situation grid with finding badges](docs/screenshots/review-explainer-light.jpg)

**Findings:** expand a finding for the problem in one sentence, a walkthrough, whether it is real, a fix sketch and the draft comment.

![Two fictional findings, one expanded with its walkthrough, fix sketch and copyable comment](docs/screenshots/review-findings-light.jpg)

**My reviews:** see whose turn it is, what changed, where you stopped and what you snoozed.

![Personal review queue with update indicators, private notes and snooze controls](docs/screenshots/my-reviews-light.jpg)

**Live review:** follow progress, ask questions, add guidance or request an early wrap-up.

![Simulated AI review with stage progress, a question and reply, and wrap-up controls](docs/screenshots/live-review-light.jpg)

**AI settings:** choose a separate provider and model for each feature, and list the repositories you know well so their reports skip the basics.

![Independent Triage, AI review and Chat provider settings above the Repositories I know well list](docs/screenshots/ai-settings-light.jpg)

**Reporting:** review and merge activity, trend lines and a selected day's PRs.

![Reporting in dark mode with fictional daily activity and workday trends](docs/screenshots/reporting-dark.jpg)

**AI review cost:** estimated cost over the last 30 days, by day, provider and model, with the most expensive reviews.

![Fictional AI review cost for 30 days with daily bars by provider, cost by model and the costliest reviews](docs/screenshots/reporting-cost-light.jpg)

</details>

All screenshots use synthetic data, captured September 24–October 20, 2026 from the actual
UI. See [screenshot provenance and refresh instructions](docs/screenshots/README.md).

## Install and run

### Requirements

- macOS or Linux, Python 3.11+, Git and [GitHub CLI](https://cli.github.com/).
  The backend uses Unix facilities; Windows is not supported.
- A GitHub account with access to the repositories you want to review.
- For AI features, an authenticated [Codex CLI](https://developers.openai.com/codex/cli/)
  or [Claude Code](https://code.claude.com/docs/en/setup) installation and the
  provider runtime described below. Claude reviews/chat also need Node.js 22.16+.

The inbox, review queue, code browser and reporting work without an AI provider.
Full AI review validation needs a disposable execution sandbox; report browser
checks also need Node.js, Playwright and Chrome/Chromium. Reports draw Mermaid
diagrams with the report runtime (`npm ci --prefix scripts/report-runtime`) and the
installed Chrome. See [review validation setup](references/authoring.md).

### 1. Clone the repository

```sh
git clone https://github.com/robert-northmind/pr-review-skill.git \
  ~/.agents/skills/pr-review
cd ~/.agents/skills/pr-review
```

Use an existing checkout if you already have one. Another directory also works;
use that path when referring to the skill from your agent.

### 2. Connect GitHub

```sh
gh auth login --hostname github.com --web
gh auth status --hostname github.com
```

Use the same OS account for login and the server. The app uses `gh` for GitHub
API reads and for authenticated HTTPS source fetches in code chat. No dashboard
GitHub account or token-entry form is needed. Private repositories require your
normal repository access and any organization SSO authorization.

### 3. Start the dashboard

```sh
python3 scripts/pr_server.py
```

Open [http://127.0.0.1:8765/](http://127.0.0.1:8765/) and click **Sync GitHub**.
Review requests and your own PRs appear after sync. In **Settings → Repositories**,
add repositories as `owner/repository` and sync again to populate **Watching**.

Keep the terminal running; Ctrl-C stops the server. If the port is occupied:

```sh
python3 scripts/pr_server.py --port 8766
```

Then open [http://127.0.0.1:8766/](http://127.0.0.1:8766/).
For automatic startup, see [macOS service setup](references/dashboard.md#automatic-startup-on-macos).

### 4. Enable an AI provider (optional)

GitHub and AI logins are separate. Configure either provider or both, using the
same OS account and environment as the server. Run these commands from the
repository root. Stop the server before restarting it with an installed runtime.

**Codex**

```sh
codex login
codex login status
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-triage.txt
.venv/bin/python scripts/pr_server.py
```

The pinned Python runtime starts local Codex sessions using your Codex
authentication. Browser login uses ChatGPT; Codex API-key login uses API billing.
See [Codex authentication](https://developers.openai.com/codex/auth/).

**Claude Code**

```sh
claude auth login
claude auth status
npm ci --prefix scripts/claude-runtime
python3 scripts/pr_server.py
```

The pinned Claude Agent SDK bridge uses your installed Claude Code executable
and its local authentication. Triage uses the Claude CLI directly. If you also
installed the Codex runtime, start the server with `.venv/bin/python` instead.
See [Claude Code authentication commands](https://code.claude.com/docs/en/cli-reference).

In **Settings → AI settings**, choose the provider, model and reasoning for
**Triage**, **AI review** and **Chat**, then **Save all settings**. Providers can
be mixed. Existing chats keep their original configuration; changed settings
apply to new conversations. Provider failures never silently switch providers.

**OpenAI API** is an additional option for Triage only. It requires
`requirements-triage.txt` and `OPENAI_API_KEY` in the server environment, with
separate API billing. A Codex/ChatGPT login does not authenticate this option.

For how each connection works, credential handling and service-environment
troubleshooting, see [GitHub and AI authentication](docs/authentication.md).

## Run your first review

1. Sync GitHub and choose a PR, or paste a PR URL into **My reviews → Add PR**.
2. Select **Open review**. Use **Code changes** to inspect the diff and discussion.
3. In **AI review**, choose **Generate AI review**. Use **Run with guidance…**
   to focus that run, for example: “Docs only; skip tests.”
4. Follow live activity. Ask questions or steer the review while it runs.
   **Wrap up now** requests a report with unfinished checks recorded as gaps;
   **Stop review** cancels the worker and preserves saved activity.
5. Read the completed report in **AI review**: assessment, explanation, findings
   and verification evidence. Review and edit draft comments before posting on GitHub.
   **Continue in Claude Code/Codex** copies a command that opens the review's
   session in a terminal; **Copy handoff prompt** hands it to either agent.
6. Use **Hand back to author** in My reviews when you are waiting for a response.
   New commits, relevant replies or a due reminder can bring the PR back to you.
   To set a PR aside for a few days without handing it back, use **Snooze**.

Reports remain available during reruns, and outdated results are marked.
Finishing an AI run does not submit a GitHub review or finish your personal review.
For later code questions, use the workspace's persistent **Ask AI** chat.

### Use the skill directly in an agent

Give your coding agent this instruction, replacing the PR URL:

```text
Read ~/.agents/skills/pr-review/SKILL.md and run a full review of
https://github.com/OWNER/REPOSITORY/pull/123.
```

You can also use **Copy review prompt** from a PR's actions menu. Automatic skill
discovery depends on your agent's search paths; cloning here alone does not
configure every CLI. The renderer and neutral comment-writing guidance are
bundled. Dashboard AI reviews also inject `my-feedback-voice` when it is found
at `~/.pi/agent/skills/my-feedback-voice/SKILL.md`,
`~/.agents/skills/my-feedback-voice/SKILL.md`, or the path set by
`PR_REVIEW_STYLE_SKILL`. It applies only to copyable comments, summaries and
replies; the repository's review and safety rules remain authoritative.

## Configuration and data

| Setting | Purpose |
|---|---|
| `PR_REVIEW_LOCAL_DEV_ROOT` | Existing checkout discovery root; defaults to `~/Development`. |
| `PR_REVIEW_TRACKER_HOME` | Local state and report directory; defaults to `~/.local/share/pr-review-tracker/`. Use separate homes for different GitHub accounts. |
| `PR_REVIEW_PYTHON` | Python interpreter for background workers. |
| `PR_REVIEW_CLAUDE` / `PR_REVIEW_NODE` | Explicit Claude Code and Node.js executable paths when needed. |
| `PR_REVIEW_STYLE_SKILL` | Optional path to a local writing-style `SKILL.md`; defaults to the two `my-feedback-voice` locations described above. |

Set environment variables before starting the server. A background service may
have a different `PATH` and environment from your terminal.

The server listens on loopback. GitHub sync reads with your `gh` credentials;
AI features send relevant PR descriptions, code/diffs and questions to the
selected provider. When a writing-style skill is applied, its bounded contents
are sent with the review prompt as well. Enable them only for repositories and
local style guidance you can share with that provider. Private notes and Ask AI
conversations stay local by default. An explicitly
selected note or conversation can be included as quoted context in a guided AI
review; selected content is sent to the configured provider and retained in that
review's local run history.

Reports, cached source and conversations are stored outside this repository.
Local data for a PR, including its AI review runs, expires 7 days after the PR's
confirmed close/merge date, and only the newest three runs per PR are kept.
Reporting keeps its own history. Running work or cleanup errors defer deletion. Provider
session history is separate and is not deleted by tracker cleanup.

Follow-up checks run every five minutes while the dashboard is visible; there
are no queue checks or notifications while it is closed. Running AI work can
continue independently. Reporting uses a fixed Europe/Berlin timezone and covers
four complete weeks plus the current week.

## Documentation

| Guide | Contents |
|---|---|
| [Authentication](docs/authentication.md) | GitHub CLI, Codex, Claude Code, API triage and connection troubleshooting. |
| [Using the dashboard](docs/usage.md) | Review reports, queue transitions, reminders, reporting, code chat and privacy. |
| [Review workflow](SKILL.md) | Agent instructions, full-diff coverage, finding verification and sandboxed checks. |
| [Dashboard reference](references/dashboard.md) | Configuration, background services, providers and operational details. |
| [Code workspace](references/code-workspace.md) | Diff behavior, GitHub comments, persistent chat and current limits. |
| [Development](docs/development.md) | Tests, browser setup, repository structure and security scans. |
| [Screenshot maintenance](docs/screenshots/README.md) | Synthetic fixtures and repeatable screenshot capture. |
| [Changelog](CHANGELOG.md) | Notable changes, newest first. |
| [Recovery](RECOVERY.md) | Git recovery procedures. |

## Development and recovery

Run the regression suites from the repository root:

```sh
python3 tests/run.py
```

JavaScript tests need Node.js; browser tests also need Playwright and Chrome.
See [development setup and focused checks](docs/development.md) before running
those suites. Reload the page after asset changes; restart the server after
Python changes.

## License

[MIT](LICENSE), copyright © 2026 Robert Magnusson.
