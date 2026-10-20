# Screenshot provenance and refresh

Captured September 24, 2026 from the production dashboard assets and bundled
report renderer at commit `a924abf`. The three `review-*` report images were
refreshed September 25, 2026 with the renderer in the commit that added
`review-explainer-light.jpg`. `reporting-cost-light.jpg` was added September 30,
2026 with the commit that added AI review cost. The three `review-*` images and
`ai-settings-light.jpg` were refreshed October 17, 2026 for the paper report
layout and the Repositories I know well setting. `my-reviews-light.jpg` was
refreshed October 20, 2026 for snoozing in My reviews. Headless Chrome, light/dark system themes,
1440 × 1050 CSS-pixel viewports (1250 high for live review), JPEG quality 88.

| Image | What it shows | Synthetic source |
|---|---|---|
| `inbox-light.jpg` | Effort estimates, My reviews actions and Open review | `workspace_browser_fixture.py`, with fictional titles and authors supplied by the capture script |
| `my-reviews-light.jpg` | Queue grouped by turn, with update and move reasons and snooze controls | `my_reviews_browser_fixture.py` |
| `code-workspace-light.jpg` | Pinned code diff, inline review thread and Comments rail | `workspace_integration_fixture.py` |
| `live-review-light.jpg` | Stage progress, a question and simulated reply, wrap-up and stop controls | `codex_browser_fixture.py` |
| `ai-settings-light.jpg` | Independent Triage, AI review and Chat profiles, and Repositories I know well | `workspace_browser_fixture.py` |
| `reporting-dark.jpg` | Daily activity, workday trend lines and a selected day's PRs | `workspace_browser_fixture.py` |
| `reporting-cost-light.jpg` | 30-day AI review cost, a day's provider split, cost by model and the costliest reviews | `workspace_browser_fixture.py` |
| `review-overview-light.jpg` | Why this PR exists, current assessment, outcome and At a glance | `readme_report_fixture.py` |
| `review-explainer-light.jpg` | The change: approach note, before/after diagrams and a situation grid with finding badges | `readme_report_fixture.py` |
| `review-findings-light.jpg` | One finding expanded with its walkthrough, fix sketch and copyable draft | `readme_report_fixture.py` |

All fixtures live in `tests/fixtures/`. Every displayed PR, repository, person,
activity event, AI cost and private note is fictional. The browser blocks external requests;
avatars use the UI's initials fallback. Fixtures use temporary tracker homes and
mock GitHub/AI boundaries. No live inbox, credentials, model calls or GitHub data
are used. Settings show the repository's presets, not verified account entitlements.

The report is rendered from a temporary synthetic Git repository containing only
`parser.py`. Its examples are source-traced, not runtime-tested. The live-review
reply is simulated. Images capture the real UI; controls and text are not composited.

## Refresh

Install the [browser-check dependencies](../../README.md#development-and-recovery),
then run from the repository root:

```sh
node scripts/capture_readme.cjs
```

The command replaces the ten images here. To preview in another directory:

```sh
node scripts/capture_readme.cjs /tmp/pr-review-readme-preview
```

`PYTHON`, `PR_REVIEW_PLAYWRIGHT_MODULE` and `PR_REVIEW_BROWSER_CHANNEL` select the
interpreter, Playwright module and browser channel. Chrome is the default.
The script starts disposable loopback servers and cleans them up afterward;
run where local server binding and headless browser startup are permitted.
Generated HTML and synthetic Git/tracker state stay outside the repository.

Inspect every image for clipping, stale labels and accidental private content
before committing. Update the capture date, source commit and README captions
together. Do not capture the live inbox and redact it afterward.
