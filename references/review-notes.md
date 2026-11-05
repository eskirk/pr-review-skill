# Review notes

Read when synthesizing a full review. `review.md` helps the user decide what to
send and what to do next. Keep investigation detail in `verification.md` and
the change explanation at the top of the same HTML report. `review.md` is
renderer input; the reader opens `review.html`.

The reader must be able to understand each finding, judge whether it is right,
and post a helpful comment **without researching what the finding means**.

## Shape

Put the short current assessment in `review.assessment` for display beside the
opening outcome: what merits a comment, what is optional, what needs confirmation,
and any remaining merge or verification limitation. Keep the PR link, reviewed
base/head SHAs and review date in the report's existing metadata/provenance;
distinguish historical SHAs from current PR state. Start `review.md` with findings
or validation, without repeating the overview assessment or metadata.
Keep this to a short paragraph or a few bullets that make the next action clear.
Also record `review.verdict` (see [Authoring](authoring.md)); the renderer
shows the assessment inside a collapsed advisory verdict card. Keep the
assessment consistent with that verdict.
Mention only applicable categories; let finding titles carry individual concerns
instead of repeating every finding in the assessment.

For each supported defect, teach it before showing the copyable draft. Keep the
explanation, draft and evidence together:

````markdown
<details class="review-finding">
<summary>P2 · One bad item empties the whole batch</summary>

**P2 · Comment · Source-verified** · [src/parser.dart:42](https://github.com/owner/repo/blob/HEAD_SHA/src/parser.dart#L42), right side

**The problem in one sentence:** If one item in a batch fails to parse, the
parser now returns nothing, including the items that were fine.

**Why you should care:** Callers that import mixed data silently lose every
valid record in that batch, and the result looks the same as an empty batch.

**Walk me through it:**

1. The batch is `[valid A, invalid B, valid C]`. The existing contract is to
   skip malformed items and keep the rest.
2. A parses and is added to the result.
3. B throws. The new `catch` wraps the whole loop, so the loop stops and the
   result is replaced with an empty list. C is never read.
4. Before this PR the `catch` sat inside the loop, so the result was A and C.

**Is it real?** High confidence from the source trace; not executed. It would
be intentional only if the PR meant to make batches all-or-nothing, which
neither the description nor the tests say. The author might reply that
invalid items are rare; the loss is still silent when they happen.

**How to fix it:** Move the `catch` back inside the loop (sketch, not a tested
patch; `reportError` is the existing reporting call):

```dart
final results = <Item>[];
for (final raw in batch) {
  try {
    results.add(parseItem(raw));
  } on FormatException catch (error) {
    reportError(error);
  }
}
return results;
```

A test with a mixed batch returning A and C would cover it.

<!-- review-comment:start -->
For `[valid, invalid, valid]` we now get an empty result, since the catch wraps
the whole loop and stops at the first bad item. Should we catch per item
instead? Something like:

```dart
for (final raw in batch) {
  try {
    results.add(parseItem(raw));
  } on FormatException catch (error) {
    reportError(error);
  }
}
```

A mixed-batch test would keep this from regressing.
<!-- review-comment:end -->

<details>
<summary>Evidence and remediation check</summary>

Link the pinned source and relevant contract supporting the example. Record
whether it was traced or reproduced, what was checked about the proposed
remediation, and what remains uncertain. Keep detailed logs in verification.

</details>

</details>
````

### Make multiple findings easy to scan

Wrap each finding in the exact `<details class="review-finding">` form above.
The summary carries severity and a title that names **what goes wrong for a
caller, user or test author in plain words**, not the mechanism: “Tests with a
custom binding get the real driver instead of the mock”, not “Custom test
bindings select real drivers”. Use Optional or Needs confirmation instead of a
defect severity where appropriate. Sort supported defects by severity; keep the
overall assessment, material blockers and validation summary outside all
finding disclosures so the recommendation is always visible.

Put severity or Optional/Needs confirmation, disposition and evidence status on
one bold metadata line, followed by the placement link, as in the example.
Do not spread them over several labelled paragraphs before the explanation.

Findings start collapsed. Each opens independently; opening another must not
close the first. The combined report adds Expand all / Collapse all when there
is more than one finding. Put the explanation, draft and nested evidence inside
the finding; evidence remains separately expandable. A clean review needs no
empty disclosure. Do not duplicate the finding title as a heading inside it.

### Explain each finding like a colleague at a whiteboard

Use the labels from the example, in that order:

- **The problem in one sentence:** plain words, no identifiers unless defined.
- **Why you should care:** who hits it and how bad it is, without exaggeration.
- **Walk me through it:** three to six numbered steps carrying one real value or
  action through the relevant branches, ending where it goes wrong. Contrast the
  old behavior when that explains the regression. Explain unfamiliar objects at
  first use. A small table can list several inputs that fail the same way. For
  a failure involving ordering, ownership or propagation, a small review visual
  can replace part of the walkthrough; place it just before this section.
- **Is it real?** Confidence and how it was checked (reproduced, source-traced,
  CI). The strongest reason it could be wrong or intentional. What the author
  might reasonably reply, and whether that reply changes anything.
- **How to fix it:** see the next section. When no easy fix exists, say so and
  name the trade-off instead of inventing a patch.

Aim for about 250–350 words before the draft, excluding code; a simple defect
may need far less, and the validator warns above 450. Establish the expected
behavior from a checked contract or requirement; a deliberate behavior change
alone is not a defect. For an optional suggestion, explain the concrete benefit
without inventing a defect and shorten the structure accordingly.

Verify each example against the pinned source, callers and assumptions. Label
source-traced outcomes as such; reserve observed/reproduced for checks actually
run. Quote logs verbatim or say you are paraphrasing. Use synthetic inputs
openly, never fabricated production incidents, affected users, measurements,
successful builds, author actions or data loss beyond what the evidence shows.
For an unresolved concern, keep the scenario conditional and name the missing
fact. The explanation must retain the finding's uncertainty and severity.

### Fix sketches

Show the fix when a simple remediation is known. Every sketch must:

- be **self-contained**: declare every variable it uses, include required
  imports, and show how new code is wired in (callers, defaults, constructors,
  registration). A new function that nothing calls does not fix anything;
- mark omitted existing code with a `// ...unchanged` comment, never silently
  dropping an existing `catch`, `finally`, guard or error path;
- use field names, parameters and string literals exactly as in the pinned
  source, including parameterized ones, and say which file each part belongs in;
- stay short (normally 12 lines or fewer per file) and be labelled as a sketch,
  not a tested patch, unless it was actually executed.

When the fix replaces only the lines the comment is attached to, prefer a
GitHub ```` ```suggestion ```` block with the exact replacement lines, checked
against the pinned source, so the author can apply it in one click. Check that a
suggested test would actually catch the regression in its intended file and
setup. The draft uses the same sketch or a clearly labelled subset that still
makes sense on its own; the validator warns when draft code does not appear in
the finding explanation.

### Drafts, evidence and other dispositions

Keep the reader-facing explanation outside the copy markers. The copyable
comment is self-contained for the PR author: lead with the concrete case, keep
one concern, and include the fix sketch or suggestion block when it makes the
suggestion clearer (“something like:”). Up to about 150 words outside code is
fine. Use the collapsed evidence section for supporting source links,
reproduction details and the remediation check, rather than repeating the
explanation there.

Use real verified locations and SHAs. Use `Optional` in the metadata line for
selected test, documentation or housekeeping suggestions; state that they are
non-blocking in the comment when useful. A general PR comment needs no invented
line attachment. Do not force numeric severity onto optional suggestions.

### Findings already discussed on the PR

When the saved PR discussion already covers a finding, say so where the reader
looks first. Put `Already discussed` in the metadata line with a link to the
thread, and name who raised it and its state in “Is it real?”:

```markdown
**P2 · Already discussed · Reproduced** · [open thread by alex-maintainer](https://github.com/owner/repo/pull/7#discussion_r123) · [src/a.swift:142](https://github.com/owner/repo/blob/HEAD_SHA/src/a.swift#L142)
```

Write the draft as a reply for that thread, adding only what is new: a
reproduction, a concrete fix sketch, a case the thread missed, or confirmation
that the latest commit still has the problem. Do not restate the original
comment. When there is nothing new to add, write “No reply needed; the open
thread covers it” instead of a draft. The same applies to comments the
requesting reviewer already made. Mention already-discussed findings in the
assessment (for example “two of three findings are already raised in open
threads”) so the next action is clear.

For `Needs confirmation`, put it in both the summary and the metadata line,
provide the missing evidence and how to obtain it, and add no review-comment
block. Do not turn unresolved hypotheses into copyable defect comments. Omit
this section when there are no material open questions.

End with a short validation summary: checks actually run and their outcomes,
local versus remote CI, app journeys reached and exercised, and material
skips or blockers with reasons. Say which checks ran outside the sandbox or
with network access; never group them under a "sandboxed" label. Link representative screenshot evidence when
captured, with detailed verification embedded at the end of the report. Successful checks are evidence,
not additional findings. Keep commands and full journey logs in verification.md.
For a reproduced defect, include concise actions and expected/observed behavior
with its screenshot or log links beside the finding, outside the copyable body.
For a clean review, these may be the entire findings Markdown; the HTML still
includes the change explanation above it.
No arbitrary minimum or maximum finding count applies.

## Draft boundaries and rendering

Put the comment body as ordinary Markdown between the exact standalone
`<!-- review-comment:start -->` and `<!-- review-comment:end -->` lines.
The report renderer adds **Copy comment** and **Copy handoff prompt** buttons.
Copy comment copies only that body, including intended Markdown links and code
fences, plus the on-behalf footer from `comment_attribution` (see
[Authoring](authoring.md)). Copy handoff prompt adds the finding's file and line
when available, then the draft as plain text; it leaves out the on-behalf footer.
Put placement, disposition, confidence, severity and internal reasoning outside
the markers. Do not wrap the whole body in a blockquote; use blockquotes inside
it only for intentional quotations.

Keep a blank line around fenced code, lists and paragraphs. Evidence may use
the exact bare `<details>` form above. The outer finding also accepts the
fixed `class="review-finding"` attribute shown in the example; other HTML or
attributes are not supported. Review visuals go on their own line as
`<!-- review-visual:key -->`, outside the copy markers. Legacy Markdown
blockquotes and tables remain readable, but only explicit markers create copy
controls.

## Final consistency pass

- Scan the report with findings collapsed: the changed behavior, assessment,
  material limitations and finding titles should give a clear route through the
  review. Then open each finding: its problem sentence, walkthrough and proposed
  action should be understandable without opening detailed evidence. Cut
  repetition and optional background before reducing context, caveats or
  supported findings.
- The assessment and every draft express the same current conclusion.
- Each finding's walkthrough, consequence, “Is it real?” and fix agree with its
  evidence and draft. The expected result has a checked basis; illustrative and
  source-traced behavior is not presented as observed output.
- Every sketch passes the fix-sketch rules above, and every suggested test would
  catch the regression where it is placed.
- Every default defect draft has a demonstrated scenario and a checked
  remediation direction. Unknown deployment facts remain unknown.
- Scope and previous discussion have been considered: every finding raised in
  an existing thread is marked Already discussed with its link, and no draft
  repeats an existing comment. Superseded and rejected candidates appear only
  in the verification/history artifact.
- Links identify the pinned source; placement is exact or explicitly general.
- Validation claims match observed results and revisions. Screenshots show the
  stated view/state, exist outside the disposable checkout, and have useful
  captions. Partial app coverage and unavailable checks remain explicit.
- Comments contain no review metadata or invented personal claims, and each
  asks about one concern. Read them aloud against the voice examples.
- Run `python3 scripts/validate_review_notes.py /absolute/path/review.md`.
  Automated checks supplement this pass and the fact-check stage; they cannot
  judge code or voice.
