#!/usr/bin/env bash
# Score one merged PR inside a disposable CI runner (never on a personal machine: it runs the
# project's own tests). Usage: score_pr.sh OWNER/REPO PR_NUMBER OUT.json
set -uo pipefail
repo="$1"; pr="$2"; out="$3"
work="$(mktemp -d)"; cd "$work"
meta=$(gh api "repos/$repo/pulls/$pr") || exit 0
base=$(jq -r .base.sha <<<"$meta"); merge=$(jq -r .merge_commit_sha <<<"$meta")
git clone -q --filter=blob:none "https://github.com/$repo" src && cd src || exit 0
git checkout -q "$merge" || exit 0
# The PR's changes are merge_commit vs its first parent (base at merge time), not vs .base.sha.
parent=$(git rev-parse "$merge^1")
python -m venv .bench-venv && . .bench-venv/bin/activate
pip install -q pytest "$CATCHSCORE_SRC" >/dev/null
# Best-effort dependency install; projects that need services or exotic setups are skipped.
(pip install -q -e ".[test]" || pip install -q -e ".[dev]" || pip install -q -e . || \
 { [ -f requirements.txt ] && pip install -q -r requirements.txt; }) >/dev/null 2>&1 || { echo '{"skipped":"install"}' > "$out"; exit 0; }
# The headline is about the tests that came with the change, and whole suites of projects like
# transformers don't fit a runner: run the test files this PR added or changed.
tests=$(git diff --name-only --diff-filter=AM "$parent" "$merge" -- '*.py' \
        | grep -E '(^|/)(test_[^/]*|[^/]*_test)\.py$' | tr '\n' ' ')
[ -n "$tests" ] || { echo "{\"repo\":\"$repo\",\"pr\":$pr,\"skipped\":\"no test files\"}" > "$out"; exit 0; }
timeout 1500 catchscore --json --base "$parent" --max-mutants 40 --jobs 2 --pytest "python -m pytest $tests" \
  > "$out.tmp" 2>"$out.err" \
  && jq --arg repo "$repo" --argjson pr "$pr" --arg tests "$tests" '. + {repo: $repo, pr: $pr, tests: $tests}' \
     "$out.tmp" > "$out" \
  || echo "{\"repo\":\"$repo\",\"pr\":$pr,\"skipped\":\"baseline or timeout\"}" > "$out"
