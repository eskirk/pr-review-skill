# Local PR inbox

Open `http://127.0.0.1:8765/`, or run:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_dashboard.py open
```

The optional launchd job `com.pr-review.dashboard-server` runs `pr_server.py`.
The current HTML/CSS/JavaScript shell is in `assets/dashboard.*`. The page
reads local tracker state through `/api/state`, including newly registered
artifacts. Saved personal reviews are refreshed on opening/refocusing the page
and every five minutes while it is visible; retention runs after successful background GitHub checks.

## Automatic startup on macOS

From the repository root, generate a service configuration using the Python
environment that will run the server. For AI features, install
`requirements-triage.txt` in that environment first.

```sh
mkdir -p "$HOME/Library/LaunchAgents" "${PR_REVIEW_TRACKER_HOME:-$HOME/.local/share/pr-review-tracker}"
python3 scripts/render_launchd.py > "$HOME/Library/LaunchAgents/com.pr-review.dashboard-server.plist"
plutil -lint "$HOME/Library/LaunchAgents/com.pr-review.dashboard-server.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.pr-review.dashboard-server.plist"
```

Use `.venv/bin/python` in place of `python3` if that is your server environment,
or select an interpreter with `--python` / `PR_REVIEW_PYTHON`. The generator
records absolute installation, state, log, and checkout-discovery paths. Set
`PR_REVIEW_TRACKER_HOME` and `PR_REVIEW_LOCAL_DEV_ROOT` before generating to
customize them. It carries the current `PATH` but does not copy API keys or the
rest of your environment into the plist. Regenerate and reload the service
after changing these values or moving the installation.

For an existing service, use `--label` with its installed label and write to
the matching plist filename. Unload that service with `launchctl bootout`
before replacing its plist, then bootstrap it again. Do not install a second
service alongside a running one on the same port. Keep generated plists local;
they contain paths from your machine. The generator itself does not install,
start, stop, or modify any service.

## Workspace navigation

My reviews, Inbox, Your PRs and Reporting are the main views. Inbox groups
Requested, Watching, Snoozed and Hidden. Filters opens a drawer; active filters
remain visible above the list. Inbox, Your PRs and every My reviews section are
tables with one row per PR: the PR (repository and number, title, author avatar and
username), its size (+additions −deletions, files), review load, AI review and when
it was updated (My reviews shows a Status column instead, see below). The row ends
with the primary action, **Open review** (the code/report workspace) and a **•••**
menu. **••• → AI tools** can start a first AI review or rerun existing notes in
both Inbox and My reviews. Tab counts show “5 of 47” when filters hide PRs.

Clicking a row (or Enter on a focused row) opens the side panel with the PR's full
card: review load details, update suggestion, AI review progress and run history.
It stays in sync with the list and keeps open sections while the page refreshes.
The AI review cell shows live progress (status, percent, current step, **Live ↗**)
while a review runs, otherwise the AI review state, verdict and cost, plus
**Update AI review** when an update of an older report is suggested. Wide tables
scroll sideways on narrow screens.

PR sizes come from GitHub sync (`additions`, `deletions`, `changedFiles`) and from
the My reviews check; PRs saved before sizes were recorded get one detailed fetch.
A size shows “–” until then.

Settings is a persistent drawer with Review agent, Review load estimates, Repositories
and Appearance sections. AI activity contains running reviews and estimate progress.

**Sync GitHub** updates inbox discovery, saved reviews and reporting history.
Open the adjacent sync status for each source's last successful update and errors.
Sources can fail independently; cached data remains available. Background checks of
saved reviews do not disable Sync; clicking Sync during one runs one more pass after it.
Sync does not rerun
completed AI reviews or estimates. Enabled initial estimates can start after discovery.
The page polls cached state and reporting every five seconds; polling does not fetch
GitHub history or run models. Existing automatic saved-review checks still apply.

## Triage and freshness

Requested from you includes direct reviewer requests and assignments.
Watching includes open PRs from watched repositories. Your PRs includes
your authored PRs. Hidden PRs can be restored. Last-used filters and named inbox
presets are saved in the browser, independently from the registry. Setting a
default does not change the current filters; **Reset to default** applies it
explicitly. Reporting repository filters are not part of inbox presets. Legacy
star filters are ignored.
Rows emphasize the PR title with repository and PR number above it. The side
panel shows age since GitHub creation alongside recent activity. Missing opening
dates show “Age unknown” until a GitHub refresh; first-seen time is never used as
PR age. Secondary actions appear in the ••• menu beside each row's primary action.

GitHub participation distinguishes comments, approvals, requested changes,
and dismissed reviews. It is not inferred from an AI run finishing. Legacy
participation needs a GitHub refresh to classify. Artifact dates and commit
IDs remain visible; the dashboard flags results from different runs. The combined
review notes link has a **New** badge until that version is opened
from the dashboard, and an independent **Older commit** badge when its pinned
head differs from the last fetched PR head. A visible warning names the affected
results and explains that parts may no longer apply. Missing commit metadata
shows **Commit unverified**. Freshness uses the last fetched GitHub head, not a
new live check. The badges and result links also appear directly in My reviews.

Opened versions are saved per run in `artifact-views.json`, shared across tabs
and browsers. Legacy artifacts keep independent opened states; replacing a result
marks the new version unread, including re-registration at the same file path.
Existing artifacts initially appear unread because earlier opens were not
recorded. The **New unopened AI results** status filter finds unread results.
Normal, keyboard, modifier and middle-click opens acknowledge only the version
displayed through authenticated JSON POST `/artifact-opened`; merely polling or
fetching an artifact does not mark it read. Open status does not acknowledge
GitHub updates in My reviews or change the human review stage.

Artifact dates use registration time. New registrations pin the current run's
base/head SHAs and receive a distinct version ID; legacy artifacts use the run
revision and a stable metadata identity. The combined HTML becomes ready when
its report task completes. Legacy explanation/Markdown artifacts retain their
previous explainer/drafts readiness rules. Until a replacement is ready, previous completed results remain available.

Refresh GitHub fetches sources and PR details with bounded concurrency. It
runs in the background when started from the page. PR details are reused for up
to an hour while the search result's `updatedAt` matches the last detail fetch. Incomplete or failed
sources preserve their existing entries and leave visible warnings. Local
rerenders do not advance GitHub freshness. Searches currently cap at 100
results per source; hitting that cap is visible and prevents absence-based
removal. The dashboard does not claim to have fetched beyond the cap.

Inbox discovery does not delete artifacts. The accompanying personal-history
refresh applies the 7-day retention policy below. Tracker CLI retention remains
available as described in SKILL.md. Dashboard state/config transactions are serialized across CLI and
HTTP callers; a refresh merges fetched data into current local preferences.

## Snooze

Snooze an inbox PR for **1 day**, **2 days**, or **1 week** (24/48/168 hours).
The Snoozed view shows its return time and **Bring back now**; snoozing offers
Undo. Hide remains indefinite, and hiding/restoring clears a snooze. Snooze
only affects inbox discovery views; saved commitments in My reviews remain.

The deadline persists in `dashboard.json` as `snoozed_until`. On expiry, the
visible dashboard requests a GitHub refresh, retrying at most every five minutes.
An observed open PR returns to its current source view. Closed/merged PRs drop
out through normal discovery refresh; incomplete sources retain snoozed entries
until an open result confirms they can return. The page shows expired entries
as awaiting a GitHub check. A page opened after expiry checks then; no scheduled
job or notification is created. Refresh merges current preferences so a new
snooze applied during a fetch is preserved.

Authenticated JSON POST `/snooze` takes `url` and `days` (1, 2, or 7);
`/unsnooze` takes `url`. Both preserve GitHub freshness and review artifacts.

## My reviews

**My reviews** is a durable personal queue across repositories, independent of
Requested/Watching membership and their filters. Use **Add to Up next** on an
inbox row or paste a GitHub PR URL, including a PR outside watched repositories.
Starting an AI review also saves an untracked PR in Up next; AI completion never
completes the human review.

The page groups sections by whose turn it is: **Your turn** (In progress, Back
to you, Up next), **Their turn** (Waiting for author) and **Finished** (Merged or
closed, Stopped tracking). Stages map to sections as `reviewing` → In progress,
`waiting` with reasons → Back to you (bucket `attention`), `up_next`, `waiting`,
closed → Merged or closed, and `removed` → Stopped tracking.

- Every section collapses via its heading, with its count always visible, and
  remembers its state per browser. Back to you highlights its count and marks its
  rows with ●.
- Each section is a table like the Inbox, with a Status column: why the PR is in
  this section, a due reminder, links to what is new and sync errors. Your private
  note shows under the title. Row buttons: In progress: Open review, **Hand back to
  author**; Back to you: Open review, **Continue review**; Up next: ↑, Open review,
  **Start review**; Waiting: Remind me, Open review, Review now; Stopped tracking:
  Track again, Open review. **Pause**, **Mark updates seen** and **Keep waiting**
  are in •••. The side panel repeats the row's actions with the full context.
- **Up next** rows are numbered in queue order; only the first has a primary
  Start review button. Move up swaps with the previous PR.
- **Start review** (Review now, Continue review) records the displayed commit
  and activity observation. **Hand back to author** acknowledges that
  observation, so commits or replies arriving during the review remain pending
  and the PR goes straight to Back to you; its confirmation says so.
- Continuing from Back to you does not acknowledge pending updates. They show as
  "New since you started" until **Mark updates seen** or Hand back to author.
- **Pause** returns the PR to the top of Up next without acknowledging updates
  or cancelling an AI run. Starting again records a fresh review observation.
- **Back to you** shows head changes, human replies in review threads you
  participated in, author comments after your feedback, mentions, direct review
  re-requests and due reminders. Links open the relevant conversation or
  comparison. Opening a PR does not acknowledge its updates. **Keep waiting**
  acknowledges only the observation displayed in that browser and clears a due
  reminder.
- **Remind me** (1, 3 or 7 days) is available while waiting. A due reminder moves
  the PR to Back to you on the next page render; starting, handing back, pausing
  or stopping tracking clears it. The dashboard does not notify while closed.
- **Stop tracking** (in •••) moves an open PR to Stopped tracking, where
  **Track again** returns it to Up next. Closed PRs appear in Merged or closed.
- GitHub sync automatically moves confirmed closed/merged PRs to **Merged or
  closed**. Reopened tracked PRs return to their active stage.
- Every record stores `moved: {kind, at}` for the latest move (`added`,
  `recovered`, `discovered`, `started`, `resumed`, `paused`, `handed_back`,
  `github_review`, `kept_waiting`, `removed`, `restored`). The UI shows it as
  "why it is here". Stage moves return an undo token restoring stage,
  acknowledgment, position, reminder and move reason; a newer choice
  invalidates it.
- Every move shows a toast with **Show** (open section, scroll, highlight) and
  **Undo** where available. Section changes not made in the current tab, from
  GitHub sync, reminders or other tabs, are announced with Show.
- **Find a tracked PR** filters every tracked PR by title, repository, number,
  author or note, labelled with its section.
- Add a private note to retain context or where you stopped. It stays local.

GitHub sync automatically discovers PRs you commented on or submitted a review for,
including approvals and requested changes, using paginated `commenter` and
`reviewed-by` GitHub searches. Requests, mentions and AI runs alone do not count.
Open participated PRs enter Waiting for author unless already tracked or stopped.
Only closed/merged PRs appear in Merged or closed, newest GitHub update first.
Discovery never starts an AI review. Legacy done/history stages become waiting
without acknowledging any unseen changes. The retired done action routes to wait. Search failures preserve existing data; the GitHub
1,000-result limit is reported rather than silently truncating history.

Closed/merged PR entries expire 7 days after their actual GitHub `closedAt` or
`mergedAt`, not their latest comment, first discovery or sync date. Their review
runs expire on the same schedule through `storage_cleanup.py` (see
[Tracking](tracking.md)), which also covers runs of PRs that are not in the inbox.
Reporting keeps its own activity history. Open PRs remain.
Expiration runs after successful observations during the visible page's automatic
refresh and Sync GitHub. Reopened PRs are kept. Failed checks never authorize
cleanup. `dashboard_retention.py` removes the personal entry, workflow-owned
reports/runs, workspace diffs, code checkouts, notes/chats and effort metadata.
Active reviews, chats, estimates and cleanup failures defer deletion with a visible
error. A review counts as active while its dashboard worker runs or while its tasks
were updated in the last six hours; an abandoned run does not block cleanup. Checkout cleanup keeps the tracker's ownership and non-force rules;
unmanaged external files are never deleted. The workspace lock file is retained
for synchronization. Reporting maintains its independent activity window.

`dashboard_queue.py` owns `my-reviews.json`, separate from `dashboard.json` and
the run registry. It uses the existing dashboard lock and atomic writes. UI
actions carry a revision to prevent stale tabs/notes overwriting newer choices.
GitHub refresh merges observations into current personal preferences. Personal
records remain if discovery drops the PR or GitHub becomes inaccessible.

Follow-up refresh uses read-only, paginated GitHub CLI REST requests, with at
most eight PRs fetched concurrently. A batched GraphQL query first reads each open
PR's `updatedAt` and head commit; PRs unchanged since their last detailed fetch
are skipped, and each still gets a detailed fetch at least hourly. Closed PRs and
PRs with a failed check are always fetched. Adding or restoring a PR checks only
that PR, without starting a full refresh. It ignores your own replies, bot comments,
and unrelated thread/CI activity. A newly submitted GitHub review while Reviewing
moves the PR to Waiting at that review's commit, retaining later updates. Ordinary
comments do not automatically finish the review; use Hand back to author.

Every saved PR shows its last successful check and any error. Automatic refresh
checks open tracked PRs, including waiting items for replies and re-requests, while the page is
visible. Sync also checks closed entries for reopening before expiration.
Only a confirmed closed/merged status moves a PR to Merged or closed; an unavailable PR
stays saved. There are no notifications or checks while the page is closed.
The personal queue is bound to the first GitHub login that refreshes it; changing
accounts yields an explicit error instead of interpreting another user's activity.

New authenticated JSON POST actions: `/queue` (enqueue/start/wait/acknowledge/
done/remove/restore/undo/note/move_up), `/refresh-queue` (optionally `urls` to
check up to 50 saved PRs only), and `/recover-reviews`.
The page and `/api/state` include `assets/queue.js`, workflow observations,
participation history, and queue refresh status. Do not edit the JSON by hand.

Validate changes with `test_queue` plus the existing dashboard, launch, reporting,
and notes suites. Browser checks must use disposable tracker data; cover capture,
waiting, notes, removal/Undo, reload, navigation, and 320px/390px layouts.

## Starting and following a review

The review buttons create a tracker run before starting the agent, then pass
that exact ID to the agent. Reuse it. The tracker ID is the launch identity;
never attach whichever unrelated run happens to finish next.

**Run with guidance…** opens a dialog for optional steering text (up to 2,000
characters). The dialog also offers individual private notes and whole Ask AI
conversations as optional quoted context. `/regenerate-review` accepts the
steering text as `guidance` and selected source IDs as `workspace_context`; the
server resolves the local sources and appends their displayed text after the
reviewer guidance. Only conversation prompts and completed assistant responses
are included; drafts and tool activity are omitted. Selected context is stored
in the local run prompt and source IDs/counts are recorded in launch metadata.
It never overrides the no-publishing and secret-handling rules, and
the report must state which checks the guidance skipped. Plain launches send no
guidance or private context.

When a finished report covers an older commit, the card and the workspace AI
review tab offer **Update AI review** beside **Run full AI review**.
`/regenerate-review` accepts `mode: update`. Before launching, fixed rules
check (with the GitHub compare API) that the previous head is an ancestor of
the new head, the comparison merge base is unchanged, the new commits change at
most 500 lines in 20 files, and fewer than three updates ran since the last full
review. A failed rule rejects the update with its reason; no model can override
it. An accepted launch writes `update-context.json` to the new run (previous
run, revisions, commits, changed files and any matching pre-check), records
`mode`, `previous_run` and `update_chain` in its launch metadata, and registers
the `previous-findings` task. A full review of a PR with an earlier finished
report also receives `update-context.json` (`mode: full`) so the report can say
what happened to each previous finding. See
[Updating a previous review](update-review.md) for the review itself.

**Copy review prompt** is available beside the
launch actions and in My reviews → Review tools. They copy the same workflow
prompt for pasting into any agent session, without opening Terminal, creating
a tracker run, or applying the saved agent settings. The receiving agent
registers its run and artifacts when it starts. If clipboard access fails, a
dialog shows selected prompt text for manual copying. `/copy-prompt` validates
the PR URL and prompt kind and returns the prompt without changing local state.

The review launch action uses the saved agent settings and the entire
pr-review workflow. Register one combined HTML as `review-html`; only completed
`report` tasks surface as finished notes. Historical Markdown and explanation
artifacts remain accessible in run history. Requests from an old explainer button
or copied-prompt client now route to the full review.

The prompt prefers a verified local clone under `PR_REVIEW_LOCAL_DEV_ROOT`
(default `~/Development`), using an isolated worktree. Follow the
existing checkout and verification sandbox instructions.

Settings → **AI settings** configures Triage, AI review and Chat independently.
Each feature remembers provider-specific model/reasoning profiles. Codex and
Claude Code are available for every feature; the existing OpenAI API option is
available for triage. Providers can be mixed. There is no automatic fallback.
Model default leaves the override unset. Changing models resets unsupported
reasoning; existing custom values remain visible until changed.

Maintain presets and feature defaults in `scripts/agent_options.py` when models
are released. The dashboard never queries providers for its dropdowns. Triage
uses GPT-6 Luna or Claude Haiku 5.5 by default; Claude Haiku 4.5 has no reasoning override.
The UI saves all features atomically through POST `/ai-config`, guarded by a
revision hash so stale windows cannot overwrite newer settings. Existing settings
are migrated in memory and persisted only on explicit save. Reports, estimates
and conversation history remain available. Conversations pin their provider,
model and reasoning; new conversations use the current Chat selection.
These overrides do not change global agent configuration.

These settings configure the lead session. The skill's
[reviewer allocation policy](reviewer-allocation.md) lets that session assess
the PR and select supported model/effort overrides for subagents, subject to
explicit user constraints. Hosts without those controls inherit the session
settings; the report records the limitation. No dashboard setting is rewritten
by this allocation.

Eligible Codex escalations go through automatic approval review; this does
not guarantee every request succeeds. PR code still requires the isolated
verification environment specified by the skill.

A second launch for an active PR returns the existing run. The shared worker
tracks liveness, public activity and cancellation for both providers. Earlier
artifacts remain available during a retry. Historical Terminal runs remain
readable; releasing their tracking does not terminate an old external process.
The dashboard does not launch Terminal sessions.

## Local state and endpoints

State lives under `~/.local/share/pr-review-tracker/`; use
`PR_REVIEW_TRACKER_HOME` for isolated tests. Do not edit registry JSON manually.
`dashboard_runtime.py` owns artifact selection and durable launch metadata;
`pr_review_tracker.py` remains the owner of review runs/tasks/artifacts.

GET serves the page, assets, `/api/state`, `/status?url=...`, and artifact
views. Mutations require JSON POST, the expected Host and Origin, and the
server's CSRF token. Do not invent GET mutation links in generated artifacts.
HTML artifacts are served in an opaque-origin CSP sandbox; their scripts can
run but cannot read or mutate dashboard state. Valid local artifact links are
rewritten to the artifact viewer. Markdown uses the existing sanitized renderer.

CLI configuration and triage commands remain available:

```shell
python3 ~/.agents/skills/pr-review/scripts/pr_dashboard.py refresh
python3 ~/.agents/skills/pr-review/scripts/pr_dashboard.py set-config --agent codex --model '' --effort ''
python3 ~/.agents/skills/pr-review/scripts/pr_dashboard.py add-repo owner/repo
python3 ~/.agents/skills/pr-review/scripts/pr_dashboard.py remove-repo owner/repo
python3 ~/.agents/skills/pr-review/scripts/pr_dashboard.py hide 'https://github.com/owner/repo/pull/1'
```

Use `unhide` to restore a hidden PR.
Adding/removing a watched repository updates settings immediately; refresh
GitHub to update its PR membership.
Repositories under **Run blocked checks outside the sandbox** are stored as
`host_execution_repos` (`owner/repo` or `owner/*`). `verification_sandbox.py
--host` reads this list itself and refuses any other repository; see
[trusted host execution](validation.md#trusted-host-execution).

When changing server Python modules, restart the launchd job after validation.
Asset-only changes are picked up on page reload. Validate with the
`test_artifact_state`, `test_snooze`, `test_dashboard`, `test_dashboard_launch`, and `test_review_notes` unittest
modules using `python3 tests/run.py python <module> ...` from the repository root,
plus browser interaction and responsive checks. HTTP tests use a
random loopback port and disposable data; never point test mutations at the
live tracker.
`node tests/browser/test_inbox_review_browser.cjs` checks first launches, reruns,
active-run disabling, failure recovery, and desktop/mobile controls with
synthetic state and intercepted AI launch requests.


## Reporting

The Reporting view shows submitted GitHub reviews of other authors' PRs and merged PRs authored by the authenticated user. It covers four complete Monday–Sunday weeks plus the current week. Days use Europe/Berlin, including daylight-saving transitions. Repeated reviews count once per PR per displayed day or week; daily counts need not sum to weekly distinct-PR totals. Comment-only submitted reviews count; pending reviews, ordinary comments and AI runs do not. Merge activity uses mergedAt, regardless of who merged the PR.

`dashboard_reporting.py` fetches history read-only through the existing GitHub CLI, paginates searches and review histories, and writes a complete snapshot to `reporting.json` under the tracker root. Search updatedAt is only a candidate-discovery bound; review dates come from submittedAt. An incomplete/failed fetch keeps the previous cache. A search exceeding GitHub's 1,000-result cap is reported as an error rather than silently truncated. Sync GitHub starts history refresh via the authenticated `/refresh-reporting` action; `/api/reporting` reads cached data. Loading Reporting does not run AI reviews. Missing days in an old snapshot are not rendered as zero activity.

Reporting has independent repository include/exclude selections. Inbox hiding, authors, statuses and repository filters do not change Reporting totals. Current-week data is marked in progress; comparisons use completed weeks. Click a chart period for linked PR titles, or Yesterday for the daily recap.

Daily charts overlay a separate trailing average for reviews and merges, using 10 complete workdays by default or 5 from the Activity trend selector. Each daily distinct-PR count is one observation; zero weekdays count. Saturdays, Sundays and inclusive date ranges marked as Time off are excluded from both the numerator and denominator. Their raw activity remains in bars and weekly counts. The line holds its last value across excluded days and starts only after a full window is available within cached history. No history before `range_start` or after `range_end` is assumed. Today and `range_end` are excluded because the final cached day may still be incomplete, including after the calendar advances. Repository filters apply before calculating the averages. Weekly charts retain distinct-PR totals without an average overlay.

The window and time-off ranges are stored under `pr-inbox-reporting` in browser local storage. Overlapping ranges are merged; invalid saved dates are ignored. Preferences apply across repository selections and do not modify the GitHub cache. Storage failures are visible and leave preferences applied only for the current session. Asset changes take effect on reload without restarting the server.

### AI review cost

Every finished in-app review is priced from the provider's own accounting. Claude Code reports `total_cost_usd` and per-model `modelUsage` in its final SDK result, covering the lead, subagents and helper calls; the same totals are in the transcript's `cost-state` record. Codex reports `estimatedUsageUsdMicros` per thread through `account/usage/read`; sub-agents run in their own threads, so `ai_cost.py` adds up the lead thread and every `subAgentActivity` thread beneath it. Both are API-price estimates, not bills.

`ai_cost.py` stores one entry per run in `ai-costs.json` under the tracker root, with the PR, provider, models and dollar amount. The ledger is kept for 120 days, independent of run cleanup. Runs without an entry, such as those finished before cost tracking or Codex runs not yet priced, are filled in when the server starts and after each reporting refresh. That covers runs from the last 45 days, and a failed lookup is retried after an hour. For Claude runs, only the review's own process is counted, so a later resume of the session is not added.

A finished run's card, run history and activity panel show its estimated cost; the panel includes a per-model token breakdown. Reporting shows the last 30 days: the total, review count, average per review, daily cost split by provider, cost by model, and the most expensive reviews or the reviews of a selected day. The comparison with the previous 30 days appears once the ledger covers that whole window. The cost section follows the Reporting repository filter.

Validation: `python3 tests/run.py python test_ai_cost test_reporting test_dashboard test_dashboard_launch test_review_notes`, `node tests/javascript/test_reporting.cjs`, `node tests/javascript/test_workspace.cjs` and `node tests/browser/test_reporting_browser.cjs` from the repository root. Browser checks use a disposable local server and synthetic activity to cover trend windows, time off, persistence, repository filtering, chart drill-down, incomplete history, bar/line alignment and light/dark desktop and mobile layouts. Set `PR_REVIEW_PLAYWRIGHT_MODULE` to the installed Playwright module path when it is not available through normal Node resolution; `PR_REVIEW_BROWSER_CHANNEL` defaults to `chrome`.

## Review update pre-check

When automatic estimates are enabled, the same worker also checks PRs whose
finished AI review covers an older commit, after it finishes waiting effort
estimates. It first applies the fixed update rules above; when they fail it
records **Full review suggested** with the rule's reason and makes no model
call. When they pass it sends the new commits' patches (at most 12,000
characters per file and 60,000 in total), their titles, and the previous
report's finding titles, placements and section excerpt locations to the
triage model. The model returns a scope (update or full), a reason, per-finding
hints (likely addressed, affected, untouched), affected sections and up to
three hotspots. Oversized patches skip the model and leave the scope to the
review. Each check uses one call from the daily limit and is keyed by the
previous run and head, the new base/head and the triage settings; failures
retry after an hour. Results live under `updates` in `triage.json` and are
pruned when their PR leaves the inbox and active My reviews.

The side panel shows the recommendation with the matching button emphasised, and the row's AI review cell offers **Update AI review** unless the rules require a full review. The update
launch copies the pre-check into `update-context.json` for the review lead only.
It is advice: the review re-checks every previous finding either way, and its
reviewers never see it.

Rows with a finished report that recorded a verdict show it as a compact chip
(for example **✓ Approvable · high**), read from the report's
`review-verdict.json`. It is advisory, derived by the renderer from the report's
findings and coverage, and is hidden when the sidecar is missing, malformed or
for a different head.

## Review load

Review load estimates are separate from full AI review runs, GitHub participation,
severity and the human review queue. The side panel's card shows **Review load Low**, **Medium**,
**High**, or **Unsure** (stored as the `quick`, `moderate`, `involved` and
`uncertain` effort), with four small bars for its parts: change scope, required
context, conceptual complexity and review risk. Each part has a level and a one-line
reason. These estimate review work, not correctness or readiness to approve. The
idea follows maintainer-cockpit's review cognitive load. Hovering or focusing the
badge explains what it measures and shows the reason and the four levels; clicking
it opens Review load details with each part's reason. Use the Review load filter
or sort; the saved order in My reviews stays unchanged. An estimate for an older
commit or different settings has a dashed outline. Estimates made before the parts
existed show the word only. Review load details also contains provider/revision
details and optional feedback: About right, Took more effort, or Took less effort. Rate a handful of PRs after
normal reviews; a separate manual evaluation exercise is unnecessary.

A compact activity strip above the tabs appears during startup and estimation,
showing a spinner and processed PR count across inbox, My reviews and Reporting.
It disappears after successful completion. With automatic estimates enabled,
failures and interruptions remain as small notices; the daily-limit notice is
shown only when estimates are waiting. Retry estimates appears when work can
actually be retried. Details opens AI activity at the review load estimate progress.

AI activity retains the current PR and stage, progress bar, estimated/waiting totals,
UTC daily usage, last-run summary, failure details, and Estimate all waiting.
Counts cover eligible inbox and active My reviews PRs and ignore browser filters.
Uncertain counts as a completed assessment, not unfinished work. Duplicate starts
are rejected while a worker is starting or running. Updates use the normal
five-second state polling and do not cause additional model calls.

Install the optional runtime from the skill directory:

```shell
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-triage.txt
```

Settings → AI settings → Triage selects Codex, Claude Code or OpenAI API,
a model ID, automatic operation and a daily call limit. The shipped default is
off; enabling it authorizes sending bounded PR descriptions and patches to the
selected provider. Codex reuses the existing local login and runs through its
bundled runtime. Claude uses the installed CLI with tools disabled. OpenAI API requires OPENAI_API_KEY in
the **server process environment**, uses separate API billing and never reads a
key from dashboard JSON or the browser. There is no automatic provider fallback.
The SDK runs ephemeral, read-only classification with inherited MCP servers,
apps, shell tools, hooks and plugins disabled. PR text is untrusted input.

After GitHub refresh commits its metadata, `dashboard_triage.py` starts a
separate worker using the skill's `.venv/bin/python` when present. The worker
process survives an HTTP-server restart and a cross-process lock prevents
concurrent runs. Requested PRs are considered first, oldest first. Active My reviews
entries (Up next, Reviewing, and Waiting) are also eligible even when no longer
in the discovery inbox. When both sources contain a PR, the latest checked
metadata is used and current inbox hide/snooze preferences take precedence.
Drafts, hidden/snoozed PRs, authored PRs, closed PRs, and entries without verified
base/head revisions are skipped automatically. Personal history alone does not
qualify a PR. Browser-only filters do not control background triage.

Refresh GitHub and **Estimate all waiting** each start one serial worker that
continues through all eligible unestimated PRs, including newly eligible entries
observed during the run. A full GitHub refresh also checks for waiting work
after its personal-queue fetch completes, so slower My reviews updates are
included. It stops when caught up, the daily limit is reached,
settings change, or an estimate fails. Each PR is attempted at most once per run.
Completed estimates, including Uncertain and outdated ones, are never rerun by
these actions. The legacy `batch_limit` setting/CLI flag remains accepted for
compatibility but no longer caps a run.

A daily limit of 30 model attempts (UTC) is the shipped default; failed calls
count. Settings can change the daily limit. For example:

```shell
python3 scripts/dashboard_triage.py configure --enabled true --provider codex --model gpt-6-luna --daily-limit 60
python3 scripts/dashboard_triage.py status
```

**Estimate review load** on an eligible card starts an initial estimate for just that
PR. It also permits an explicit draft estimate, while drafts remain excluded
from automatic runs. **Re-estimate** updates a completed estimate. Both actions
respect hidden/snoozed exclusions, saved provider settings, worker exclusivity,
and the daily limit. Newly pasted My reviews PRs need a successful Check for
updates to populate their verified revision metadata first.

Choose model IDs available to the selected provider. The Codex default is
`gpt-6-luna`; Claude defaults to Haiku 5.5. Switching to OpenAI API may require a different API model ID.
The worker stops its run on failure and backs off the same comparison for an
hour. There is no independent polling schedule: new PRs are discovered by
Refresh GitHub, not simply by the page's saved-state polling. A running batch
continues if the tab closes while the machine stays awake.

GitHub context uses paginated REST file metadata and patches. The initial
limits are 300 files, 24,000 characters per patch, 100,000 patch characters total,
and a 12,000-character description. Missing/binary patches, exceeded limits,
and incomplete inventories produce Uncertain without a model request. Generated
and lockfile paths are hints, never automatic exemptions. This first version
uses the supplied diff context; it does not clone repositories, run tests, or
retrieve arbitrary additional files. A model that needs more context returns
Uncertain only when that gap prevents judging the likely review effort. Missing
callers, upstream implementations, or validation results can remain context notes
alongside Quick, Moderate, or Involved; the estimate includes the work to inspect
those areas. The full review workflow remains available for that deeper work.

`dashboard_config.json` stores the canonical per-feature AI settings.
`triage.json` stores UTC usage counters and per-PR results under the
existing dashboard transaction lock. Never edit it manually. It contains no
raw descriptions or patches. Cache identity includes provider/model/reasoning, rubric
version, base/head revisions and a digest of title/body. GitHub is rechecked
before accepting results; local changes during a request also invalidate them.
Completed estimates keep their original effort, reason, and revision when the PR
or triage settings change. A dashed badge outline identifies these estimates;
filters and sorting still use their original effort. Refresh GitHub and Estimate
all waiting only schedule PRs without a completed estimate (including eligible
failed initial attempts), plus completed estimates made under an older rubric
version, which are re-estimated once while the old estimate stays visible (a failed
upgrade waits an hour, like a failed initial attempt). Other outdated estimates are
counted separately from waiting PRs. **Re-estimate** on a card processes only that PR, even when its estimate is
still current, using the saved provider and daily limit. Hidden/snoozed and other
ineligible PRs remain excluded. A busy worker prevents duplicate starts. The
previous estimate stays visible during a rerun and is retained on failure or
interruption; retrying that rerun is manual. Feedback is disabled for outdated
estimates. Freshness uses the last GitHub refresh; refresh before re-estimating
when new commits have arrived.
`/triage-config`, `/triage-run`, `/triage-reestimate`, and `/triage-feedback` require the existing
Host/Origin/CSRF-checked JSON POST. Feedback includes the displayed estimate ID
and cannot silently attach to a replacement estimate. Rated estimates remain in
the private feedback history when a newer estimate replaces the visible result.

Temporary working directories are removed after each provider call, including
handled failures and timeouts. No repository is checked out; patches travel in
memory through stdin. Codex requests ephemeral threads with history disabled.
A forcibly killed worker or machine crash can leave a temporary directory; this
path does not contain a checkout or saved diff. Shared SDK caches/logs are owned
by the SDK and are not deleted by dashboard retention.

Metadata is pruned on triage writes and GitHub refresh, including when AI triage
is disabled. Current inbox and active saved-review estimates are retained. Other
estimates expire 90 days after their last result, with at most 500 retained.
Calibration feedback expires after 180 days and is capped at 1,000 ratings; old
embedded feedback is removed too. Cleanup touches triage metadata only, never
full review reports, checkouts or private review notes. The installed `.venv`
and bundled SDK runtime are reusable dependencies, not per-PR copies.

Validate with `test_triage` plus the existing dashboard/queue suites. The
`node tests/browser/test_triage_browser.cjs` check starts an offline fixture with disposable state,
covering filters, sorting, feedback, settings, persistence, queue order, escaping
and light/dark 320px/390px/desktop layouts. It uses Playwright and installed Chrome
by default; PR_REVIEW_PLAYWRIGHT_MODULE and PR_REVIEW_BROWSER_CHANNEL override
those runtime choices. `evaluate_triage.py --output /tmp/triage-evaluation.json`
explicitly runs six small synthetic model examples. This uses provider quota;
it checks rubric behavior, not calibrated review times or broad model accuracy.

For an isolated UI session, run `python3 tests/fixtures/workspace_browser_fixture.py`
from the skill directory. Add `--report-failure` to exercise partial sync failures.
The fixture uses disposable state and blocks GitHub, provider and terminal work.

## In-app AI reviews

Reviews run in a detached Python worker through a shared provider interface.
Codex uses `openai-codex`; Claude uses the pinned JS Agent SDK with the installed
Claude Code executable. Install its dependencies with
`npm ci --prefix scripts/claude-runtime` (Node.js 22.16+).
Before the model starts, the worker saves the PR's review threads (with resolved
and outdated state), top-level comments and review summaries into the run as
`discussion.json` and `discussion.md`, using the same read-only queries as the
code workspace. A GitHub failure is noted in the activity and does not stop the
review; the skill then reads the discussion itself.
The review button opens a live activity panel with stage progress and cancellation.
Finished runs show their outcome and blocked/failed stage counts instead of a
percentage or progress bar. Stage details retain incomplete checks and their reasons.
Claude sessions stay connected when the lead finishes a turn while background
reviewers are running. Their completion notifications let the lead continue
through synthesis and report registration; progress watchers alone do not keep
a finished session open.
Reloading the page or restarting the dashboard reconnects to the saved run; it
never starts another model call. Session resume after a review ends and inline
answers to agent questions are not implemented yet. Unhandled input requests are
declined and surfaced as a blocker if the review cannot complete.

A running review accepts messages from the activity panel. POST `/review-message`
appends to the run's `review-inbox.jsonl`; the worker forwards each message once
the provider session can take it, then records it as a `you` event. Claude
receives it as streaming user input with a client uuid; the bridge keeps the
session open until a turn reports consuming that uuid, so a queued question is
not cut off by an earlier result. Codex receives it through `turn/steer` on the
active turn. Wrap up now sends a fixed instruction to stop new work, stop
background reviewers, mark unfinished tasks blocked and finish the report; the
worker then labels a complete report `completed-with-gaps`. Providers without
steering record an attention event instead. The stored prompt wrapper is never
shown in activity.

Codex uses workspace-write sandboxing and automatic approval review. Claude uses
its native auto permission mode, without bypass flags. Both retain
the skill's separate sandbox requirement for executing PR code, and passes the
selected lead model/effort. It explicitly reads the current skill checkout.
Reviewers report checkpoint counts through `set-task`; stage weights are a UI
estimate, not an ETA or coverage guarantee. Skipped validation is shown explicitly.
A successful finish requires settled tracker tasks and an existing `review-html`
in the run. A finished report with blocked or failed checks is labeled Finished
with the incomplete stage counts. Final outcomes replace the progress bar.

`dashboard_reviews.py` launches and supervises workers; `ai_runtime.py` defines
requests and callbacks, `provider_*.py` implement each runtime,
`review_context.py` supplies the shared prompt; `review_jobs.py` owns persistent state, locking,
activity and progress. Job metadata and events live in each run directory.
The worker records bounded agent messages and tool activity summaries, not raw command arguments, tool output or reasoning traces.
The UI escapes messages as plain text. The activity view shows the latest 100
saved events (with a bounded file-tail read); older events remain on disk.
Worker heartbeats and actual agent activity are separate. A missing worker is
reported as failed after a startup grace period. Retry cannot overlap an active
in-app worker. Stop first requests a provider interruption; after eight seconds the
worker can terminate its own dedicated process group. Partial artifacts and
checkout state are retained for inspection/normal tracker cleanup.

Same-origin GET `/api/review` returns saved state; `/api/review-events` streams
snapshots over SSE. POST `/review-cancel` uses the normal Origin/CSRF checks.
SSE disconnects do not stop the worker. The browser can safely replay snapshots
without duplicating activity. No provider keys or protocol sockets are exposed
to the browser.

For an isolated development instance, set `PR_REVIEW_TRACKER_HOME` to a separate
directory and start `scripts/pr_server.py --port 8877` with the Python interpreter containing
`requirements-triage.txt`. `PR_REVIEW_PYTHON` can explicitly select the worker
interpreter. Copy inbox/config metadata into the separate state directory if
wanted; select Codex in that instance's settings. Do not restart the normal
launchd service to try an isolated worktree.

Run `python3 tests/run.py python test_codex_review test_dashboard test_dashboard_launch`
from the repository root. `node tests/browser/test_codex_browser.cjs` uses a disposable synthetic
review to exercise live progress, reload/reconnect, questions, wrap-up, cancellation, escaped text,
and light/dark desktop/mobile layouts. Set `PR_REVIEW_PLAYWRIGHT_MODULE` when
Playwright is outside Node's normal module path. The fixture never calls a model.

## Code exploration and inline questions

See [the code workspace](code-workspace.md) for revision-pinned diffs, private
progress/notes, persistent inline chat, report embedding and focused tests.

## Claude runtime and T3 Code alignment

The integration follows T3 Code's
[ClaudeAdapter](https://github.com/pingdotgg/t3code/blob/main/apps/server/src/provider/Layers/ClaudeAdapter.ts)
and [ClaudeTextGeneration](https://github.com/pingdotgg/t3code/blob/main/apps/server/src/textGeneration/ClaudeTextGeneration.ts):
JS `@anthropic-ai/claude-agent-sdk` `query()` sessions, streaming user input,
`pathToClaudeCodeExecutable`, native session resume/interrupt, and the ordinary
HOME/environment/login. The SDK is pinned in `scripts/claude-runtime/package.json`
and its lockfile. No subscription token extraction or direct Anthropic HTTP calls
are involved. Triage runs the installed CLI with `-p --output-format json`,
`--json-schema`, empty tools, disabled slash commands/hooks, strict MCP config and
`dontAsk` permissions, matching T3's bounded text-generation approach.

Dashboard-specific restrictions are explicit: triage also disables session
persistence and settings sources; chat exposes read/web tools plus bounded Git
and GitHub reads instead of a general shell. Review sessions load ordinary
user/project/local settings. Interactive permission/input requests that native
automatic handling cannot resolve are declined and shown as blocked work.
`PR_REVIEW_CLAUDE` and `PR_REVIEW_NODE` can select executable paths when launchd's
PATH differs from the interactive shell.
