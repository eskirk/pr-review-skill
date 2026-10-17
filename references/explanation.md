# Explain the change at the top of the review

Help the reader understand what changes, why it matters, and the condition most
likely to surprise them. The reader is a senior engineer reviewing many PRs a
day across many repositories and stacks: experienced, but often without fresh
context about this project. Give the missing local context, never the general
engineering. This is the opening of the review report; findings follow it.

## Scope and depth

The review covers every change regardless of narrative length.

Resolve an ambiguous target before proceeding. Pin the repository identity and
comparison revisions; distinguish the target branch tip from the merge base
used for a PR diff. Read the surrounding execution path and relevant issue or
PR discussion. Do not change the user's checkout or execute repository code.
Use an existing verified repository read-only, or the isolated checkout supplied
by the PR-review workflow. Git show/diff do not require switching branches.

Default to **Brief**. Choose Small for a single simple behavioral change;
Standard for multiple interacting decisions, lifecycle/ownership changes, or a
substantial compatibility contract. Diff size informs this choice but does not
decide it. Use **Deep** only when the user asks for an in-depth explanation.
“Full PR review” selects the review pipeline, not a Deep explainer. For paper
reports in Brief mode, the browser check enforces a cap per change kind (it
warns above the cap and fails above 1.5×); Deep mode uses its 3,000-word limit:

| Kind (`glance.kind`) | Explanation prose cap |
| --- | ---: |
| `docs` | 250 |
| `config`, `ci`, `deps`, `refactor`, `test` | 300 |
| `logic`, `ui`, `api` | 450 |
| `lifecycle`, `data` | 600 |

Caps cover the why, standfirst, judgment items, open background, section prose,
approach notes, step notes and code-walk sentences, not code, diagram labels or
findings. Choose the kind by the behavior that changed, not the file type: a CI
change with retry and classification branches is `logic` or `lifecycle`. Under the cap is better; cut
repetition first. Stop when the
reader can explain the changed behavior, its mechanism and the consequential
condition. Keep essential conditions and caveats instead of cutting them to fit.

## The paper layout

Render with `"layout": "paper"` ([Authoring](authoring.md)): one continuous page
the reader can skim and search, with no scenes to click through. Each layer
stands alone and adds detail; never restate the layer above.

1. **Title**, at most 12 words: the behavior change as a claim.
2. **Why this PR exists** (`why`, always present): one or two sentences, at
   most 45 words, on what was missing or wrong before, for whom, and what
   becomes possible. See below.
3. **Outcome** (standfirst), one or two sentences and at most 40 words, no code
   identifiers: what is different now, for whom, and the deciding condition or
   boundary (“only with batching on”, “diagnoses the hang, does not fix it”).
   It must not repeat the why: together they read problem → change → caveat.
   A reader who stops here has the gist, so it must be accurate on its own;
   detail further down cannot repair a misleading top.
4. **At a glance** (`glance`): the change kind, blast level with a reason of at
   most 12 words, the finding problem sentences derived from the review, and
   **Needs your judgment** (`glance.judgment`) when it applies (see below).
5. **Background** (`orientation`), by familiarity (see below).
6. **The change**, one section with a claim heading. State the general rule in
   at most 100 words, then the one visual for the change kind. Add one concrete
   example (real input values, a named actor) only when the mechanism is
   subtle; the visual traces that example. Do not restate the rule after it.
   Add an `approach` note only when it names a simpler alternative a reviewer
   would expect and why it was not taken (“`Uri.port` reports 80/443 when no
   port is written, so the PR parses the raw authority”). Do not restate a code
   comment or the why. Skip it for docs, deps and config.
7. **Code changes in plain words** (`code_walk`): two to five items in
   data/control-flow order (check the order against source), one plain
   sentence each, tied to a diagram step where relevant (“Step 3 happens
   here”), with exact excerpts. Choose the visible excerpts with `open`: the
   guard, the new branch, the deciding consumer, not automatically the first
   range. For a removal, open both the base and the head excerpt. When an
   unchanged consumer decides the visible effect (stored URL → channel port),
   show it; it is badged unchanged.
8. **Blast radius**: a `compare` of `Not in the blast` (tone `safe`) and
   `In the blast` (tone `risk`), ending with a `gate` card “Do not merge until…”
   or “Safe to merge when…”. Keep both panes even for a low-risk PR. Separate
   changed behavior from changed files: “tracing code is unchanged” is not
   “tracing signals are unaffected”.

Findings, self-check, verification and provenance follow from the review object.
Headings state claims (“Retries stop after three failures”), not topics
(“Retry logic”), so a reader who reads only headings still gets the story.

## Why this PR exists

Reviewers look for the rationale first and rarely come back for it. Harvest it
from the PR description, the linked issue (`Fixes #N`) and commit bodies, in
that order, and cite each with a `sources` chip. When nothing states it, write
the most defensible reading of the diff and set `inferred: true`; that chip is
itself a review signal. Never invent user impact, an incident or author
rationale, and never paraphrase the title as the reason (“adds batching to
support batching”). Attribute reported history (“the PR description says four
nightly runs hung”) rather than presenting it as observed. For docs, deps and
test PRs one short sentence is enough. Keep the why in every report, whatever
the familiarity.

## Background and reader familiarity

The review prompt may include `Reader familiarity: familiar` or
`Reader familiarity: new` for the PR's repository; when it is absent, treat the
reader as new.

- **familiar**: omit `orientation`, or include it with `open: false` only when
  the PR touches a corner of the repository the reader is unlikely to know.
- **new**: `orientation` with `open: true`. It orients rather than teaches:
  - a `map` of three to six boxes on the real path (entry → changed part →
    consumer), plain words plus the real name, with only the parts this PR
    changes flagged `changed`; name every component a box stands for;
  - a `story` of at most three sentences on how this part worked before;
  - at most one `compare` line tying it to something a senior engineer from
    another stack knows, saying where it stops being accurate;
  - zero to four `terms`, only for repository- or stack-specific names.

  Map-only or story-only is fine. The `teaser` says what is inside, so a reader
  can skip it without opening it. When the reader knows the domain but not the
  code (OTLP known, Dart new), explain the repository's structure and language
  quirks, never the domain's primitives.

Nothing needed for the gist or the review decision may live only inside the
background: the why and outcome stand alone. Never define universal engineering
concepts (a retry, a mutex, a feature flag, a hook). Never rename identifiers:
use the real name and explain it (“`meta`, the attributes sent with each
signal”), so the reader can match the page to the code. Analogies rarely help;
use one only when it genuinely shortens the explanation and say where it stops
being accurate.

## Needs your judgment

`glance.judgment` holds one or two genuine policy or trade-off questions the
source cannot settle (“Is org-wide `members: read` acceptable for a digest
bot?”, “Should sessions saved by the old format get a new sampling decision on
upgrade?”). Name the practical consequence and link the `section` holding the
evidence. They are not defects (those are findings), test gaps or a restated
table row. Omit it when there is no real call to make; most fixes, docs and
deps PRs have none.

## Visual for the change kind

Draw a diagram only when its kind matches the structure of the change; a
mismatched diagram costs attention and adds nothing.

| Change | Visual |
| --- | --- |
| docs, copy, trivial value change | None; at most a before/after `compare` of what a reader sees |
| config, ci, deps | Table of setting × before/after × effect; a Mermaid `flowchart` only if job or stage order changed |
| logic, parsing, validation | `cases` grid; a small Mermaid `flowchart` or `diagram` of the decision when there is real branching |
| several components handing off over time (lifecycle, ordering, queues) | Mermaid `sequenceDiagram`, at most about six participants |
| data transformation | `diagram` pipeline showing one concrete record at each stage |
| UI flow, especially behind a flag or permission | State or storyboard `diagram` of the screens in order, flag on/off side by side |
| refactor | Old → new mapping table, or an ownership `diagram` if responsibilities moved |
| api | Before/after `compare` plus a compatibility table per caller type |

**One primary visual.** Before adding a second representation (diagram, steps
and cases grid), say what it adds that the first does not, and cut it
otherwise. Mutually exclusive branches (parser cases, input classes) read faster
as a cases grid than as a tall flowchart; keep flowcharts to about eight nodes
and no crossing edges, and prefer a table once a diagram would be taller than a
screen. Do not use a sequence diagram for simple prop wiring or a single value
passed through. Keep diagrams to about 12 nodes, labels in plain words plus the real
name. Every node, arrow, ordering and label must match the pinned source: do not
draw “every rule” when some take another path, and do not reorder steps for a
tidier picture. Captions say what to notice and label the diagram source-traced
unless it was executed. Build with Mermaid, the `diagram` SVG kit, or `flow`,
`sequence` or `scenario` when they fit exactly ([Authoring](authoring.md)).

**Cases grid.** State the assumptions the rows share in the caption (defaults,
restore mode, which transport or processor), and qualify a row that depends on
one. Three to six concrete situations × before/after: the normal
path, the case the PR fixes, the off-path rows where generalizations break
(flag off, feature disabled, other transport, other caller), and each finding's
case. Mark works / breaks / changes honestly; use `absent` for “did not exist
before”, not `breaks`. When a Before column would only repeat `absent`, use
“Setting / New value / Effect” or “Reader action / Result” instead.

**Numbered diagram (`stepper`).** Use it when the reader must follow an order
of events, a moving record, or a sequence of screens. The renderer draws the
complete diagram with numbered markers and lists every step note below
it; clicking a note or its marker (or pressing Enter on it) highlights
those elements. Nothing is hidden behind Prev/Next, and nothing moves. Write
three to seven steps mapped to drawn messages or nodes. Each note is one
sentence that adds a fact the drawing does not show (a value, a condition, a
consequence); never re-read the arrow label. Put `finding` on the step where a
finding's failure happens. For a four-box flow, a plain diagram is enough.

A finding whose failure is an ordering problem (race, deadlock, retry, lost
update) should carry a sequence of its failure in `review.visuals`.

## Show code inline

Code changes stay visible in the page: the reader is reviewing code and should
not need clicks to see it. Show the beacon lines (the guard, the new branch, the
changed call), not whole functions, and include a few lines of an unchanged
consumer when it explains the effect. Write the JSON input described in
[Authoring](authoring.md); `scripts/render_review.py` extracts source from the
supplied Git repository at the pinned revision with permalinks, line ranges,
highlighting and changed-line markers.

Prefer excerpts of at most 15 lines. Never replace an exact excerpt with
shortened or invented statements carrying source-diff styling; for omissions,
select several short ranges and explain the gap. Authored snippets use the
**example** block, visibly labeled illustrative; they must not masquerade as
exact lines. Preserve real source blank lines. Diagrams use semantic HTML/SVG,
not ASCII art. Do not add dependencies for decoration.

## Establish the explanation before rendering

Keep a small evidence record (`evidence.md`) alongside the authoring input,
outside the reader's narrative. Record:

- The main behavior claim and its pinned source location. Distinguish
  implementation behavior, intended policy and a verified external contract.
- Each grid row's and example's exact input, assumptions, before/after output
  and how it was checked, including separators, missing fields, defaults, error
  handling and ownership when they affect the result.
- For claims such as “the spec requires” or “every SDK”, an authoritative
  source, or a narrower claim. A code comment or PR title is not independent
  evidence that its interpretation of a standard is correct.
- Which tests assert the behavior. Reading a test is not executing it, and a
  test's existence does not prove its assertions cover a scenario.

Do not invent an observed failure, user impact, consumer, timing, build result
or author rationale. Label uncertainty that changes the explanation. A
hand-drawn diagram illustrates the source; it does not validate it.

### Absolute-claim pass (mandatory)

Simplifications go wrong most often by becoming universal. Before rendering:

1. Start with the why, outcome and At a glance, which many readers stop at.
   List every sentence, label, grid cell and step note containing every, all,
   any, always, never, only, nothing, no longer, can't, must, guaranteed, same
   as, unchanged or pins.
2. For each, find pinned source that proves it **in every mode**: feature flags
   on and off, disabled or paused features, other transports or queues, other
   callers, error and backoff paths, other platforms. If it cannot be proved,
   narrow it where the claim is made (“with session tracking on”, “for plain
   URLs on the Dart VM”) or remove it.
3. Check every ordering claim and every diagram message, node and order, and
   every “Step N happens here”, against source. “A runs before B” must hold on
   each path, not only the one traced.
4. Check version wording: `^1.2.0` is a range, not a pin.
5. Record claim → file:line → verdict in `evidence.md`.

Then pass the draft to the independent fact-check stage in `SKILL.md`. In a full
review, reconcile with the final synthesis: remove rejected warnings, keep
material supported caveats, and do not duplicate the defect list.

## Self-checks

Default to one or two questions; three at most in Brief mode, five in Deep.
Favor a scenario that tests a consequential distinction: which branch runs,
whether data is retained, whose resource closes, or how a partial input
behaves. A grid row or finding makes a good source. Use two to four plausible,
comparable choices, one correct; no gotchas or “all/none of the above”. Verify
each answer against source. The quiz stays collapsed and optional and never
separates the reader from the findings.

## Colleague-style check

Can a colleague who reads only the title, why, outcome and At a glance say why
the PR exists, what changed and where the findings sit? Can a reviewer new to
the repository, after the background, point to where the change sits? Can they read the grid and say who is better
or worse off? Group by behavior, not file order; place each excerpt beside its
claim. Do not invent author intent; distinguish documented rationale from
inference.

## Legacy layouts

Older reports use `"layout": "walk"` (a scene rail, one scene at a time) or the
classic layout (in plain words, diagram, cases grid, excerpts). The renderer
still supports both for re-rendering; write new reports in paper.

The renderer, offline security and visual validation requirements are in
[Authoring](authoring.md) and the main skill. Do not produce a separate page.
