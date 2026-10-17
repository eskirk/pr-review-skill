# Agent instructions

- Read [README.md](README.md) for what the dashboard does and
  [docs/development.md](docs/development.md) for setup, tests and recovery.
  [SKILL.md](SKILL.md) is the review skill itself.
- Run the relevant suites with `python3 tests/run.py python|javascript|browser`
  before handing work back, and say which ones you ran.

## Changelog

Update [CHANGELOG.md](CHANGELOG.md) in the same change whenever you add,
change, fix or remove something a user or reviewer would notice:

- Each pull request has its own section, newest first:
  `## #21 · Short title (unreleased)`. Create it when the pull request exists;
  when it merges, replace `(unreleased)` with `· <merge day>` (`· 2026-10-17`).
- Changes committed to `main` without a pull request go under
  `## <day> · no pull request`.
- One plain-words line per change, describing the effect rather than the
  implementation; start a fix with `Fixed:`.
- Skip internal refactors, test-only and CI-only changes.
