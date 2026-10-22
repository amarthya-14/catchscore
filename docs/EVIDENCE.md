# What real agent pull requests show

Before building catchscore I checked whether the problem is real, using merged pull requests from popular open-source Python projects. These notes record what was measured, how, and what it changed about the tool.

## Dataset

- **1,297 merged pull requests** from **136 Python repositories with 500+ stars** (pydantic-ai, reflex, agno, fastmcp, vllm, transformers, pytorch, AutoGPT, litellm, langflow and others).
  - All were created after July 2026 and all change at least one Python test file.
  - 1,277 carry the "Generated with Claude Code" marker. 17 were opened by GitHub's Copilot coding agent.
- Collected read-only through the GitHub API ([`agent-test-audit/collect_popular.py`](../../agent-test-audit/collect_popular.py)). No code from these repositories was downloaded or run.

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

The same pattern appears in the demo project (`examples/make_demo.sh`): the agent's tests caught 2 of 16 injected bugs, and the verified tests from `--suggest` caught all 14 that had survived.

## What would make this a stronger study (next steps)

- **Run mutation testing on the 1,120 real PRs that change both source and tests.** This needs a sandbox (GitHub Actions or a container) because it runs other people's code. The headline would be "X% of bugs injected into agent-written changes survive the agent's own tests", a number no vendor has published.
- Compare agent-written and human-written PRs in the same repositories, as a baseline.
- Have a second person label the manual-review sample to measure agreement.
