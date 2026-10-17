# Review and explanation practices

Research checked 2026-09-15; presentation research updated 2026-10-17. Use these decisions in the workflow; this is not a
leaderboard or evidence that any public skill is universally best. Browse again
when a review depends on an uncertain or changing external API or contract.

## Local AI review

- [Anthropic's code-review command](https://github.com/anthropics/claude-code/blob/main/plugins/code-review/commands/code-review.md)
  uses independent reviewer passes, a separate validation step, scoped repository
  guidance and deduplication. Adopt those patterns. Its intentionally narrow
  diff-only/input-independent bug criteria would miss reachable edge cases;
  this skill also traces callers, guards, state and contracts. Keep its findings
  threshold focused on evidence rather than a desired number of comments.
- [Anthropic's security review approach](https://www.anthropic.com/news/claude-code-security)
  describes trying to prove or disprove candidate vulnerabilities to reduce
  false positives. Apply this to all candidate defects: seek a counterexample
  or existing protection before recommending a comment. Confidence is a triage
  signal, not a measured probability.
- [Superpowers requesting-code-review](https://github.com/obra/superpowers/blob/main/skills/requesting-code-review/SKILL.md)
  packages review around explicit requirements and base/head context. Preserve
  that exact comparison contract. Its implementation-oriented follow-up loop
  is not authorization to modify another author's PR in this read-only workflow.
- [Google's review guidance](https://google.github.io/eng-practices/review/reviewer/looking-for.html)
  covers design, behavior, complexity, tests and surrounding context, including
  every assigned line. This motivates the coverage inventory and scrutiny of
  test assertions, not just successful test execution. Consider design and
  maintainability; distinguish a demonstrated defect or relevant optional
  improvement from personal style preferences.

Do not import another skill wholesale or copy its vendor/model restrictions,
auto-posting steps, or assumptions about access. Use the existing sandbox and
permissions, and keep final verification independent of reviewer agreement.

## Help a colleague understand the change

- [GitHub: helping others review changes](https://docs.github.com/en/pull-requests/concepts/helping-others-review-your-changes)
  recommends clear problem, approach and result context and directing attention
  to important areas. Start there, then give a short route through the mechanism.
- [Google: writing change descriptions](https://google.github.io/eng-practices/review/developer/cl-descriptions.html)
  distinguishes a short summary from the detail needed to understand what and
  why. Apply progressive detail: a visible outcome and example, then exact code,
  then optional background. Do not infer undocumented author motivation as fact.

Our presentation is a single scrolling page that leads with the claim: a title
and standfirst, an At a glance strip, optional background, one section on the
change with a diagram only when it fits the change kind, code shown inline, the
blast radius, then findings ([Explanation](explanation.md)). The evidence behind
it, all from learning or web-reading studies rather than PR-report trials:

- Mayer's multimedia principles: cutting extraneous material
  ([coherence and signaling](https://www.cambridge.org/core/books/abs/cambridge-handbook-of-multimedia-learning/principles-for-reducing-extraneous-processing-in-multimedia-learning-coherence-signaling-redundancy-spatial-contiguity-and-temporal-contiguity-principles/C98AB3A6CE760DD63C048936EA0B3B44)),
  naming key concepts before the mechanism, and meaningful segments
  ([pre-training and segmenting](https://cambridge.org/core/books/cambridge-handbook-of-multimedia-learning/principles-for-managing-essential-processing-in-multimedia-learning-segmenting-pretraining-and-modality-principles/DD24C2F48B9B1277CE59F78276110258))
  each improved learning in most tests. Hence no repeated layers, claim
  headings, finding badges on diagram steps, and a short glossary only when needed.
- NN/g's [inverted pyramid](https://www.nngroup.com/articles/inverted-pyramid/)
  and [progressive disclosure](https://www.nngroup.com/articles/progressive-disclosure/)
  observations: put the most important point first and avoid more than two
  disclosure levels. Usability observations, not controlled effects.
- [Expertise reversal](https://en.wikipedia.org/wiki/Expertise_reversal_effect):
  guidance that helps novices can hinder experienced readers, so background
  depends on the reader's familiarity with the repository and never explains
  general engineering.
- [Berney & Bétrancourt (2016)](https://archive-ouverte.unige.ch/unige:92234),
  61 studies: a small overall benefit of animation (g = 0.23), seen only for
  realistic animations, not abstract ones such as code diagrams. Diagrams are
  therefore static.
- Experienced programmers check a hypothesis against *beacons*, characteristic
  code lines ([Crosby et al. 2002](https://ppig.org/papers/2002-ppig-14th-crosby/)),
  so excerpts show the guard or changed call, not whole functions.

In a local blind comparison in September 2026 (six PRs, reports by Claude and
Codex, judged by both), a purpose-built diagram, a cases grid and the current
finding format did best; analogies did not help, and fuller explanations
introduced more factual errors, mostly over-broad simplifications, which
motivates the fact-check stage. In October 2026 two rounds compared the walk
layout with the paper layout on four PRs (docs, logic, lifecycle and UI). Round
1 used Claude and Codex judges and was split; the paper variants lost on
accuracy. Round 2 added a writing guide, word caps and an absolute-claim
fact-check, with three blind judges (Claude, Codex, Gemini): paper was
preferred in 7 of 12 judgements and the fact-check closed the accuracy gap. All
three judges preferred one scrolling page to scenes, found motion added nothing,
saw click-through stepping as neutral next to a numbered diagram with every
note visible, wanted code inline and diagrams only where they fit the change,
and penalized glossaries of familiar terms and renamed identifiers. Round 3
(five PRs, three of them new: Swift, a Terraform/Vault monorepo, Android CI)
added a sourced why lead, a familiarity-gated background with a where-it-sits
map, judgment questions and an approach note; all three judges preferred it on
all five PRs, mainly because the why arrived in seconds rather than after
scrolling, and new codebases became legible from the map. They asked to keep
judgment and approach rare, put the deciding condition in the top lines, and
derive file badges from git. Reviewers orient on rationale before inspecting
code ([Code Review as Decision-Making](https://arxiv.org/html/2507.09637v1)),
alternatives and side effects are the hardest rationale to recover
([Al Safwan & Servant 2019](https://people.cs.vt.edu/~khsaf/public/papers/fse19.pdf)),
and advance organizers help most when prior knowledge is low
([Mahar 1992](https://www.ideals.illinois.edu/items/20405)). Treat this
as indicative: judges favor their own model's output, four PRs is a small
sample, and the judges are models, not the people reading the reports.

Keep the current assessment and drafts in the same document so explanation and
review cannot silently describe different revisions or conclusions.

## Evidence for a consumable report

These studies guide presentation choices; none establishes an optimal word count
or proves this HTML layout increases daily PR throughput. Keep this rationale
out of generated reports.

- [Code Review Comprehension (2025)](https://arxiv.org/abs/2503.21455)
  observed ten experienced reviewers across 25 real reviews. Reviewers built
  context before inspecting code and moved opportunistically among activities.
  This supports a short orientation and flexible navigation; it does not establish
  one mandatory reading sequence.
- [Working memory and change ordering (2019)](https://tobiasbaum.github.io/rp/memoryCodeOrderAndReview.pdf)
  studied 50 participants, mostly professionals. Working memory was associated
  with finding defects involving separated code locations; evidence for an effect
  of presentation order was inconclusive. Keeping related claims and excerpts
  together is a reasonable design inference, not a proven speed improvement.
- [Signaling meta-analysis (2018)](https://www.sciencedirect.com/science/article/pii/S1747938X17300581)
  synthesized 103 studies with 12,201 participants and found benefits for retention
  and transfer from cues highlighting relevant structure. Apply cautiously to
  descriptive headings, focused highlighting and consistent labels: these were
  learning studies, not PR-report trials.
- [Segmenting meta-analysis (2019)](https://doi.org/10.1007/s10648-018-9456-4)
  synthesized 56 investigations: meaningful segments improved retention and
  transfer but increased learning time. This motivates coherent sections and
  optional detail, not fragmenting every paragraph into a separate disclosure
  or promising faster reading.
- [Explicit review strategies (2022)](https://doi.org/10.1007/s10664-022-10123-8)
  tested 70 developers, mostly novice reviewers. Checklist benefits depended on
  the task; no strong overall guidance-performance relationship emerged. Keep
  review hints specific and optional. Ease of reading alone is not review quality.

Judge refinements on real use: can the reader explain the behavior, assess a
finding and locate its support without repeated searching? Consider time together
with misunderstandings and missed caveats. Preserve useful thinking time while
reducing repetition, navigation and unnecessary background.
