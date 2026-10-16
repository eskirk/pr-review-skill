# Using PR Review Skill

[Back to the README](../README.md)

## Run a review

Make this skill discoverable by your agent. Skill search
paths depend on the agent; placing the folder here alone does not configure
every CLI. You can also give an agent the explicit instruction:

```text
Read ~/.agents/skills/pr-review/SKILL.md and run a full review of
https://github.com/OWNER/REPOSITORY/pull/123.
```

From the dashboard, choose **Run AI review** in a PR’s actions menu or open
**Open review → AI review → Generate AI review** to generate the combined report.
Both providers run in a background worker with live progress inside the dashboard.
They use the skill prompt and
the selected agent's authentication. Use **Copy review prompt** to paste the
same instructions into another agent session.

**Run with guidance…** (in the PR actions menu and the workspace AI review tab)
starts the same review with a short steering note, such as "Docs only; skip
tests" or "Only iOS changed; validate on iOS". The note applies to that run only.

When new commits arrive after a finished review, **Update AI review** (on the
card and in the workspace AI review tab) builds on the previous report instead
of starting over. It re-checks every previous finding at the new head, reviews
the new commits and the code around them, and updates only the explanation
sections they affect. The report opens with **Since the last review**: which
findings were resolved, are still open, changed or are new. Updates are only
offered when the PR was not rebased, still builds on the same base commit, and
changed at most 500 lines in 20 files, with a full review required after three
updates in a row. With automatic estimates on, the card also says whether an
update or a full review is suggested. **Run full AI review** is always available.

After a review finishes, the AI review tab can continue its conversation outside
the dashboard. **Continue in Claude Code** (or **Continue in Codex**) copies a
terminal command that forks the review's own session with its full history:
`claude --resume <id> --fork-session` from the review's working directory, or
`codex fork <id>`. Forking leaves the original review session unchanged.
**Copy handoff prompt** copies a short prompt for a new session in either agent.
It names the session ID, the transcript path and the run's review notes, so a
Codex session can pick up a Claude Code review and the other way round. Both
buttons use the session behind the report shown. They are disabled when the
agent has deleted that transcript. By default, Claude Code deletes transcripts
after 30 days (`cleanupPeriodDays`).

The agent records progress and artifacts in the local tracker. When finished,
click **Open review** on the PR's row and select **AI review**. There is one report and one review skill:

1. **Understand the change:** a walk of scenes shown one at a time (use the scene
   list, Previous/Next, 1–9 or the arrow keys; **Show all scenes** for one long
   page). What changed shows before and after, with Mermaid diagrams where call or
   event order matters; why it matters walks through a concrete example and a grid
   of situations; how it works pairs each logical change with its exact diff; the
   blast radius separates what is affected from what is not. Finding badges mark
   where each finding goes wrong. A short self-check tests the key distinction.
2. **Read the assessment and findings:** each finding starts collapsed with its
   severity and a plain-words title visible. Open it for the problem in one
   sentence, why it matters, a numbered walkthrough, whether it is real (with the
   strongest counter-argument), a fix sketch, evidence, and a copyable comment.
   Multiple findings have **Expand all / Collapse all** controls.
3. **Check the verification appendix:** inspected scope, checks and outcomes,
   unresolved gaps, and reviewer allocation with requested versus known effective
   model and effort settings.

The workflow covers the full diff with correctness, security, and contract
review lenses, then verifies candidates before reporting them. Existing review
threads, comments and reviews on the PR are saved into the run first. A finding
someone already raised is marked **Already discussed** with a link to the
thread, and its draft becomes a reply that adds something new instead of a
duplicate comment. Model selection
is an adaptive policy, not a guarantee of review quality. See the
[review approach](../references/review-practices.md) and
[allocation policy](../references/reviewer-allocation.md).
Review comments are drafts; read and edit them before posting them yourself.

## Keep track of your reviews

Click **Add to Up next** on a PR or paste its link into **My reviews**. The page
groups tracked PRs by whose turn it is:

- **Your turn**: **In progress** (reviews you started), **Back to you** (waiting
  PRs with new commits, relevant replies, a review re-request or a due reminder)
  and **Up next** (in your order).
- **Their turn**: **Waiting for author**.
- **Finished**: **Merged or closed** and **Stopped tracking**.

Every section collapses, shows its count and remembers its state across reloads.
Waiting for author and Finished start collapsed. Each PR shows why it is in its
section, such as "You handed it back to the author 3d ago" or "Added from GitHub
because you commented or reviewed".

Buttons are named after where the PR goes:

| Button | Where the PR goes |
|---|---|
| **Start review** / **Review now** / **Continue review** | In progress |
| **Hand back to author** | Waiting for author, or Back to you if updates arrived during your review |
| **Pause** | Top of Up next, keeping pending updates |
| **Keep waiting** | Stays in Waiting for author; only newer updates bring it back |
| **Mark updates seen** | Stays in progress; clears the updates shown as new |
| **Remind me** (1 day, 3 days, 1 week) | Back to you when due, unless something else brings it back first |
| **Stop tracking** (in •••) | Stopped tracking; **Track again** returns it to Up next |

Each move shows a confirmation with **Show**, which opens the section and
highlights the PR, and **Undo**. Moves made by GitHub sync, a due reminder or
another tab are announced the same way. **Find a tracked PR** searches every
tracked PR, including finished ones, and shows which section each is in.
Opening a PR does not clear its updates.

Opening a review and returning via **PR reviews** or browser Back restores the
overview's scroll position after the cards load. Positions stay in the current
browser tab, separately for My reviews and each Inbox filter selection.

Completing an AI run does not submit a GitHub review or finish your work.

GitHub sync automatically places confirmed closed/merged PRs in **Merged or
closed**, sorted by latest activity. Open PRs you commented on or reviewed are
followed in Waiting for author unless already tracked or explicitly stopped.
Closed/merged entries, private notes, code conversations and AI review runs
expire 7 days after GitHub's close/merge date, on the next successful check, and
only the newest three runs per PR are kept. Reporting keeps its own history. Build caches, report-check screenshots and workspace caches unused for
7 days are removed automatically. Preview the cleanup with
`python3 scripts/storage_cleanup.py --dry-run`.
Running work and cleanup failures defer deletion and show an error.
Reporting keeps its separate activity window.

Saved PRs and participation history are checked every five minutes while the dashboard is visible.
A newly added or restored PR is checked on its own right away, and Sync GitHub stays available during background checks.
There are no checks or notifications while the page is closed.

## See your activity

Open **Reporting** and click **Sync GitHub**. The report
covers four complete weeks and the current week, using Europe/Berlin dates.
Switch between **Daily** and **Weekly**, select a chart bar, or click
**Yesterday** to see the associated PRs. Reporting has its own repository
filter; hiding an inbox PR does not remove it from your activity.

**AI review cost** at the bottom of Reporting covers the last 30 days of in-app
reviews: the total, the number of reviews, the average per review, daily cost by
provider, cost by model and the most expensive reviews. Select a day to list its
reviews. Amounts are API-price estimates reported by Claude Code and Codex,
including sub-agents; what you actually pay depends on your plan. Reviews that
finished before cost tracking existed are filled in from the last 45 days when the
server starts.

Daily bars include separate review and merge trend lines. **Activity trend**
uses the last 10 complete workdays by default; select 5 for a faster-moving
average. Weekends and dates marked under **Time off** are excluded, while
zero-activity workdays count. The line stays flat across excluded days and
starts once a full window is available. Today and the last synced day remain
outside the average until a later sync confirms their full activity.

Time off accepts an inclusive date range; use the same start and end for a
single day, or **Remove** to include those weekdays again. These preferences
are saved in the current browser. Bars and weekly totals retain all activity,
including PRs reviewed or merged on excluded days. Trend values are daily
averages; weekly counts remain distinct PRs for the week.

## Personalize the installation

- Set `PR_REVIEW_LOCAL_DEV_ROOT` to the directory containing your existing clones.
  It defaults to `~/Development` and is used as a checkout discovery hint.
- Optionally configure a writing-style skill for personalized comments. Dashboard AI
  reviews inject `my-feedback-voice` from `~/.pi/agent/skills/` or `~/.agents/skills/`,
  or from the path in `PR_REVIEW_STYLE_SKILL`, when available. It affects copyable
  comments, summaries and replies only.
- Reporting's Europe/Berlin timezone is currently fixed in the backend and UI;
  it is not a dashboard setting.
- For automatic startup on macOS, generate a launchd plist for your installation
  using [the service setup instructions](../references/dashboard.md#automatic-startup-on-macos).
  Running the server manually is sufficient to get started.

For example, start with a different checkout directory:

```sh
export PR_REVIEW_LOCAL_DEV_ROOT="$HOME/Projects"
python3 scripts/pr_server.py
```

`PR_REVIEW_TRACKER_HOME` selects the state directory. `PR_REVIEW_PYTHON` selects
the Python interpreter for background workers. Set these before starting the
server or generating its launchd configuration.

## Local data and privacy

State and review runs live under `~/.local/share/pr-review-tracker/`; generated
review files live separately from this Git repository. The
`PR_REVIEW_TRACKER_HOME` environment variable selects an alternate tracker
home, which is useful for isolated testing. Use the provided commands instead
of editing registry JSON by hand.

The dashboard runs on your machine, but AI features send data off your machine:

- **GitHub sync:** reads PR information using your GitHub login. Author avatars
  normally load from GitHub.
- **AI features:** send PR descriptions, code/diffs, and your questions to the
  selected AI provider as needed. Review load estimates also send descriptions and
  patches. Only enable these features for repositories you are allowed to share
  with that provider.
- **Saved copies:** review reports, downloaded source, notes, and chat data can
  remain in the tracker directory. Persistent AI conversations also use
  provider-managed history outside that directory. Deleting tracker files does not
  delete provider history or copies retained by a provider; manage those separately
  through the relevant product's data controls.

The server listens only on your machine's loopback interface. Treat generated
reports and screenshots as potentially containing private code and review data.

Dashboard GitHub operations are read-only: they do not post comments, approve,
or merge PRs. The skill uses isolated checkouts and runs PR code in a sandbox.
Checks the sandbox blocks run on your Mac only for repositories you list under
Settings, Repositories, **Run blocked checks outside the sandbox**; they use a
throwaway copy and a clean environment but can read your files and use the
network, and reports label them. Runtime history and generated review artifacts are not included
in this repository. Keep those out of commits and screenshots.

## In-app AI reviews

Selecting Codex or Claude Code runs AI reviews in a background worker and opens live activity
in the dashboard. Stage progress follows reviewer checkpoints; it is an estimate,
not time remaining. Reviews keep running across page reloads and server restarts.
While a review runs, the activity panel accepts questions and steering, such as
"what is going on?" or "skip the example app"; the lead answers in the agent
updates. Wrap up now asks the lead to stop new checks, mark unfinished stages
blocked, and build the report from the evidence gathered so far; the result is
labeled Finished with gaps. Stop review cancels the worker and preserves its saved
activity. When a review finishes, the panel, the PR card and the run history show
its estimated cost, and **Cost breakdown** lists tokens and cost per model.
Finished review sessions do not accept follow-ups; the code workspace
has a separate persistent chat for code questions.

Install `requirements-triage.txt` into the server's Python environment for Codex
reviews. See [dashboard operations](../references/dashboard.md#in-app-ai-reviews)
for isolated state, progress reporting, and validation.

## Code review workspace

**Open review** opens a workspace with AI review and Code changes tabs. Explore
unified or side-by-side diffs, expand context, open full files, and save viewed
progress. Checking for new commits resets viewed status only for changed file
comparisons. Private notes and revision-labeled conversations are saved locally.

Select lines to focus a question, then let the selected AI investigate beyond it.
Each conversation pins its provider, model, reasoning and PR revision. Follow-ups
resume the same native session; switching providers requires a new conversation.
Both providers can read source, inspect the pinned base version, search the web,
and read GitHub through a fixed read-only tool: issues and PRs with comments, issue
search, and files at any ref, in any repository your `gh` login can read. Local
reads are limited to the checkout and the PR's AI review files. Codex runs shell
commands in its sandbox without network access, token-like environment variables or
approval requests. Claude uses a restricted read/web tool set plus bounded
Git/GitHub read tools; shell, edits, hooks and imported MCP servers are disabled.
Private notes remain local by default. When you explicitly select notes or Ask AI
conversations in the guided review dialog, the selected content is sent as quoted
context to the configured AI provider and retained in that review's local run
history. Streamed answers, public activity and source links appear in the
conversation.

GitHub review threads appear under the lines they discuss, and **Comments** lists
every thread plus the general PR conversation. Show all, only unresolved, or no
comments inline, and hide bot comments. **Ask AI** attaches a comment to the chat;
**Draft reply** checks whether the current code addresses it and drafts a reply
for you to copy. Nothing is posted to GitHub.

Finished HTML reviews stay in the dashboard; completion does not open an external
browser. See [workspace architecture, limits and tests](../references/code-workspace.md).

