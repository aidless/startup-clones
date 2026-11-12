"""抓真实 MCP server 的清单（package.json + README 头部）。

目的不是收集，而是回答一个产品问题：**真实的 agent 清单里，权限到底写了没有。**
所以只保留判断权限需要的字段，不下载整个仓库。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "agent-store-research/0.1"
RAW = Path(__file__).resolve().parents[1] / "data/raw"


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def search(query: str, per_page: int) -> list[dict]:
    url = ("https://api.github.com/search/repositories?q="
           + urllib.parse.quote(query) + f"&sort=stars&per_page={per_page}")
    return json.loads(get(url)).get("items", [])


def fetch_raw(owner_repo: str, branch: str, path: str) -> str | None:
    url = f"https://raw.githubusercontent.com/{owner_repo}/{branch}/{path}"
    try:
        return get(url).decode("utf-8", "replace")
    except (urllib.error.HTTPError, urllib.error.URLError):
        return None


def fetch_repo(owner_repo: str, branch: str) -> dict | None:
    """package.json 和 README 必须都试一遍。

    之前的写法遇到 package.json 就 return 了，README 永远是空的，
    结果 16 份清单里 8 份被误判成「没有文档」——这是抓取错误，不是事实。
    """
    pkg_body = fetch_raw(owner_repo, branch, "package.json")
    readme = fetch_raw(owner_repo, branch, "README.md") or ""
    if pkg_body is None and not readme:
        return None
    try:
        pkg = json.loads(pkg_body) if pkg_body else {}
    except json.JSONDecodeError:
        pkg = {}
    return {"package_json": pkg, "readme": readme[:6000]}


def main() -> int:
    per_page = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    RAW.mkdir(parents=True, exist_ok=True)
    saved = 0
    for item in search("mcp-server in:name", per_page):
        repo = item["full_name"]
        if "awesome" in repo.lower():
            print(f"  [剔除] {repo}: 这是清单仓库，不是 server")
            continue
        branch = item.get("default_branch") or "main"
        got = fetch_repo(repo, branch)
        if not got:
            print(f"  [跳过] {repo}: 取不到清单文件")
            continue
        payload = {"repo": repo, "stars": item["stargazers_count"],
                   "description": item.get("description") or "",
                   "branch": branch, **got}
        out = RAW / (repo.replace("/", "__") + ".json")
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
        pkg = payload["package_json"]
        print(f"  {payload['stars']:>6}★ {repo:<45} pkg={'Y' if pkg else '-'} "
              f"readme={len(payload['readme'])//1000}k")
        saved += 1
        time.sleep(1.0)
    print(f"保存 {saved} 份清单到 {RAW}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
