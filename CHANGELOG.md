# Changelog

Notable changes to the PR review dashboard and skill, newest first. Each pull
request gets its own section with the day it merged; changes that went to `main`
without a pull request are grouped by day.

## #22 · Snooze in My reviews (unreleased)

- **Snooze** (1 day, 3 days, 1 week) on PRs in Up next and In progress sets
  them aside in a new **Snoozed** section. They come back to you when the
  snooze ends, or sooner on new commits, replies, mentions or a review
  re-request.
- A snoozed review in progress continues from the commit it started at.

## #21 · Explain why a PR exists before what it changes · 2026-10-17

- Review reports are one scrolling page: a sourced "Why this PR exists" lead,
  the outcome, At a glance with findings and rare "Needs your judgment"
  questions, a background with a where-it-sits map for unfamiliar repositories,
  the change with a visual that fits its kind, key code inline and the blast
  radius.
- **Settings → AI settings → Repositories I know well**: listed repositories
  skip introductory background in their reports.
- **In-depth explanation** checkbox in **Run with guidance…** for a Deep
  explainer.
- Fixed: code-walk file badges come from Git, so unchanged context files are no
  longer shown as changed or new.
- Fixed: wrapped Mermaid labels keep the space between words for screen readers
  and search.
- Fixed: an earlier review's verdict no longer reads like the current one.

## #20 · Review context selection and inbox filter presets · 2026-10-16

- Guided reviews can include selected private notes or Ask AI conversations.
- Inbox filter presets.

## 2026-10-10 · no pull request

- Claude Haiku 5.5 is offered and is the default Claude triage model.

## #19 · On-behalf footer for draft comments · 2026-10-06

- Draft review comments end with an on-behalf footer.

## #18 · Reports rendered outside the Codex sandbox · 2026-10-06

- AI review reports are rendered and checked outside the Codex sandbox.

## #17 · Review workspace polish · 2026-10-05

- Loading progress, a scroll-synced file list and clearer chat questions.

## #16 · Row actions fit · 2026-10-05

- Row actions stack so the repository name and PR number fit.

## 2026-10-02 · no pull request

- The review load badge no longer overlaps the AI review column.

## #15 · Review load, list view and walk reports · 2026-10-01

- Review load estimates, a list view and walk-style review reports.

## #14 · Cancelled reviews stop their checks · 2026-10-01

- Cancelling a review stops the check command it is running.

## #13 · More PR checks run locally · 2026-09-30

- Sandbox presets, a fetch step and trusted host runs.

## #12 · GPT-6.1 Sol for Codex · 2026-09-30

- GPT-6.1 Sol is offered for Codex and used for Codex Chat.

## #11 · AI review cost · 2026-09-30

- Each AI review shows what it cost.

## #10 · Approval verdict · 2026-09-30

- AI reviews open with an approval verdict.

## #9 · Faster GitHub sync · 2026-09-30

- GitHub sync is faster; GPT-6 Sol and Luna work in Codex.

## #8 · GPT-6 Codex models · 2026-09-29

- GPT-6 Codex models are offered; security reviewers stay at the lead
  reviewer's tier.

## #7 · Sonnet 5.5 for Claude Code · 2026-09-29

- Sonnet 5.5 replaces Sonnet 5.

## #6 · Update an AI review · 2026-09-29

- After small follow-up commits, update a review instead of redoing it.

## #5 · Cleanup no longer blocked · 2026-09-28

- Abandoned review runs no longer block storage cleanup.

## #4 · Hardened workspace chat · 2026-09-25

- Hardened Codex workspace chat and wider GitHub reads for both chats.

## #3 · PR discussion and storage cleanup · 2026-09-25

- Reviews read the PR discussion first; storage cleanup; chats point at the
  review.

## #2 · Continue a review in an agent · 2026-09-25

- Continue a finished AI review in Claude Code or Codex.

## #1 · Diagrams and step-by-step findings · 2026-09-25

- PR explanations with diagrams, and findings taught step by step.

## 2026-09-24 · no pull request

- Ask, steer and wrap up a running AI review.
- The dashboard restores instantly when going back from the workspace.
