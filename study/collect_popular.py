"""Find agent-authored, merged PRs inside popular Python repos and keep those that change tests.

Read-only: GitHub REST API only. Reuses the helpers in collect.py.
"""

import json
import sys
import time
import urllib.parse

from collect import OUT, api, is_test

AGENT_QUERIES = {
    "claude-code": '"Claude Code" is:pr is:merged created:>2026-07-01',
    "copilot-agent": "author:app/copilot-swe-agent is:pr is:merged created:>2026-07-01",
}


def search(q, per_page=100, page=1):
    url = "https://api.github.com/search/{}?" + urllib.parse.urlencode(
        {"q": q, "per_page": per_page, "page": page, "sort": "created", "order": "desc"})
    return url


def popular_python_repos(pages):
    repos = []
    for page in range(1, pages + 1):
        res = api(search("language:python stars:>500 pushed:>2026-10-01", page=page).format("repositories"))
        repos += [(r["full_name"], r["stargazers_count"]) for r in res["items"]]
        time.sleep(2.5)
    return repos


def main(repo_pages):
    seen = {json.loads(l)["url"] for l in OUT.open()} if OUT.exists() else set()
    repos = popular_python_repos(repo_pages)
    stars = dict(repos)
    print(f"{len(repos)} popular Python repos", flush=True)
    kept = 0
    with OUT.open("a") as out:
        # Several repo: qualifiers in one query are OR'ed, which keeps us under the search rate limit.
        for i in range(0, len(repos), 6):
            chunk = [name for name, _ in repos[i:i + 6]]
            scope = " ".join(f"repo:{n}" for n in chunk)
            for agent, q in AGENT_QUERIES.items():
                items = api(search(f"{q} {scope}", per_page=50).format("issues"))["items"]
                time.sleep(2.5)
                for it in items:
                    if it["html_url"] in seen:
                        continue
                    repo = it["repository_url"].split("/repos/")[1]
                    files = api(f"https://api.github.com/repos/{repo}/pulls/{it['number']}/files?per_page=100")
                    tests = [f for f in files if is_test(f["filename"])]
                    if not tests:
                        continue
                    src = [f["filename"] for f in files if f["filename"].endswith(".py") and not is_test(f["filename"])]
                    out.write(json.dumps({
                        "url": it["html_url"], "repo": repo, "stars": stars.get(repo), "number": it["number"],
                        "agent": agent, "title": it["title"],
                        "merged_at": it.get("pull_request", {}).get("merged_at"), "n_files": len(files),
                        "src_files": src,
                        "test_files": [{k: f.get(k) for k in ("filename", "status", "additions", "deletions", "patch")}
                                       for f in tests]}) + "\n")
                    seen.add(it["html_url"])
                    kept += 1
            print(f"repos {i + len(chunk)}/{len(repos)}: kept {kept}", flush=True)
    print(f"done: {kept} new PRs -> {OUT}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
