"""Agent vs human benchmark: python3 bench/analyze.py [bench/results]

Same categories as docs/BENCHMARK_PILOT.md. Survival = share of injected bugs the PR's own
tests didn't catch. Human PRs are smaller, so compare at equal size (the >= 10 mutant rows)."""
import json, random, statistics, sys, collections
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "results")
def load(names):
    rows = []
    for n in names:
        rows += [json.loads(l) for l in open(root / f"{n}.jsonl")]
    return rows

def classify(r):
    if r.get("skipped"):
        return "could not run"
    b = r.get("baseline_tests") or {}
    if r.get("injected", 0) == 0:
        return "nothing to mutate"  # catchscore stops before the baseline run (pilot: "no mutable changed lines")
    if not b.get("passed"):
        return "no tests ran"
    return "scored"

groups = {"agent": load(["agent-1", "agent-2"]), "human": load(["human-1", "human-2"])}
scored = {}
for g, rows in groups.items():
    c = collections.Counter(classify(r) for r in rows)
    s = [r for r in rows if classify(r) == "scored"]
    scored[g] = s
    inj = sum(r["injected"] for r in s); caught = sum(r["caught"] for r in s)
    surv = [100 - r["score"] for r in s]
    notrun = sum(1 for r in s for x in r["survivors"] if x["reason"] == "not run by any test")
    integ = sum(1 for r in rows if r.get("integrity"))
    print(f"\n== {g}: {len(rows)} results  {dict(c)}")
    print(f"  pooled: caught {caught}/{inj} = {100*caught/inj:.1f}%  survived {inj-caught} ({notrun} on lines no test runs)")
    print(f"  per-PR survival: median {statistics.median(surv):.1f}%  mean {statistics.mean(surv):.1f}%")
    b = collections.Counter("0%" if x == 0 else "1-10%" if x <= 10 else "11-25%" if x <= 25 else "26-50%" if x <= 50 else ">50%" for x in surv)
    print("  buckets:", {k: b[k] for k in ["0%", "1-10%", "11-25%", "26-50%", ">50%"]})
    print(f"  PRs with an integrity flag: {integ}")
    print("  repos scored:", len({r['repo'] for r in s}))

# Difference in median per-PR survival, bootstrap over PRs (resampling repos would be stricter).
rng = random.Random(0)
a = [100 - r["score"] for r in scored["agent"]]; h = [100 - r["score"] for r in scored["human"]]
def pooled(rows): return 100 * sum(r["injected"] - r["caught"] for r in rows) / sum(r["injected"] for r in rows)
diffs_med, diffs_pool = [], []
for _ in range(5000):
    ra = [rng.choice(scored["agent"]) for _ in scored["agent"]]; rh = [rng.choice(scored["human"]) for _ in scored["human"]]
    diffs_med.append(statistics.median([100 - r["score"] for r in ra]) - statistics.median([100 - r["score"] for r in rh]))
    diffs_pool.append(pooled(ra) - pooled(rh))
for name, d, point in (("median survival", diffs_med, statistics.median(a) - statistics.median(h)),
                       ("pooled survival", diffs_pool, pooled(scored["agent"]) - pooled(scored["human"]))):
    d.sort(); print(f"\nagent - human {name}: {point:+.1f} pts, 95% CI [{d[125]:+.1f}, {d[4875]:+.1f}]")

# Same-repo comparison: repos with scored PRs on both sides.
by = collections.defaultdict(lambda: {"agent": [], "human": []})
for g in scored:
    for r in scored[g]: by[r["repo"]][g].append(100 - r["score"])
both = {k: v for k, v in by.items() if v["agent"] and v["human"]}
wins = sum(1 for v in both.values() if statistics.mean(v["agent"]) > statistics.mean(v["human"]))
ties = sum(1 for v in both.values() if statistics.mean(v["agent"]) == statistics.mean(v["human"]))
print(f"\nrepos scored on both sides: {len(both)}; agent tests let more bugs survive in {wins}, fewer in {len(both)-wins-ties}, tie {ties}")
d = [statistics.mean(v["agent"]) - statistics.mean(v["human"]) for v in both.values()]
print(f"  within-repo difference (agent - human): median {statistics.median(d):+.1f} pts, mean {statistics.mean(d):+.1f}")

from math import comb
n = len(both) - ties; k = wins
p = 2 * sum(comb(n, i) for i in range(max(k, n - k), n + 1)) / 2 ** n
print(f"  sign test (ties dropped): {k} of {n}, two-sided p = {min(p, 1):.3f}")

print("\nsize (mutants injected per scored PR):")
for g in scored:
    inj = [r["injected"] for r in scored[g]]
    print(f"  {g}: median {statistics.median(inj)}, at the 40 cap {sum(i >= 40 for i in inj)}, under 10 {sum(i < 10 for i in inj)}")
for cut in (10, 20):
    print(f"PRs with >= {cut} mutants:")
    for g in scored:
        s = [100 - r["score"] for r in scored[g] if r["injected"] >= cut]
        print(f"  {g}: n={len(s)}, median survival {statistics.median(s):.1f}%, pooled {pooled([r for r in scored[g] if r['injected'] >= cut]):.1f}%")

big = collections.defaultdict(lambda: {"agent": [], "human": []})
for g in scored:
    for r in scored[g]:
        if r["injected"] >= 10: big[r["repo"]][g].append(100 - r["score"])
bb = [v for v in big.values() if v["agent"] and v["human"]]
w = sum(statistics.mean(v["agent"]) > statistics.mean(v["human"]) for v in bb)
l = sum(statistics.mean(v["agent"]) < statistics.mean(v["human"]) for v in bb)
n = w + l; p = 2 * sum(comb(n, i) for i in range(max(w, l), n + 1)) / 2 ** n if n else 1
print(f"\nsame repo, PRs with >= 10 mutants: {len(bb)} repos; agent worse in {w}, better in {l}; sign test p = {min(p, 1):.2f}")
