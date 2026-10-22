# The PR study

Scripts behind the "diffs alone mostly produce false alarms" finding in [docs/EVIDENCE.md](../docs/EVIDENCE.md), and the PR list the benchmark samples from.

- `collect_popular.py` finds merged PRs opened by coding agents ("Generated with Claude Code" in the body, or GitHub's Copilot coding agent) in Python repositories with 500+ stars, created after 2026-07-01. It keeps the PRs that change at least one test file. Read-only GitHub API; uses your `gh` login.
- `collect.py` holds the shared helpers. It writes the full data, including test-file patches, to `study/data/prs.jsonl`. That file isn't committed (19 MB).
- `analyze.py` runs the static checks on those patches.
- `prs.jsonl` is the committed list: 1,297 PRs with file names but no patches. `bench/select.py` samples from it.
