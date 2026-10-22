#!/usr/bin/env bash
# Score one merged PR inside a disposable CI runner (never on a personal machine: it runs the
# project's own tests). Usage: score_pr.sh OWNER/REPO PR_NUMBER HEAD_SHA BASE_SHA OUT.json
# Needs: git, jq, uv, and CATCHSCORE_SRC pointing at a checkout of catchscore. Uses no token.
set -uo pipefail
repo="$1"; pr="$2"; head="$3"; base="$4"; out="$5"
started=$SECONDS
work="$(mktemp -d)"
install_log="$work/install.log"; touch "$install_log"
proj=.; py=
result() {  # result STAGE DETAIL: record why this PR was not scored
  jq -n --arg repo "$repo" --argjson pr "$pr" --arg stage "$1" --arg detail "$(tail -c 2500 <<<"$2")" \
     --arg install "$(tail -c 1500 "$install_log")" --arg proj "$proj" --arg py "$py" \
     --argjson secs $((SECONDS - started)) \
     '{repo: $repo, pr: $pr, skipped: $stage, detail: $detail, install_tail: $install, project_dir: $proj,
       python: $py, seconds: $secs}' > "$out"
  exit 0
}

# The PR exactly as its author left it: its head commit, diffed against where it branched off.
git init -q "$work/src" && cd "$work/src"
git remote add origin "https://github.com/$repo"
git fetch -q --filter=tree:0 origin "pull/$pr/head" "$base" 2>"$work/fetch.err" || result fetch "$(cat "$work/fetch.err")"
git checkout -q "$head" || result checkout "head $head missing"
fork=$(git merge-base "$head" "$base") || result checkout "no merge base"

# The headline is about the tests that came with the change, and whole suites of projects like
# transformers don't fit a runner: run the test files this PR added or changed.
tests=$(git diff --name-only --diff-filter=AM "$fork" "$head" -- '*.py' | grep -E '(^|/)(test_[^/]*|[^/]*_test)\.py$')
[ -n "$tests" ] || result tests "no test files added or changed"

# Monorepos: work from the nearest folder above the first test file that has its own project file.
d=$(dirname "$(head -1 <<<"$tests")")
while [ "$d" != "." ]; do
  if [ -f "$d/pyproject.toml" ] || [ -f "$d/setup.py" ] || [ -f "$d/setup.cfg" ]; then proj="$d"; break; fi
  d=$(dirname "$d")
done
cd "$proj"
if [ "$proj" != "." ]; then
  tests=$(grep "^$proj/" <<<"$tests" | sed "s#^$proj/##")
  [ -n "$tests" ] || result tests "test files are outside $proj"
fi
tests=$(tr '\n' ' ' <<<"$tests")

# Everything we create lives outside the checkout: catchscore treats untracked files as changed.
py=$(head -1 .python-version 2>/dev/null || head -1 "$work/src/.python-version" 2>/dev/null || true)
py=${py:-3.12}
uv venv -q --seed --python "$py" "$work/venv" >>"$install_log" 2>&1 || result install "could not create a Python $py venv"
. "$work/venv/bin/activate"
uv pip install -q pytest "$CATCHSCORE_SRC" >>"$install_log" 2>&1 || result install "could not install catchscore"
# Best effort for the project itself: whichever of these exist. Failures show up as a failing baseline.
{
  uv pip install -q -e ".[test]" || uv pip install -q -e ".[tests]" || uv pip install -q -e ".[dev]" ||
    uv pip install -q -e . || true
  uv pip install -q --group dev || uv pip install -q --group test || true
  for r in requirements.txt requirements-dev.txt requirements-test.txt requirements_test.txt test-requirements.txt; do
    if [ -f "$r" ]; then uv pip install -q -r "$r" || true; fi
  done
} >>"$install_log" 2>&1

timeout 1500 catchscore --json --base "$fork" --max-mutants 40 --jobs 2 --pytest "python -m pytest $tests" \
  > "$work/score.json" 2>"$work/score.err"
code=$?
[ $code -eq 124 ] && result timeout "catchscore ran over 25 minutes"
[ $code -eq 0 ] || result run "exit $code: $(cat "$work/score.err")"
jq --arg repo "$repo" --argjson pr "$pr" --arg tests "$tests" --arg proj "$proj" --arg py "$py" \
   --argjson secs $((SECONDS - started)) \
   '. + {repo: $repo, pr: $pr, tests: $tests, project_dir: $proj, python: $py, total_seconds: $secs}' \
   "$work/score.json" > "$out"
