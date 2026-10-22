# What real agent pull requests show

Before building catchscore I checked whether the problem is real, using merged pull requests from popular open-source Python projects. These notes record what was measured, how, and what it changed about the tool.

## Dataset

- **1,297 merged pull requests** from **136 Python repositories with 500+ stars** (pydantic-ai, reflex, agno, fastmcp, vllm, transformers, pytorch, AutoGPT, litellm, langflow and others).
  - All were created after July 2026 and all change at least one Python test file.
  - 1,277 carry the "Generated with Claude Code" marker. 17 were opened by GitHub's Copilot coding agent.
- Collected read-only through the GitHub API ([`study/collect_popular.py`](../study/collect_popular.py)). No code from these repositories was downloaded or run.

## 1. Looking only at the diff mostly produces noise

A static pass over the test diffs flagged 22% of PRs: tests removed, expected values changed, new tests with no visible assertion, and so on. A manual review of a random sample of 24 flagged PRs found **none that was clearly a weakened test**:

| Signal | Reviewed | What it actually was |
|---|---|---|
| Tests removed | 8 | The feature was removed or redesigned (5), or the tests were rewritten under new names (2). 1 is unclear. |
| Expected value changed | 10 | An intentional behaviour change matching the PR's stated purpose, e.g. "remove CI recap" turned a `POST` into a `DELETE`. |
| New test with no assertion | 6 | The diff cut the test off partway (4), the test asserted via `raise AssertionError` (1), or it was a "does not raise" test (1). |

**Why:** these PRs were merged, so human reviewers had already filtered them. Blatant test tampering is caught in review or never reaches a PR; research benchmarks show it happens inside agent sessions (ImpossibleBench, EvilGenie). That makes it a reviewer-time cost rather than something that ships.

**What changed in catchscore:** the static checks are conservative and secondary. Every finding is phrased as "worth a second look", with the evidence attached.

## 2. Tests that pass but would not catch a bug cannot be seen in a diff

Whether a test would catch a bug only shows up when the code is run with a bug in it. That is what mutation testing does. catchscore therefore leads with it, scoped to the changed lines so it finishes in seconds to minutes, not hours.

## 3. A real agent-written commit: 45% of injected bugs went unnoticed

Pathlight is a solo project with 222 backend tests. Its commit `2c68c02` ("Tailored resume adds implied and user-confirmed skills to raise ATS score") was written with Claude Code and changed 8 files, adding 181 lines.

- catchscore injected **47 small bugs** into the changed lines and ran 5 relevant test files against each. The tests **caught 21 (45%)**.
- **26 bugs survived.** 13 of them are in the logic that decides which skills a tailored resume may claim (`resume_tailor.py` lines 159–185). For example, `not has_skill(..., implied=False) and has_skill(...)` → `or` would let the resume claim skills the candidate does not have, and no test notices. That is the most honesty-critical code in the project.
- The other survivors are in `confirmed_skills_for` (saving newly confirmed skills, deduplication, the 60-skill cap). None of that is tested.

**`--suggest` on this commit:** Claude wrote 8 tests for `resume_tailor.py`, the module with the most survivors. catchscore ran them before accepting them: they pass on the real code and catch **all 13** bugs that had survived in that module. The commit's catch rate rose from **45% to 72%** (34 of 47) after one call. The tests check the honesty rules directly: implied skills vs skills the resume doesn't show, confirmed skills deduplicated, and "never add these" excluding confirmed skills (saved in [`pathlight-case-study/`](pathlight-case-study/)). One test was contrived: a `str` subclass that is falsy, written only to kill one mutant. The prompt now tells the model to skip bugs that need unrealistic inputs and mark them as probably harmless.

**Timing (MacBook Air M2, 8 GB), all with identical results:**

| Tests used | One process per bug (`--no-select`) | Selected tests, forked (default) |
|---|---|---|
| 5 relevant test files, one bug at a time | 181 s | 126 s |
| 5 relevant test files, `--jobs 4` | 123 s | 58 s |
| Whole suite (219 tests), `--jobs 4` | 623 s | 245 s |

On the default path, 40 of the 47 bugs ran in memory, 4 ran in a fresh process (import-time code), and 3 needed no run because no test reaches their line. The whole-suite run catches exactly the same bugs as the hand-picked 5 files, so the 45% figure doesn't depend on that choice. Pathlight's 3 tests that already fail on this commit (unrelated to it) were deselected. The 623 s run overlapped with about a minute of other test runs on the same machine.

The same pattern appears in the demo project (`examples/make_demo.sh`): the agent's tests caught 2 of 16 injected bugs, and the verified tests from `--suggest` caught all 14 that had survived.

## A bug catchscore's own tests found in catchscore

Python reuses cached bytecode when a file's size and modification time (in whole seconds) look unchanged. A mutant like `/ 2` → `/ 3` keeps the file size and is written within the same second as the previous run, so the tests silently ran the *previous* code, and a bug could wrongly "survive" or wrongly be "caught". A test of the suggestion step showed nondeterministic counts, which exposed it. The fix disables the bytecode cache for every test run. A regression test that interleaves harmless and real same-size mutants failed in about half of runs without the fix and passes every time with it. The headline numbers above were re-measured after the fix and did not change. Their test runs take long enough that two rarely land in the same second, but the fast suggestion check was affected.

## What would make this a stronger study (next steps)

- **Run mutation testing on the 1,120 real PRs that change both source and tests.** This needs a sandbox (GitHub Actions or a container) because it runs other people's code. The headline would be "X% of bugs injected into agent-written changes survive the agent's own tests", a measurement I could not find published anywhere.
- Compare agent-written and human-written PRs in the same repositories, as a baseline.
- Have a second person label the manual-review sample to measure agreement.
