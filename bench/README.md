# Benchmark: how many injected bugs survive AI agents' own tests?

Draft harness for the week-2 measurement. Each job scores one merged agent PR from
`agent-test-audit/data/prs.jsonl` inside a disposable GitHub Actions runner, because it has to run that
project's tests. Results are aggregated into: catch score distribution, survivors per changed line,
and a comparison with human-written PRs from the same repositories.

Not run yet: it needs a GitHub repository to host the workflow (a decision for the owner).
