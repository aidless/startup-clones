#!/usr/bin/env bash
# 从本仓库产出一个可公开发布的仓库（保留历史，去掉商业包）。
#
#   bash scripts/make_public_repo.sh /path/to/startup-clones-oss
#
# 去掉的东西（每一项都有理由，别随手加回来）：
#   go-to-market/     定价、20 家目标事务所名单、销售话术、落地页 —— 这是商业包，不是代码
# 保留的东西：
#   docs/REVIEW-*.md  我们自己写的三轮代码审查（48 + 34 + 30 条缺陷）—— 公开它比不公开可信
#   filing-lens/data-prospects/  三家小盘客户的 10-K 与差异表（SEC 公开文件），让 e2e 与
#                                差异表的测试在没有 164MB 全量语料时也能真跑
#
# 做完之后 public 仓库还要一个「发布版」提交：pytest.ini 去掉 go-to-market 这个挂载点，
# README 的测试计数按实际重算。脚本末尾会提示这两步。
set -euo pipefail

TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  echo "用法：bash scripts/make_public_repo.sh /path/to/target" >&2
  exit 2
fi

SRC="$(cd "$(dirname "$0")/.." && pwd)"
if ! command -v git-filter-repo >/dev/null 2>&1 && ! git filter-repo --version >/dev/null 2>&1; then
  echo "需要 git-filter-repo：pip install git-filter-repo" >&2
  exit 2
fi

rm -rf "$TARGET"
git clone -q "$SRC" "$TARGET"
cd "$TARGET"
git filter-repo --force --invert-paths --path go-to-market
# filter-repo 会把 origin 删掉，发布前显式告诉人要重新指
git remote remove origin 2>/dev/null || true

echo "== 产出的仓库 =="
echo "路径：$TARGET"
echo "提交：$(git rev-list --count HEAD) 个"
echo "体积：$(du -sh . | cut -f1)（其中 .git $(du -sh .git | cut -f1)）"
echo
echo "还要手动做两件事（都在 $TARGET 里）："
echo "  1. pytest.ini 的 testpaths 删掉 go-to-market，否则 pytest 会报目录不存在"
echo "  2. README 的测试计数按 'python3 -m pytest' 的实际输出重算"
echo "然后：python3 -m pytest -q 必须 0 failed / 0 error（缺语料的用例 skip 是正常的）"
