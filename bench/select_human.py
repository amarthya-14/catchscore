"""Pick human-written PRs to compare with a sample of agent PRs: same repositories, same period.

    python bench/select_human.py bench/agent.json bench/human.json

For each repository in the agent sample, takes as many merged PRs as the sample has from it,
created after 2026-07-01, that change both Python source and Python tests. A PR counts as
human-written when its author isn't a bot and neither its description nor any of its commit
messages mentions an AI coding tool. People can use AI without saying so, so this means
"no AI involvement disclosed", not "certainly written without AI".
"""

import json
import re
import subprocess
import sys
import time
from collections import Counter

AI = re.compile(r"claude|copilot|cursor|codex|aider|devin|gemini|chatgpt|openai|windsurf|\bjules\b|\bllm\b|\bai[- ]?(generated|assisted)|"
                r"generated with|co-authored-by:.*(bot|ai)\b|🤖", re.I)


def gh(*args):
    for attempt in range(3):
        r = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
        if r.returncode == 0:
            return json.loads(r.stdout)
        if "rate limit" in r.stderr.lower():
            time.sleep(60 * (attempt + 1))
            continue
        raise RuntimeError(r.stderr.strip()[:200])
    raise RuntimeError("rate limited")


def is_test(path):
    name = path.rsplit("/", 1)[-1]
    return path.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def human_prs(repo, want, exclude):
    found = []
    for page in (1, 2, 3):
        q = f"repo:{repo} is:pr is:merged created:>2026-07-01"
        items = gh("-X", "GET", "search/issues", "-f", f"q={q}", "-f", "per_page=50", "-f", f"page={page}",
                   "-f", "sort=created", "-f", "order=desc")["items"]
        time.sleep(2.5)  # search API: 30 requests a minute
        for it in items:
            if it["number"] in exclude or it["user"]["type"] == "Bot" or it["user"]["login"].endswith("[bot]"):
                continue
            if AI.search(f"{it['title']}\n{it.get('body') or ''}"):
                continue
            files = gh(f"repos/{repo}/pulls/{it['number']}/files?per_page=100")
            if not any(is_test(f["filename"]) and f["status"] != "removed" for f in files):
                continue
            if not any(f["filename"].endswith(".py") and not is_test(f["filename"]) for f in files):
                continue
            commits = gh(f"repos/{repo}/pulls/{it['number']}/commits?per_page=100")
            if any(AI.search(c["commit"]["message"]) for c in commits):
                continue
            pr = gh(f"repos/{repo}/pulls/{it['number']}")
            found.append({"repo": repo, "pr": it["number"], "head": pr["head"]["sha"], "base": pr["base"]["sha"],
                          "group": "human"})
            if len(found) == want:
                return found
        if len(items) < 50:
            break
    return found


def main():
    agent = json.load(open(sys.argv[1]))
    want = Counter(a["repo"] for a in agent)
    exclude = {}
    for a in agent:
        exclude.setdefault(a["repo"], set()).add(a["pr"])
    out = []
    for i, (repo, n) in enumerate(want.items(), 1):
        try:
            got = human_prs(repo, n, exclude[repo])
        except RuntimeError as e:
            print(f"{repo}: {e}", file=sys.stderr)
            got = []
        out += got
        print(f"[{i}/{len(want)}] {repo}: {len(got)}/{n}", file=sys.stderr, flush=True)
        json.dump(out, open(sys.argv[2], "w"), indent=1)
    print(f"{len(out)} human PRs for {len(agent)} agent PRs", file=sys.stderr)


if __name__ == "__main__":
    main()
