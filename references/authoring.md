# Authoring one review report

Write JSON as inert content. Explanation fields are plain text; use literal
code names in prose. Findings and verification use restricted Markdown. The
renderer owns HTML,
syntax highlighting, controls, escaping and source links. Choose sections and
block types that explain this particular change. Use `"layout": "paper"` for new
reports. Omitting `layout` still selects classic for older inputs.

```json
{
  "layout": "paper",
  "title": "A concrete behavioral title",
  "glance": {"kind": "logic", "blast": "contained", "blast_reason": "Only the changed path is affected."},
  "outcome": "The problem, changed behavior, and essential condition.",
  "mode": "Brief · Small",
  "stack": "Dart · OpenTelemetry SDK",
  "repository": "/absolute/path/to/verified/repository",
  "repo_url": "https://github.com/owner/repo",
  "pr_url": "https://github.com/owner/repo/pull/123",
  "base": "FULL_COMPARISON_BASE_SHA",
  "head": "FULL_REVIEWED_HEAD_SHA",
  "context": "Historical comparison, prepared YYYY-MM-DD. PR state checked separately.",
  "comment_attribution": {"tool": "Claude Code", "model": "claude-opus-5-5", "person": "Robert"},
  "sections": [
    {"id": "plain-words", "title": "In plain words", "claim": "In plain words", "blocks": [
      {"type": "paragraph", "text": "Who is affected, what used to happen, what happens now, and the condition that matters."}
    ]},
    {"id": "shape", "title": "How the decision is made", "claim": "How the decision is made", "blocks": [
      {"type": "diagram", "title": "Which driver a widget gets",
       "html": "<div class=\"dg-stack\"><div class=\"dg-node\">A widget builds</div><div class=\"dg-arrow\"></div><div class=\"dg-node dg-bad\">Custom binding: answers no <span class=\"dg-badge\">⚠ Finding 1</span></div></div>",
       "caption": "Source-traced from the pinned head. What to notice."}
    ]},
    {"id": "cases", "title": "What happens in each situation", "claim": "What happens in each situation", "blocks": [
      {"type": "cases", "columns": ["Situation", "Before", "After"], "caption": "Source-traced; row 2 reproduced.",
       "rows": [
         {"situation": "Normal widget test", "cells": [{"status": "works", "text": "test driver"}, {"status": "works", "text": "test driver"}]},
         {"situation": "Custom test binding", "finding": "Finding 1", "cells": [{"status": "works", "text": "test driver"}, {"status": "breaks", "text": "real driver"}]}
       ]}
    ]},
    {"id": "code", "title": "How it works", "claim": "How it works", "blocks": [
      {"type": "source", "path": "lib/example.dart", "side": "head", "start": 10, "end": 15,
       "caption": "Step 2 in the diagram: how this excerpt produces the result."}
    ]}
  ],
  "questions": [
    {"question": "Which outcome follows for a particular input?",
     "options": ["One plausible outcome", "A different plausible outcome"],
     "answer": 0, "explanation": "The condition in the source that decides it."}
  ],
  "references": [{"label": "Verified contract", "url": "https://official.example/spec"}],
  "review": {
    "base": "FULL_COMPARISON_BASE_SHA",
    "head": "FULL_REVIEWED_HEAD_SHA",
    "assessment": "No actionable defects found. Source reviewed; runtime was not exercised.",
    "verdict": {
      "complete": true, "traced": true, "tests": "pass", "runtime": "not-run",
      "runtime_note": "The retry timer was not exercised against a real receiver.",
      "unreviewed": [],
      "why": ["One function and its tests change; every exit path was traced."],
      "checked": ["Traced send → retry → drop at the pinned head", "Ran the transport tests: 142 passed"]
    },
    "markdown": "## Validation\n\nThe changed call path and test assertions were inspected at the pinned head."
  },
  "verification": "## Coverage and checks\n\nRecord the actual inspected files, checks, outcomes and gaps.",
  "attachments": [],
  "evidence": {
    "claims": [{"claim": "The main behavior", "source": "path and pinned lines", "check": "How it was verified"}],
    "examples": [{"input": "Exact toy data", "before": "Output", "after": "Output", "assumptions": "Relevant conditions", "check": "Source trace or independent evidence"}],
    "consistency_check": "Result of checking prose, diagram, captions and quiz together."
  }
}
```

For a review that builds on a previous one (see
[Updating a previous review](update-review.md)), add an `update` record and, in
update mode, `verified_at` on each carried section:

```json
{
  "update": {
    "scope": "update",
    "previous": {"run_id": "PREVIOUS_RUN_ID", "base": "FULL_COMPARISON_BASE_SHA", "head": "PREVIOUS_HEAD_SHA"},
    "summary": "The two new commits move the catch inside the loop and add a mixed-batch test.",
    "findings": [
      {"title": "One bad item empties the whole batch", "status": "resolved", "note": "Reproduced again; the batch now keeps A and C."},
      {"title": "Retries ignore the new timeout", "status": "new", "note": "Introduced by the retry change in abc1234."}
    ]
  },
  "sections": [
    {"id": "shape", "title": "How the decision is made", "verified_at": "PREVIOUS_HEAD_SHA", "blocks": []}
  ]
}
```

`scope` is `update` or `full`. An update keeps the previous comparison base and
covers a newer head; the renderer rejects anything else. `summary` is short
visible Markdown. Each finding status is `resolved`, `still-open`, `changed`,
`new` or `withdrawn`. The record renders as **Since the last review** after the
assessment and adds the previous head to the provenance. A section whose
`verified_at` is not the reviewed head shows that it was carried from the older
review; omit `verified_at` for sections re-derived at this head. Source excerpts
always render from the reviewed head, so re-anchor carried ranges first
(`scripts/review_update.py carry` does this).

`repository` is the verified local Git repository, inspected read-only. `base`
is the actual comparison base (usually the PR merge base), not a silently moving
branch name. `head` is the exact head SHA, or `working-tree` for uncommitted work.
If the target branch tip differs, retain it in `context`. Omit `pr_url` for
non-PR changes. For local-only commits omit `repo_url` if GitHub cannot resolve
them. Working-tree excerpts never receive a false commit permalink; label
uncommitted context clearly. Untracked files can be extracted but have no Git
added-line metadata; identify them in the caption.

`comment_attribution` adds one footer line to every draft comment, shown in the
report and included in the copied Markdown, for example
`*Posted by Claude Code (claude-opus-5-5) on Robert's behalf.*`. Use your actual
tool and model ID, never a guessed one; omit `model` when it is unknown. `person`
is the first name of the person the review is for (from `git config user.name`
unless they say otherwise). Dashboard reviews receive the exact values in the
launch prompt. Omit the field for no footer. Do not write the footer in the
drafts yourself; the validator rejects it.

The `review` object is required. Its `base` and `head` must exactly match the
explanation revisions; the renderer rejects a mismatch. Read `review.md` as a
string into `review.markdown`, using the comment boundaries in
[Review notes](review-notes.md). Put the short current assessment in
`review.assessment` as Markdown without a heading, disclosures or copyable drafts.
It appears once beside the opening outcome, with a direct jump to findings.
Keep it out of `review.markdown`; retain detailed findings and a short validation
summary there. Older inputs without `assessment` still render their assessment
in the findings section. The renderer embeds findings after the narrative
sections and adds Copy comment controls. It preserves the original Markdown
payload; when clipboard access is unavailable, it shows a selected manual-copy
field. No iframe, second HTML, or runtime Markdown fetch is used.

Add `review.verdict` to every new report. The renderer turns it and the finding
summaries into the advisory verdict card that replaces the plain assessment box:
the icon, colour, headline and confidence come only from fixed rules, never from
your wording. Any P0/P1 is red, a P2 or Needs confirmation is orange, only P3 or
Optional items are green "Approvable", and no findings is green "Ready to
approve". Confidence reflects coverage: one or two gaps make it medium, three or
more or failing tests make it low, and a green verdict with low confidence
turns orange. Record coverage honestly; it is the only input you control.

- `complete`: false when a material part of the diff was not reviewed (for
  example a wrapped-up run); the card turns grey "Not fully reviewed".
- `traced`: whether every changed path was traced end to end, not only read.
- `tests`: `pass`, `fail` or `not-run` for the tests covering the change at the
  reviewed head. Reading a test is not running it. `fail` renders “Checks failed”,
  which may include reviewer probes rather than repository tests. Optional
  `tests_note` (plain text, at most 15 words) appears beside the tests status;
  identify the check scope, for example `"tests_note": "Reviewer probes failed; repository tests passed."`.
  The note does not change confidence or imply a repository regression.
- `runtime`: `validated` when the changed behavior was exercised, `not-needed`
  when no runtime behavior changes, otherwise `not-run`. Optional
  `runtime_note` names what was not exercised.
- `unreviewed`: areas left out, in a few words each.
- `why`: two or three short inline-Markdown reasons for the verdict.
- `checked`: what was actually checked, one short item each.

Finding summaries must start with P0–P3, Optional or Needs confirmation; the
card links each one as something to consider and lists the coverage gaps. The
card starts collapsed to one row: icon, headline, confidence, reviewed commit and
how many things there are to consider. Opening it shows `review.assessment`
(required with a verdict), the reasons, the things to consider and what was
checked. For updates, the card also shows the previous run's verdict,
re-derived from its saved input, and the findings resolved since. Beside `review.html` the renderer writes
`review-verdict.json`, which the dashboard card shows; do not edit it.

Wrap each finding in the fixed `<details class="review-finding">` form from
[Review notes](review-notes.md); arbitrary attributes remain unsupported. Findings
start collapsed with severity/title visible, and the report supplies an expand-all
control when there are multiple findings. Keep the overall assessment outside.

Within each finding, use ordinary Markdown for the visible explanation and
example before its comment markers, following [Review notes](review-notes.md).
Paragraphs, lists, small tables and illustrative code fences already work; no
extra JSON field is needed. Keep the reasoning needed to understand the defect
visible when the finding opens, with the detailed evidence and remediation
check in a nested disclosure.

Put coverage, check outcomes and relevant investigation history in `verification`
as Markdown. This becomes an expandable appendix inside the same report. It
must summarize actual evidence even when tests are blocked. Reading a test is
not running it. Authoring files may remain alongside the report but are not
needed to read it. Do not link a second review or explanation page.

Optional `attachments` lists absolute existing evidence paths inside the tracker
root: `.md`, `.txt`, `.log`, `.png`, `.jpg`, `.jpeg`, `.webp`. Markdown may link
these paths; the renderer produces explicit-click file links. Such attachments
are supplementary evidence, not required narrative. The dashboard rewrites these
links through its evidence route. Files must remain outside disposable checkouts.
HTTPS source links are allowed; raw HTML and other URL schemes are not active.

Report order: outcome and assessment, plain words, diagram, cases grid and
mechanism (see [Explanation](explanation.md)), findings, self-check, expandable
verification and provenance. Explanation depth
and prose targets apply to the opening; never cut valid findings to meet them.
The reading estimate covers the opening and walkthrough prose, excluding code,
findings and disclosures. Findings and evidence take additional time; this does
not estimate how long a review should take.
Keep a coherent reading path with descriptive headings. Group related code and
explanation together; avoid making readers open several disclosures to understand
one concern. A small report can use only a cases grid or diagram and one source excerpt.

Additional block shapes:

- Paragraph: `{"type":"paragraph","text":"Plain prose."}`
- List: `{"type":"list","items":["A specific condition and consequence."]}`
- Table: `{"type":"table","headers":["Input","Result"],"rows":[["x","y"]]}`
- Comparison (two lanes of steps; prefer a cases grid or diagram): `{"type":"comparison","lanes":[{"title":"Before","steps":["..."]},{"title":"After","steps":["..."]}],"caption":"..."}`
- Background: `{"type":"details","title":"New to this component?","blocks":[...]}`
- Authored code: `{"type":"example","language":"Dart","code":"...","caption":"Illustrative caller example."}`

### Walk layout and its blocks

Set `"layout": "walk"` at the top level, and `"stats": {"additions": N,
"deletions": N, "files": N}` from the PR. Each section may add `tab` (rail label),
`claim` (scene headline; defaults to `title`) and `lede`. Mermaid blocks need the
report runtime once (`npm ci --prefix scripts/report-runtime`); they render with
the installed Chrome, or `PR_REVIEW_CHROME_PATH`.

- `mermaid`: `source` (a `sequenceDiagram`, `flowchart` or `stateDiagram-v2`,
  under 6000 characters), optional `title`, `caption` and `notes` (participant
  label → one sentence shown when the reader clicks it). It is pre-rendered to
  static SVG at render time; a syntax error fails the render with Mermaid's
  message, so fix the source and render again. Usable in `review.visuals`.
- `compare`: `panes` (one to three), each `{label, tone, blocks}` with tone
  `before`, `after`, `safe`, `risk` or `neutral`; optional `stacked: true` (one
  pane per row, best for side-by-side sequence diagrams) and `caption`.
- `callouts`: `items` of `{tone, title, text, finding}`; tone `good`, `warn`,
  `bad` or `plain`; `finding` is an optional badge label such as "Finding 1".
- `card`: `{name, role, kind, icon, tag, tone, finding}`. `icon` is one of type,
  branch, lock, fn, db, event, check, pipe, flag, api, config, test, user,
  server, file, thread, box. `tag`: new, changed, removed, existing. `tone`:
  `hot` (a finding sits here) or `gate` (the merge condition).
- `pair`: `change` (plain-words logical change), `blocks` (cards or paragraphs)
  and `diff` (`source`, `example` or `paragraph` blocks), optional `label`.

```json
{"id": "how", "tab": "How it works", "title": "How it works",
 "claim": "Creating a session asks the sampler once while other threads wait.",
 "blocks": [{"type": "pair", "change": "One thread at a time creates a session.",
   "blocks": [{"type": "card", "icon": "lock", "kind": "Coordination", "name": "Creation slot",
               "role": "Other threads wait with no deadline.", "tag": "new", "tone": "hot", "finding": "Finding 1"}],
   "diff": [{"type": "source", "path": "Sources/SessionManager.swift", "start": 315, "end": 323,
             "caption": "Waiters block with no deadline (Finding 1)."}]}]}
```

### Paper layout and layered blocks

Default to `"layout": "paper"` for new reports: a continuous page using the walk
fonts and palette. There is no scene rail. Order: masthead and verdict,
standfirst (`outcome`), At a glance, optional background, authored sections,
findings, then a collapsed tail containing questions, verification, references
and provenance. Use the existing `stats` object for additions, deletions and
file count. Sections require `claim` as their heading; `lede` is optional.
The title is at most 12 words. Keep `outcome` to one or two sentences and 40
words; the browser checker warns when it is longer. The prose budget includes
the standfirst, why, judgment questions, approach notes, background, section prose, step notes and code-walk sentences,
excluding masthead, verdict, paths, excerpts, diagram labels and findings.
Paper targets: docs 250 words; config/ci/deps/refactor/test 300; logic/ui/api 450;
lifecycle/data 600. The checker warns above the target and fails above 1.5×.
Paper reports in Deep mode, and walk/classic reports, use the mode-based limits.

```json
{"layout":"paper", "title":"Retries retain the original deadline",
 "outcome":"Queued events keep their deadline when the connection returns.",
 "stats":{"additions":20,"deletions":8,"files":2},
 "glance":{"kind":"lifecycle","blast":"contained","blast_reason":"Only queued exports change."},
 "sections":[{"id":"change","title":"The change","claim":"Reconnecting preserves the deadline",
   "lede":"The queue forwards the caller's limit.",
   "blocks":[{"type":"paragraph","text":"A queued event keeps the same limit when it is replayed."}]}]}
```

`glance` is required in paper. Its `kind` is `docs`, `config`, `ci`, `deps`,
`logic`, `lifecycle`, `data`, `ui`, `refactor`, `api` or `test`. Optional
`kind_label` is a plain label of at most six words. `blast` is `contained`,
`moderate` or `wide`; `blast_reason` is at most 12 words. The third tile shows
the finding count and the first two linked problem sentences, then “+N more”. By default
these come from **The problem in one sentence:** in `review.markdown`, falling
back to the summary title. Zero findings shows “No findings”, followed by the
coverage-gap count when the verdict has gaps. Override the
linked lines with `findings`, each `{text, finding}`; `finding` names an existing
`Finding N` or `finding-N` anchor. Text is one sentence.
Optional `judgment` is a list of zero to three `{text, section?}` objects.
Each `text` is a one-sentence policy or trade-off question for the human;
`section`, when present, must name an authored section id. Nonempty lists render
as “Needs your judgment”; empty lists are hidden. The compact jump row beneath
At a glance links to existing change, code, blast-radius and findings targets.

```json
{"glance":{"kind":"lifecycle","kind_label":"Queue ordering","blast":"contained",
 "blast_reason":"Only queued exports change.",
 "findings":[{"text":"Replay loses the caller's deadline.","finding":"Finding 1"}]}}
```

Optional top-level `background` renders “Before you read”. Its `story` is one
to three sentences, followed by a compact definition list of one to five
`terms`, each `{term, meaning}`. Keep the complete background within 100 words.
The review prompt's `Reader familiarity: familiar` means omit background and
glossary for that repository. `Reader familiarity: new` (also the default when
absent) permits background only for unfamiliar concepts needed to understand
the change. Preserve exact code identifiers; explain them without renaming them.

```json
{"background":{"story":"Events wait in a queue while the connection is down.",
 "terms":[{"term":"Replay","meaning":"Sending the waiting events again."}]}}
```

Optional paper blocks (omitting them preserves the existing authored layers):

- `why`: `{text, sources?: [{label, url?}], inferred}`. `text` is at most two
  sentences and 45 words. `inferred` is a required boolean; require at least one
  source unless true. Source labels are plain text and optional URLs must be
  HTTPS without credentials. Renders visibly under the title as “Why this PR
  exists”, with source chips and an “inferred from the diff” chip when true.
- `orientation`: an alternative to `background`; providing both is rejected.
  Required `open` is boolean and `teaser` is at most 12 words. Native details
  summary reads “Background” plus the teaser. Require `map` or `story`.
  `map` has three to six `{label, name?, changed}` items: a plain-word label,
  optional real identifier without whitespace, and required boolean `changed`.
  At least one item must change; changed boxes are labelled “this PR”.
  `story` is at most three sentences. Optional `terms` has zero to four
  `{term, meaning}` definitions; optional `compare` is one sentence.
  All authored orientation text, including teaser, map labels and names, must
  total at most 120 words. The checker counts orientation in the explanation
  cap only when initially open; the renderer enforces 120 words in either state.
- Section-level `approach`: `{text, source?: {label, url?}, suggested?: bool}`.
  `text` is one or two sentences, rendered after section prose in an “Approach”
  callout. Require a source, or `suggested: true` to label it “our note, not
  stated by the author”; source and suggested true are mutually exclusive.

```json
{"why":{"text":"Queued events lost their original deadline.",
 "sources":[{"label":"Issue #223","url":"https://github.com/owner/repo/issues/223"}],"inferred":false},
 "orientation":{"open":false,"teaser":"Where the queue sits",
  "map":[{"label":"App","changed":false},{"label":"Queue","name":"ReplayQueue","changed":true},{"label":"Exporter","changed":false}],
  "story":"The app queues events while disconnected.","terms":[]},
 "glance":{"kind":"lifecycle","blast":"contained","blast_reason":"Only queued exports change.",
  "judgment":[{"text":"Should replay preserve an expired deadline?","section":"change"}]}}
```

`code_walk` works in every layout. Use two to six numbered `items`, each with a
repository-relative `path`, one-sentence
`text`, and non-empty `diff` containing only `source` or `example` blocks.
The file badge (new, changed, removed or unchanged) comes from `git diff
--name-status` between base and head; an authored `tag` is ignored. An
unchanged consumer shown for context is badged unchanged.
Optional `example` is a concrete introductory sentence. The first source excerpt of each item is visible inline, with any preceding
examples. Later excerpts may use a native disclosure. Each file path appears
once per item, in its chip or first distinct source header. Source ranges retain
the 15-line limit and exact pinned extraction. Authored examples remain
explicitly illustrative.
In paper, each `diff` excerpt may set boolean `open`: true keeps it inline,
false puts it under “More excerpts”. Omitted values retain the first-source
default; at least one excerpt must stay open. When the two open excerpts are
one base and one head source, they sit side by side at 1000px and wider, stacking
below that width. The checker warns on code-walk text and excerpt captions with
fewer than four words. Blobless partial clones must contain the excerpt blobs;
otherwise point `repository` at a full or `--shared` clone.

```json
{"type":"code_walk","example":"Take an event queued while offline.","items":[
 {"path":"src/queue.ts","tag":"changed","text":"The queue keeps the deadline.",
  "diff":[{"type":"source","path":"src/queue.ts","start":10,"end":14,"caption":"The stored deadline."}]},
 {"path":"src/export.ts","tag":"changed","text":"Replay forwards the stored deadline.",
  "diff":[{"type":"source","path":"src/export.ts","start":20,"end":24,"caption":"The replay call."}]}]}
```

`stepper` keeps its schema and works in every layout, rendering a numbered
diagram with every note visible. Use it when order or a handoff benefits from
optional focus. It requires `title`, `caption`, one complete `visual`,
and two to eight `steps`. Each step has `label`, one-sentence `text`, optional
`focus`, and optional `finding` linking an existing finding. Do not put manual
numbering such as `1. ` in list items, step labels, or step text; the renderer
supplies numbering and rejects numbered text.

| Visual | Focus targets | Default when `focus` is omitted |
| --- | --- | --- |
| `mermaid` with `sequenceDiagram` | Unique 1-based message indices; text and both participants highlight together | Message i for step i |
| `mermaid` with `flowchart` or `graph` | Node ids from the source; edges between focused nodes also highlight | Node i in rendered/source encounter order |
| `diagram` | Unique `dg-*` ids in sanitized markup, outside `defs`/`marker` | Element i with an id, in markup order |
| `flow` / `sequence` | Unique 1-based step indices | Visual step i |

Explicit `focus` is a non-empty array. Missing ids, duplicate targets, indices
outside the visual, and defaults beyond the available elements fail rendering
with the step number and available targets. Put diagram ids on drawable groups,
nodes, or arrows; use explicit focus when grouping several elements or when
visual order differs from explanatory order. Mermaid remains pre-rendered SVG,
with no runtime dependency in the report. State diagrams are not stepper visuals.

Every note stays visible below the full-width diagram, in columns where space allows.
Number badges mark each note's focus elements. Click a note or one of its badges
to highlight its elements and dim the rest; click the same note/badge again or
press Escape to clear. Notes and badges are keyboard focusable; Enter and Space
toggle focus. Highlighting is instant, with no animation or stepping controls.
Without JavaScript and in print, readers get the complete visual and every
explanation as an ordered list.

Match the visual to the change: sequences for component handoffs over time,
state flows for UI transitions, flowcharts for branching validation. Use a
before/after value or case table when that explains a small change. Omit diagrams
for straightforward documentation, copy and configuration changes.

```json
{"type":"stepper","title":"Follow a queued event","caption":"Source-traced call order.",
 "visual":{"type":"mermaid","source":"sequenceDiagram\nConnection->>Queue: Reconnect\nQueue->>Exporter: Replay with deadline"},
 "steps":[{"label":"Reconnect","text":"The connection asks the queue to resume."},
          {"label":"Replay","text":"The queue forwards the deadline."}]}
```

```json
{"type":"stepper","title":"Trace the handoff","caption":"An illustrative handoff.",
 "visual":{"type":"diagram","caption":"Input reaches output.",
   "html":"<svg viewBox=\"0 0 220 60\"><g id=\"dg-input\"><rect x=\"5\" y=\"5\" width=\"60\" height=\"50\" fill=\"none\" stroke=\"currentColor\"/></g><path id=\"dg-send\" d=\"M70 30 L210 30\" stroke=\"currentColor\"/></svg>"},
 "steps":[{"label":"Input","text":"The input is ready.","focus":["dg-input"]},
          {"label":"Send","text":"The input crosses the boundary.","focus":["dg-send"]}]}
```

### Diagrams, cases grids and optional interaction

Choose the representation using [Explanation](explanation.md); reuse a block
only when it fits the concept.

- `diagram`: `html`, `caption` and optional `title`. Static HTML and inline SVG
  for a purpose-built picture of the change. The renderer parses and
  re-serializes it through an allowlist and rejects anything else, so fix the
  markup when rendering fails. Allowed: layout and text elements (`div`,
  `span`, `p`, `strong`, `em`, `b`, `i`, `s`, `code`, `small`, `sub`, `sup`,
  `mark`, `kbd`, `br`, `hr`, lists, `h4`, `h5`, tables) and SVG shapes (`svg`,
  `g`, `path`, `rect`, `circle`, `ellipse`, `line`, `polyline`, `polygon`,
  `text`, `tspan`, `defs`, `marker`, `title`, `desc`) with presentation
  attributes, `style`, `role` and `aria-*`. Not allowed: links, images,
  scripts, event handlers, `<style>`, `use`, `foreignObject`, `data-*`, and
  `url()` other than `url(#dg-…)` for a marker. Classes and ids must start
  with `dg-`. Prefer the diagram kit over inline styles:
  - containers: `dg-stack` (vertical), `dg-row` (wraps on phones), `dg-branch`
    (side-by-side lanes that stack on phones), `dg-lane` (dashed lane box);
  - nodes: `dg-node`, plus `dg-good`, `dg-bad`, `dg-warn`, `dg-accent` or
    `dg-muted` for the state; state must also be in the words (✓, ✗, “throws”);
  - connectors and text: an empty `dg-arrow` shows ↓, `dg-arrow dg-arrow-right`
    shows →; `dg-label` (small heading), `dg-code` (identifier), `dg-note`;
  - `dg-badge` (finding marker), `dg-badge-good`, `dg-badge-warn`.
  For SVG, use a `viewBox` so it scales to a phone, keep labels at least 12px,
  and use `fill="currentColor"` or `var(--fg)`, `var(--muted)`, `var(--line)`,
  `var(--panel)`, `var(--soft)`, `var(--accent)`, `var(--good)`, `var(--bad)`,
  `var(--warn)` so both themes work. Give an SVG `role="img"` and an
  `aria-label` that states the takeaway.
- `cases`: `columns` (a situation column plus one to four outcome columns),
  `rows` (one to eight) and `caption`, optional `title`. Each row has
  `situation`, optional `finding` (for example `"Finding 1"`, shown as a badge)
  and one `cells` entry per outcome column with `text` and `status`: `works`
  ✅, `breaks` ❌, `changes` ⚠️, `unknown` ❔, `absent` (visible “Not available”)
  or `same` (no mark). Use `absent` when a feature did not exist in a Before
  column; reserve `breaks` for behavior that fails. Marks are
  also given in words for screen readers.

The shared renderer also supports:

- `flow`: `title`, `caption`, and `steps` with `label`, `detail`, optional `icon`
  (`app`, `memory`, `storage`, `network`) and `state` (`normal`, `active`, `muted`,
  `blocked`). A connected path becomes vertical on phones. Put the meaning in
  labels as well as color; use icons only when they represent the real role.
- `sequence`: `title`, `caption`, and ordered `steps` with `from`, `to`, `message`
  and optional `state` (`normal` or `blocked`). This is call/event order, not a
  time-scaled chart.
- `scenario`: `title`, `caption`, and two to five `frames`, each with `label` and
  `blocks` (`flow`, `sequence`, `paragraph`). Buttons select a state; without
  JavaScript all states remain readable. Verify every state and explain the
  central condition outside the control. This illustrates source behavior, not
  execution of PR code.

For a graphic inside a finding, define a `diagram`, `cases`, `table`, `flow`,
`sequence`, `scenario` or `stepper` block in `review.visuals`, keyed by a short identifier, and place `<!-- review-visual:timeout -->` on its own line where it
belongs. For example:

```json
"visuals": {
  "timeout": {
    "type": "sequence", "title": "Where the timeout stops", "caption": "Source-traced call order.",
    "steps": [
      {"from": "Runtime", "to": "Disk buffer", "message": "Pass timeout = 1"},
      {"from": "Persistence", "to": "Exporter", "message": "Replay omits timeout", "state": "blocked"}
    ]
  }
}
```

Place review visuals outside comment-copy markers. The draft must remain
self-contained text. Raw HTML outside a `diagram` block and authored scripts
remain unsupported. When a recurring kind of diagram needs something the kit
cannot express, extend the shared assets and validation rather than forcing it.

For the visible plain-words opening, use an ordinary first section with
`paragraph` blocks. No new schema field is needed. Keep required context out of
`details` blocks. Put longer optional background there, and let the later
`source` blocks connect the diagram and grid to exact code.

A source block extracts exact lines, defaulting to `side: "head"`. Use `base`
for old code. Added/removed markers are derived from the comparison. Adjacent
source blocks can explain portions of a large method without inventing its
middle. Do not put hand-edited source text in a source block; there is no such
field. The evidence object stays in JSON and is not rendered as reader prose.
Do not store secrets in the input/evidence.

Render and validate:

```sh
python3 scripts/render_review.py input.json /absolute/output.html
node scripts/check_review.cjs /absolute/output.html /absolute/validation-directory input.json
```

The checker drives the installed Chrome through the report runtime's
`playwright-core` (`npm ci --prefix scripts/report-runtime`). Set
`PR_REVIEW_CHROME_PATH` to choose another Chromium/Chrome executable, or
`PR_REVIEW_PLAYWRIGHT_MODULE` to a full Playwright module to use its bundled
browser. Use the host's dependency discovery rather than downloading another
browser unnecessarily.

Both commands launch headless Chrome: the renderer for Mermaid blocks, the
checker always. Chrome cannot start inside the Codex sandbox (macOS shows a
crash dialog), so inside it both refuse with an error instead. In a dashboard
review, render and check with one command:

```sh
python3 scripts/report_check.py --run-id <run-id>
```

It renders the run's `input.json` to `review.html`, checks it into
`report-check/` and prints both outputs as JSON, exiting non-zero on any
error. The review worker runs the steps outside the sandbox, so the reviewer
can fix and rerun without escalation. With no live dashboard worker it runs
them directly, which needs the normal host permission for launching a browser.

The checker writes `validation.json` and desktop/phone screenshots in both
themes, including expanded and collapsed states when findings are present. Exit 1 means a
mechanical failure; exit 0 can still include warnings requiring judgment. It
checks the shared template's known controls; custom interactions require
additional focused checks. Keep a record of semantic/source verification too;
this browser check does not execute PR code or prove behavioral claims.

## Output and validation

Write `review.html` under the run directory. The report is self-contained with
inline CSS and fixed JavaScript; retain its restrictive CSP. Repository text and
source code are inert content. Do not embed repository scripts, dynamic code,
external assets, analytics, forms, frames or network calls. Verified HTTPS
source links and explicitly listed local evidence links require a user click.

Run the browser checker before releasing the checkout so it can independently
compare source excerpts to Git. It checks source fidelity, explanation length,
responsive layout, themes, quiz controls, exact comment-copy payloads and manual
copy fallback. Inspect its desktop/phone screenshots in light/dark modes; test a
mixed source diff with a real blank line when changing the renderer. Fix failed
checks; report unavailable browser checks as a limitation.

The renderer rejects revision mismatches and malformed copy boundaries but
cannot prove the Markdown's claims refer to those revisions. Reconcile the
visible SHAs, coverage, explanation and findings yourself before registration.
