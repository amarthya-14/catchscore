"""Pick merged agent PRs to score and look up the commits each needs, so the CI jobs need no token.

    python bench/select.py study/prs.jsonl bench/pilot.json --n 30 --per-repo 2

Keeps PRs that change both Python source and Python tests. Samples at random (fixed seed) with at
most --per-repo PRs per repository, so a few big projects don't dominate.
"""

import argparse
import json
import random
import subprocess
import sys


def main():
    p = argparse.ArgumentParser()
    p.add_argument("prs")
    p.add_argument("out")
    p.add_argument("--n", type=int, default=30)
    p.add_argument("--per-repo", type=int, default=2)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    prs = [json.loads(line) for line in open(args.prs)]
    usable = [pr for pr in prs if pr["src_files"] and any(t["status"] != "removed" for t in pr["test_files"])]
    random.Random(args.seed).shuffle(usable)
    picked, per_repo = [], {}
    for pr in usable:
        if len(picked) == args.n:
            break
        if per_repo.get(pr["repo"], 0) >= args.per_repo:
            continue
        api = subprocess.run(["gh", "api", f"repos/{pr['repo']}/pulls/{pr['number']}",
                              "--jq", "{head: .head.sha, base: .base.sha, merged: .merged}"],
                             capture_output=True, text=True)
        if api.returncode != 0:
            print(f"skip {pr['url']}: {api.stderr.strip()[:100]}", file=sys.stderr)
            continue
        shas = json.loads(api.stdout)
        if not shas["merged"]:
            continue
        per_repo[pr["repo"]] = per_repo.get(pr["repo"], 0) + 1
        picked.append({"repo": pr["repo"], "pr": pr["number"], "head": shas["head"], "base": shas["base"],
                       "stars": pr["stars"], "group": "agent"})
    json.dump(picked, open(args.out, "w"), indent=1)
    print(f"{len(picked)} PRs from {len(per_repo)} repositories (of {len(usable)} usable)", file=sys.stderr)


if __name__ == "__main__":
    main()
