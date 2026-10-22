"""Collect merged, agent-co-authored PRs from real repos that change Python tests.

Read-only: uses the GitHub REST API, never clones or runs code.
"""

import json
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
OUT = Path(__file__).parent / "data" / "prs.jsonl"
MIN_STARS = 50
# python.org builds on macOS ship without CA certs; certifi provides them.
import certifi
CTX = ssl.create_default_context(cafile=certifi.where())


def api(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}",
                                               "Accept": "application/vnd.github+json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                time.sleep(30 * (attempt + 1))
                continue
            raise
    raise RuntimeError(f"rate limited: {url}")


def is_test(path):
    name = path.rsplit("/", 1)[-1]
    return path.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{path}")


def main(queries, pages):
    seen = {json.loads(l)["url"] for l in OUT.open()} if OUT.exists() else set()
    stars_cache = {}
    kept = 0
    with OUT.open("a") as out:
        for q in queries:
            for page in range(1, pages + 1):
                url = "https://api.github.com/search/issues?" + urllib.parse.urlencode(
                    {"q": q, "per_page": 100, "page": page, "sort": "created", "order": "desc"})
                items = api(url)["items"]
                time.sleep(2.5)  # search API: 30 requests/minute
                for it in items:
                    repo = it["repository_url"].split("/repos/")[1]
                    if it["html_url"] in seen:
                        continue
                    if repo not in stars_cache:
                        stars_cache[repo] = api(it["repository_url"]).get("stargazers_count", 0)
                    if stars_cache[repo] < MIN_STARS:
                        continue
                    num = it["number"]
                    files = api(f"https://api.github.com/repos/{repo}/pulls/{num}/files?per_page=100")
                    tests = [f for f in files if is_test(f["filename"])]
                    src = [f for f in files if f["filename"].endswith(".py") and not is_test(f["filename"])]
                    if not tests:
                        continue
                    rec = {"url": it["html_url"], "repo": repo, "stars": stars_cache[repo], "number": num,
                           "title": it["title"], "merged_at": it.get("pull_request", {}).get("merged_at"),
                           "n_files": len(files), "src_files": [f["filename"] for f in src],
                           "test_files": [{k: f.get(k) for k in ("filename", "status", "additions", "deletions", "patch")}
                                          for f in tests]}
                    out.write(json.dumps(rec) + "\n")
                    seen.add(it["html_url"])
                    kept += 1
                print(f"{q[:60]}... page {page}: kept so far {kept}, repos checked {len(stars_cache)}", flush=True)
    print(f"done: {kept} new PRs -> {OUT}")


if __name__ == "__main__":
    pages = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    main(['"Generated with Claude Code" is:pr is:merged created:>2026-09-15',
          '"Co-Authored-By: Claude" is:pr is:merged created:>2026-09-15'], pages)
