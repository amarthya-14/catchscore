# Benchmark: how many injected bugs survive AI agents' own tests?

Scores merged AI-agent PRs from public repositories. Every PR runs in its own disposable GitHub Actions runner, because scoring means running that project's tests. Runners get read-only permissions, no token and no secrets.

- `select.py` samples PRs from [`study/prs.jsonl`](../study/prs.jsonl) and looks up each PR's commits in advance.
- `score_pr.sh` scores one PR:
  1. checks out the PR's head commit;
  2. installs the project as best it can;
  3. runs catchscore against the test files the PR added or changed.
  It records why a PR couldn't be scored when that happens.
- [`.github/workflows/bench.yml`](../.github/workflows/bench.yml) runs it, started manually with a PR list (`-f prs=bench/pilot.json`).
- `results/` holds the collected results. The pilot is written up in [docs/BENCHMARK_PILOT.md](../docs/BENCHMARK_PILOT.md).
