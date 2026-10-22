# catchscore

**Would your tests catch a bug in what just changed?**

AI coding agents write code faster than anyone can review it, and they write the tests too. Those tests usually pass. The question nobody checks is whether they would *fail* if the code were wrong.

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

For example, `not has_skill(..., implied=False) and has_skill(...)` → `or` would let the resume claim skills the candidate doesn't have, and no test notices. The details and the method are in [docs/EVIDENCE.md](docs/EVIDENCE.md). The same document covers a scan of 1,297 merged agent PRs from 136 popular repositories. That scan explains why catchscore runs your tests instead of judging diffs: diffs alone mostly produce false alarms.

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
3. **Run.** It copies the project to a scratch directory, never touching your working tree. Your tests run once to confirm they pass, then once per mutant. A mutant is *caught* if the tests fail or time out.
4. **Integrity.** Conservative checks on test diffs flag tests that were deleted (not moved), skipped unconditionally, changed to expect a different value, or that assert nothing (or only `is not None`).
5. **Suggest.** Claude gets the module, the existing tests and the surviving bugs, and writes new tests. The file is accepted only if it **passes on the current code** and **fails on at least one surviving mutant**. Rejected files are kept in `.catchscore/` along with the reason.

## Limitations

- Python and pytest only, for now.
- Some mutants are *equivalent*: they don't change behaviour, so no test could catch them. A score of 100% isn't always possible, so treat survivors as questions, not verdicts.
- Runtime is one test run per mutant. Point `--pytest` at the relevant test files, and use `--max-mutants` to cap a run. Planned: running only the tests that cover each changed line, and running mutants in parallel.
- `--suggest` sends the changed module and its tests to Claude through your Claude Code CLI.

## Roadmap

- Coverage-guided test selection and parallel runs, for speed.
- A GitHub Action that comments the score and survivors on each PR.
- JavaScript and TypeScript support (Jest and Vitest).
- A public benchmark: catch scores of agent-written changes across real open-source PRs, measured in a sandbox.
- A small fine-tuned model to rank survivors by how much they matter.
