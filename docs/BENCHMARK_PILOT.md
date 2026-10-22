# Benchmark pilot: 30 merged AI-agent PRs

Before scoring hundreds of PRs, a 30-PR pilot checked whether the harness works and roughly what to expect. Each PR ran on a disposable GitHub Actions runner with read-only permissions and no secrets. Raw results are in [`bench/results/pilot.jsonl`](../bench/results/pilot.jsonl).

## Setup

- **Sample.** 30 PRs from 25 repositories, drawn at random (seed 0, at most 2 per repository) from the 1,120 merged agent PRs that change both Python source and Python tests.
- **Code tested.** The PR's head commit, diffed against where it branched off.
- **Tests used.** The test files the PR itself added or changed, i.e. the tests that came with the change.
- **Cap.** At most 40 mutants per PR.

## Results

| | PRs |
|---|---|
| Scored | **13** |
| Could not run (missing services, browsers or dependencies a generic install can't guess) | 11 |
| No mutable changed lines (e.g. only constants or docstrings changed) | 4 |
| Tests ran but none actually executed (all skipped or none collected) | 2 |

**Across the 13 scored PRs, the tests that came with the change caught 306 of 350 injected bugs (87%). 44 survived (13%), and 8 of those were on lines no test runs.**

The spread between PRs matters more than the average:

| Share of injected bugs that survived | PRs |
|---|---|
| 0% | 4 (MCP python-sdk, Resume-Matcher, TheAlgorithms, DeepTutor) |
| 1–10% | 4 (ai-job-search, last30days, litellm, notebooklm-py) |
| 11–25% | 4 (agentscope, ai-job-search, last30days, fastmcp) |
| 40% | 1 (hermes-webui: e.g. four `or` → `and` flips in one route, none noticed) |

Pathlight's commit `2c68c02` (55% survived) would be the worst of these.

## What this does and doesn't show

- **Agent-written tests in popular, well-maintained projects are mostly good.** The median PR let 9% of injected bugs survive. These projects have reviewers and CI, and the PRs were merged, so this is a filtered sample.
- **A minority of PRs have real gaps,** in the 18–40% range. That is the case for running catchscore per PR rather than trusting the average.
- **There is no comparison yet.** Without the same measurement on human-written PRs from the same repositories, it can't say whether agent tests are better or worse than human ones. That comparison is the next step.
- **Selection bias.** Only 13 of 30 PRs could be run, and the runnable ones skew towards self-contained projects. The 40-mutant cap means large changes were only partly scored.

## Bugs the pilot found in catchscore and the harness (all fixed)

1. **Editable installs hid every mutant (catchscore).** catchscore mutates a scratch copy, but `pip install -e .` points imports at the original folder, so no injected bug ever ran. The copy's import roots now go first on `PYTHONPATH`. A regression test was added.
2. **An all-skipped baseline counted as passing (catchscore).** catchscore now reports how many tests passed and how many were skipped, and warns when none ran. Such PRs are left out of the catch rate.
3. **The baseline failed silently (catchscore).** catchscore now shows pytest's output when the tests fail before any mutation.
4. **Harness problems:**
   - install failures were swallowed;
   - the wrong Python version was used;
   - monorepo subfolders weren't handled;
   - a project's own uv index config broke installing catchscore;
   - the runners' small `/tmp` filled up ("Disk quota exceeded", Python exit 120).

## Cost

About 3.5 runner-minutes per PR. Scoring all 1,120 PRs would take about 3,900 minutes.
