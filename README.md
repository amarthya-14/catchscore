# catchscore

**Would your tests catch a bug in what just changed?**

AI coding agents write code faster than anyone can review it, and they write the tests too. Those tests usually pass. What rarely gets checked is whether they would *fail* if the code were wrong.

catchscore checks this directly. It injects small, realistic bugs into the lines you just changed, runs your tests against each one, and tells you which bugs your tests would let through. With `--suggest`, Claude writes tests for those gaps, and catchscore only keeps the ones it has run and verified.

```
$ catchscore
catchscore: would your tests catch a bug in what just changed?

Injected 16 small bugs into the changed lines. Tests caught 2 (12%).

Your tests would NOT notice these bugs:
  shop.py:12  `>` -> `>=`
  shop.py:12  `and` -> `or`
  shop.py:15  `/` -> `*`
  ...

Test changes worth a second look:
  tests/test_shop.py: new test only checks that something came back: test_discount_returns_a_number
  tests/test_shop.py: new test checks nothing: test_discount_runs

$ catchscore --suggest
...
Suggested tests in .catchscore/test_catchscore_shop.py pass on your code and catch 14 of those 14 bugs.
```

## Why this matters

- **Review is the bottleneck now.** In a 2026 study of 718 companies, AI raised pull requests by 23% with no measurable increase in deployed work. Time from opening a PR to merging it rose 49%.
- **"Almost right" is the top complaint.** 66% of developers name AI output that is "almost right, but not quite" as their biggest frustration (Stack Overflow 2025).
- **Agents game their own tests.** On benchmarks, stronger models special-case test inputs or edit the tests more often (ImpossibleBench, EvilGenie). On Hacker News, the most-cited complaint is AI-written tests that "asserted that the defective behavior was correct".
- **Coverage doesn't measure this.** A test can run every line and check nothing. Mutation testing measures whether tests actually *detect* wrong behaviour, which is what a reviewer needs to know.

## What it found on real code

Pathlight's commit `2c68c02` was written with Claude Code and adds the logic that decides which skills a tailored resume may claim. Its tests caught **21 of 47 (45%)** injected bugs.

For example, `not has_skill(..., implied=False) and has_skill(...)` → `or` would let the resume claim skills the candidate doesn't have, and no test notices. One `catchscore --suggest` run produced verified tests that catch all 13 survivors in that module, raising the commit's catch rate from 45% to 72%. The details and the method are in [docs/EVIDENCE.md](docs/EVIDENCE.md). The same document covers a scan of 1,297 merged agent PRs from 136 popular repositories. That scan explains why catchscore runs your tests instead of judging diffs: diffs alone mostly produce false alarms.

Across 214 merged PRs in about 60 popular Python projects, the tests that came with each change let a median of 17% of injected bugs through. About a third of PRs let through more than a quarter. Agent-written and human-written PRs from the same projects did about equally well once PR size is taken into account. The spread between PRs is much larger than the difference between agents and people. See [docs/BENCHMARK.md](docs/BENCHMARK.md).

## Install and use

```bash
pip install -e .            # not on PyPI yet
catchscore                  # uncommitted changes vs HEAD
catchscore --base main      # everything on this branch
catchscore --suggest        # also ask Claude for tests that close the gaps (needs the `claude` CLI)
catchscore --min-score 80   # exit 1 below 80%, for CI or an agent's definition of done
catchscore --json           # machine-readable report
```

Use `--repo backend` for a subdirectory of a monorepo. If your tests need a specific interpreter or test files, pass them with `--pytest "path/to/python -m pytest tests/test_x.py"`.

## With coding agents

- **Claude Code:** copy [`integrations/claude-code/commands/catchscore.md`](integrations/claude-code/commands/catchscore.md) to `.claude/commands/`, then run `/catchscore` after a change.
- **Codex, Cursor and other agents:** add [`integrations/AGENTS.md`](integrations/AGENTS.md) to your `AGENTS.md`.

Either way, the agent gets a concrete definition of done: name the bugs your tests miss, and fix them without weakening any existing test.

## How it works

1. **Diff.** `git diff` gives the changed line numbers. Untracked new files count as fully changed.
2. **Mutate.** It parses each changed Python file and creates one mutant per mutable spot on a changed line:
   - comparison flips (`<` / `<=`, `==` / `!=`, `in` / `not in`)
   - arithmetic swaps
   - `and` / `or`
   - dropping a `not`
   - number and boolean changes
   - `return x` → `return None`
   - negated `if` / `while` conditions
3. **Run.** It copies the project to a scratch directory, never touching your working tree. Your tests run once to confirm they pass, recording which tests run each changed line. Then each mutant is tested against only those tests. A mutant is *caught* if the tests fail or time out. Mutants that no test even reaches are reported separately, without running anything.
   - **Fast path (macOS and Linux, Python 3.11+).** pytest collects and imports your project once. Each mutant then runs in a forked child with the mutated function's code swapped in memory, so imports aren't paid again per mutant.
   - **Fresh process instead.** Mutants in code that runs at import time, or in code a test runs in another process, are run from disk in a fresh process. So is anything the fast path can't apply, or a child that crashes. `--no-select` runs every mutant this way, against the whole test command.
4. **Integrity.** Conservative checks on test diffs flag tests that were deleted (not moved), skipped unconditionally, changed to expect a different value, or that assert nothing (or only `is not None`).
5. **Suggest.** Claude gets the module, the existing tests and the surviving bugs, and writes new tests. The file is accepted only if it **passes on the current code** and **fails on at least one surviving mutant**. Rejected files are kept in `.catchscore/` along with the reason.

On Pathlight's whole suite (219 tests), scoring a 47-bug commit took 245 s with `--jobs 4`, down from 623 s with one process per bug, with identical results (details in [docs/EVIDENCE.md](docs/EVIDENCE.md)).

## Limitations

- Python and pytest only, for now.
- Some mutants are *equivalent*: they don't change behaviour, so no test could catch them. A score of 100% isn't always possible, so treat survivors as questions, not verdicts.
- Runtime is roughly the time of the tests that reach each mutated line, per mutant. Use `--jobs` to run mutants in parallel and `--max-mutants` to cap a run. With `--jobs`, tests that share a real database, port or fixed file path can interfere; the forked fast path isolates in-memory state but not those.
- Test selection assumes your tests don't depend on running in a particular order. If a test only passes after another test has run, running it on its own fails, and a bug would count as caught when it wasn't. [pytest-randomly](https://github.com/pytest-dev/pytest-randomly) finds such tests; `--no-select` avoids the problem.
- Suggested tests are checked against the code as it is now, so a test can lock in a bug that's already there. Passing on today's code proves the test catches the injected bugs, not that the current behaviour is right. Read them before keeping them.
- `--suggest` sends the changed module and its tests to Claude through your Claude Code CLI.

## Related work

catchscore puts together known ideas; it doesn't invent them. What it adds is a Python CLI aimed at checking an agent's change locally before it's pushed, and a verification step that throws away any suggested test it hasn't run and seen catch a bug.

- **Diff-scoped mutation testing.** [Google](https://arxiv.org/abs/2102.11378) shows surviving mutants in code review. The [python-mutation-report](https://github.com/marketplace/actions/python-mutation-report) GitHub Action runs mutmut on a PR's changed lines. [Tautest](https://www.hunted.space/dashboard/tautest) does the same for JavaScript with StrykerJS.
- **Mutation testing tools.** [mutmut](https://github.com/boxed/mutmut) and [cosmic-ray](https://github.com/sixty-north/cosmic-ray) for Python, [Stryker](https://stryker-mutator.io/) for JavaScript and .NET, [PIT](https://pitest.org/) for Java. They're more thorough on whole projects, and catchscore's operators are a small subset of theirs.
- **Using surviving mutants to guide LLM-written tests.** Meta's [ACH](https://dl.acm.org/doi/10.1145/3696630.3728544): engineers accepted 73% of its generated tests. [MUTGEN](https://arxiv.org/abs/2506.02954) puts mutation feedback into the prompt.
- **Agent skills.** Several Claude Code skills have the agent work through surviving mutants ([agentic-qe](https://openskillindex.com/skills/proffesor-for-testing-agentic-qe-mutation-testing), [claude-swe-workflows](https://openskillindex.com/skills/chrisallenlane-claude-swe-workflows-test-mutation)). Those let the model decide when it's done; catchscore decides by running the tests.

## Roadmap

- A GitHub Action that comments the score and survivors on each PR.
- JavaScript and TypeScript support (Jest and Vitest).
- The benchmark beyond Python, and on agent changes that were never merged.
- A small fine-tuned model to rank survivors by how much they matter.
