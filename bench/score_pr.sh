#!/usr/bin/env bash
# Score one merged PR inside a disposable CI runner (never on a personal machine: it runs the
# project's own tests). Usage: score_pr.sh OWNER/REPO PR_NUMBER HEAD_SHA BASE_SHA OUT.json
# Needs: git, jq, uv, and CATCHSCORE_SRC pointing at a checkout of catchscore. Uses no token.
set -uo pipefail
repo="$1"; pr="$2"; head="$3"; base="$4"; out="$5"
started=$SECONDS
result() {  # result STAGE DETAIL: record why this PR was not scored
  jq -n --arg repo "$repo" --argjson pr "$pr" --arg stage "$1" --arg detail "${2:0:2000}" \
     --argjson secs $((SECONDS - started)) '{repo: $repo, pr: $pr, skipped: $stage, detail: $detail, seconds: $secs}' > "$out"
  exit 0
}
work="$(mktemp -d)"; cd "$work"

# The PR exactly as its author left it: its head commit, diffed against where it branched off.
git init -q src && cd src
git remote add origin "https://github.com/$repo"
git fetch -q --filter=tree:0 origin "pull/$pr/head" "$base" 2>"$work/fetch.err" || result fetch "$(cat "$work/fetch.err")"
git checkout -q "$head" || result checkout "head $head missing"
fork=$(git merge-base "$head" "$base") || result checkout "no merge base"

# The headline is about the tests that came with the change, and whole suites of projects like
# transformers don't fit a runner: run the test files this PR added or changed.
tests=$(git diff --name-only --diff-filter=AM "$fork" "$head" -- '*.py' \
        | grep -E '(^|/)(test_[^/]*|[^/]*_test)\.py$' | tr '\n' ' ')
[ -n "$tests" ] || result tests "no test files added or changed"

# Best-effort install. Projects that need services, GPUs or unusual setups are recorded as skipped.
# Everything we create lives outside the checkout: catchscore treats untracked files as changed.
uv venv -q --seed "$work/venv" >/dev/null 2>&1 && . "$work/venv/bin/activate" || result install "venv"
install_log="$work/install.log"
{
  uv pip install -q pytest "$CATCHSCORE_SRC" &&
  { uv pip install -q -e ".[test]" || uv pip install -q -e ".[tests]" || uv pip install -q -e ".[dev]" ||
    uv pip install -q -e . || true; } &&
  { uv pip install -q --group dev || uv pip install -q --group test || true; } 2>/dev/null &&
  for r in requirements.txt requirements-dev.txt requirements-test.txt requirements_test.txt test-requirements.txt; do
    [ -f "$r" ] && uv pip install -q -r "$r"
  done
  true
} >"$install_log" 2>&1 || result install "$(tail -c 1500 "$install_log")"

timeout 1500 catchscore --json --base "$fork" --max-mutants 40 --jobs 2 --pytest "python -m pytest $tests" \
  > "$work/score.json" 2>"$work/score.err"
code=$?
[ $code -eq 124 ] && result timeout "catchscore ran over 25 minutes"
[ $code -eq 0 ] || result run "$(tail -c 1500 "$work/score.err")"
jq --arg repo "$repo" --argjson pr "$pr" --arg tests "$tests" --argjson secs $((SECONDS - started)) \
   '. + {repo: $repo, pr: $pr, tests: $tests, total_seconds: $secs}' "$work/score.json" > "$out"
