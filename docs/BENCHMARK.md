# Benchmark: agent-written tests vs human-written tests

Do the tests that come with AI-agent PRs catch bugs as well as the tests that come with human PRs? catchscore scored 568 merged PRs: 300 by agents and 268 human PRs from the same repositories over the same period. Raw results are in [`bench/results/`](../bench/results/) (`agent-*.jsonl`, `human-*.jsonl`). The numbers below come from [`bench/analyze.py`](../bench/analyze.py).

**Short answer: no evidence either way.** A raw comparison makes agent tests look worse, but that comes from human PRs being smaller. Compared at the same size, agent tests did slightly better, and the difference is not significant.

## Setup

Same harness and settings as the [pilot](BENCHMARK_PILOT.md):
- each PR runs on its own disposable GitHub Actions runner;
- its head commit is mutated only on the lines it changed;
- it is tested only with the test files it added or changed;
- at most 40 mutants per PR.

- **Agent PRs:** 300 sampled at random from merged agent PRs that change both Python source and Python tests.
- **Human PRs:** for each repository in the agent sample, the same number of merged PRs created after 2026-07-01 that change Python source and tests, whose author isn't a bot and whose description and commits don't mention an AI tool. That means "no AI use disclosed", not "certainly written without AI" ([`bench/select_human.py`](../bench/select_human.py)).
- **Timeouts:** 12 PRs (vLLM and Ray) hit the 35-minute job limit and have no result.

| | Agent | Human |
|---|---|---|
| Results | 294 | 262 |
| **Scored** | **114** (61 repos) | **100** (60 repos) |
| Could not run (services, browsers or dependencies a generic install can't guess) | 118 | 73 |
| Nothing to mutate on the changed lines | 40 | 60 |
| Tests ran but none actually executed | 22 | 29 |

## Results

| Share of injected bugs that survived | Agent | Human |
|---|---|---|
| Pooled over all injected bugs | 26.8% (627 of 2,338) | 32.6% (511 of 1,566) |
| Median per PR | 18.5% | 11.0% |
| Median per PR, PRs with 10+ mutants | **20.0%** (73 PRs) | **27.5%** (49 PRs) |
| Median per PR, PRs with 20+ mutants | 20.0% (54 PRs) | 30.4% (32 PRs) |

About half the surviving bugs were on lines no test runs at all: 299 of 627 for agents and 261 of 511 for humans.

**The headline medians point in opposite directions, and PR size explains why.** Human PRs are about half as large (median 9 mutants against 16.5), and 51 of the 100 scored human PRs had fewer than 10. A small change with three mutants easily scores 0%, and 46 human PRs did, against 26 agent PRs. Once small PRs are set aside, agent tests let fewer bugs through, not more.

**None of these differences is significant:**
- difference in the per-PR median: +7.5 points (agent minus human), 95% bootstrap CI −3.2 to +20.0;
- difference in the pooled rate: −5.8 points, 95% CI −15.5 to +3.9;
- same repository, PRs with 10+ mutants on both sides: agent tests did worse in 9 of 23 repositories and better in 13 (sign test p = 0.52).

Across all sizes, the same-repository comparison favours humans: agents were worse in 27 repositories, better in 12, and tied in 9 (p = 0.02). But that comparison mixes PR sizes in the same way, so it isn't evidence that agent tests are weaker.

**Test-integrity flags don't separate the two groups either.** "Expected value changed in an existing test" appeared 43 times in agent PRs against 14 in human PRs, but those come from a few PRs. By PR, 9 of 176 agent PRs that ran have the flag, against 7 of 189 human PRs (Fisher p = 0.61).

## What this does and doesn't show

- **The useful number is per PR, not per author type.** About one scored PR in three, on both sides, lets more than a quarter of injected bugs through: 37 of 114 agent PRs and 35 of 100 human PRs. That spread is the case for running catchscore on each PR, whoever wrote it.
- **This is a filtered sample.** These PRs were merged into popular projects with reviewers and CI. Agent PRs that were rejected, and agent code that never becomes a public PR, aren't here.
- **"Human" means "no AI use disclosed".** Some of those PRs were probably written with AI help.
- **Selection by runnability.** Only 214 of 556 results could be scored, and runnable projects skew towards self-contained ones. The 40-mutant cap means large changes were only partly scored, and 32 agent PRs and 20 human PRs reached it.
- **Survival here is an upper bound on "missed bugs".** Some mutants don't change behaviour (equivalent mutants), so a 0% target isn't realistic.

## Cost

About 3.5 runner-minutes per PR, run on public-repository runners at no cost.
