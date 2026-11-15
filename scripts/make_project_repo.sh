#!/usr/bin/env bash
# 从 startup-clones 里拆出一个项目的独立仓库（保留该项目自己的历史）。
#
#   bash scripts/make_project_repo.sh cruxline /path/to/cruxline-oss
#
# 拆出来的树根就是项目根（pyproject.toml / README.md / LICENSE / .github 都在根），
# 所以每个项目目录里必须自带这些文件——它们和代码同一次提交维护，拆出来才不会漂。
#
# 不做的事：不改代码、不改文档、不打补丁。拆出来的东西必须与源仓库同一个提交内容，
# 否则「源仓跑绿、拆出来跑红」这种差异会变成长期负债。
set -euo pipefail

PROJECT="${1:-}"
TARGET="${2:-}"
if [ -z "$PROJECT" ] || [ -z "$TARGET" ]; then
  echo "用法：bash scripts/make_project_repo.sh <项目目录名> <目标路径>" >&2
  echo "可用项目：cruxline agent-store audit-loop filing-lens geo-radar agent-inbox console" >&2
  exit 2
fi

SRC="$(cd "$(dirname "$0")/.." && pwd)"
if [ ! -d "$SRC/$PROJECT" ]; then
  echo "没有这个项目目录：$SRC/$PROJECT" >&2
  exit 2
fi
if ! git filter-repo --version >/dev/null 2>&1; then
  echo "需要 git-filter-repo：pip install git-filter-repo" >&2
  exit 2
fi

rm -rf "$TARGET"
git clone -q "$SRC" "$TARGET"
cd "$TARGET"
ABS="$(pwd)"
git filter-repo --force --subdirectory-filter "$PROJECT"
git remote remove origin 2>/dev/null || true

# 拆出来之后必须自证三件事：测试能跑、CLI 能起、没有指向兄弟项目的相对路径
echo "== 残留的兄弟项目引用（应当为空）=="
if grep -rnE '\.\./(agent-inbox|agent-store|audit-loop|cruxline|filing-lens|geo-radar|console)(/|\b)' \
     --include='*.md' --include='*.py' --include='*.toml' . 2>/dev/null | grep -v '^\./\.git/'; then
  echo "!! 上面这些引用在独立仓库里会断链，先回源仓库改掉" >&2
else
  echo "（无）"
fi

echo "== 提交数与体积 =="
echo "提交：$(git rev-list --count HEAD) 个"
du -sh . | awk '{print "体积：" $1}'

echo "== 测试 =="
python3 -m pytest -q 2>&1 | tail -2

echo "== CLI =="
case "$PROJECT" in
  cruxline)    python3 -m cruxline.cli --version ;;
  agent-store) python3 -m agentstore.cli --version ;;
  audit-loop)  python3 -m auditloop.cli --version ;;
  *) echo "（该项目的 CLI 入口不同，手动确认）" ;;
esac

echo "== 完 =="
echo "发布：cd $ABS && gh repo create <name> --public --source=. --remote=origin --push"
