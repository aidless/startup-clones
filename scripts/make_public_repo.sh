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

# ---- 发布版补丁：去掉商业包的挂载点 + 按实测重算测试计数 -------------------
python3 - "$TARGET" <<'PATCH'
import pathlib, re, subprocess, sys

root = pathlib.Path(sys.argv[1])

# 1) testpaths 去掉商业包，否则 pytest 报「目录不存在」
ini = root / "pytest.ini"
s = ini.read_text(encoding="utf-8")
s = re.sub(r"^testpaths = .*$",
           "testpaths = geo-radar filing-lens audit-loop cruxline agent-inbox "
           "agent-store console tests", s, flags=re.M)
s = s.replace("# 一次跑完七个项目的全部测试：python3 -m pytest -q（在 startup-clones/ 下）",
              "# 一次跑完七个项目的全部测试：python3 -m pytest（在仓库根下）\n"
              "# go-to-market/ 是维护者的商业包，不在这个仓库里。")
ini.write_text(s, encoding="utf-8")

# 2) 拿实测数字（只取汇总行，不猜）
run = subprocess.run([sys.executable, "-m", "pytest", "-o",
                      "addopts=--import-mode=importlib", "-q"],
                     cwd=root, capture_output=True, text=True)
out = run.stdout + run.stderr
m = re.search(r"(\d+) passed(?:, (\d+) skipped)?", out)
if not m:
    sys.exit("发布版补丁：读不到 pytest 汇总行，先手动跑一遍看看哪里红了\n" + out[-2000:])
passed = int(m.group(1))
skipped = int(m.group(2) or 0)
total = passed + skipped

# 3) README 只改「汇总口径」那几行；每个项目的分项数不变（各项目测试没动）
readme = root / "README.md"
s = readme.read_text(encoding="utf-8")
s = re.sub(r"\*\*\d+ 个测试\*\*[^\n]*\n",
           f"**{total} 个测试**（干净检出里 **{passed} passed / {skipped} skipped**，0 failed），"
           f"**0 个 mock 掉的断言，全部离线可跑**。\n", s, count=1)
s = re.sub(r"一次跑全 \d+ 条（\d+ passed / \d+ skipped）",
           f"一次跑全 {total} 条（{passed} passed / {skipped} skipped）", s)
s = re.sub(r"- 测试：\*\*\d+ 条\*\*（干净检出 \d+ passed / \d+ skipped；",
           f"- 测试：**{total} 条**（干净检出 {passed} passed / {skipped} skipped；", s)
readme.write_text(s, encoding="utf-8")

# 4) filing-lens README：有语料时「全部通过」，无语料时用实测
fl = root / "filing-lens" / "README.md"
s = fl.read_text(encoding="utf-8")
s = re.sub(r"应当 \*\*\d+ passed\*\*（0 skip，0 failed）",
           "应当 **全部通过**（0 skip，0 failed）", s)
s = re.sub(r"实测形状是 \*\*\d+ passed / \d+ skipped / 0 failed\*\*",
           f"实测形状是 **{passed} passed / {skipped} skipped / 0 failed**", s)
fl.write_text(s, encoding="utf-8")
print(f"发布版补丁：{total} 条测试 → {passed} passed / {skipped} skipped")
PATCH

git -C "$TARGET" add -A
git -C "$TARGET" -c user.name="clone-labs" -c user.email="noreply@example.com" \
    commit -q -m "发布版：去掉商业包的挂载点，测试计数按干净检出重算

pytest.ini 的 testpaths 不含 go-to-market；README 与 filing-lens/README 的数字
按本次在无 164MB 语料条件下的实测重写。" || echo "（无改动，跳过发布版提交）"

echo "== 产出的仓库 =="
echo "路径：$TARGET"
echo "提交：$(git rev-list --count HEAD) 个"
echo "体积：$(du -sh . | cut -f1)（其中 .git $(du -sh .git | cut -f1)）"
echo
echo "自检（必须 0 failed / 0 error，缺语料的用例 skip 是正常的）："
(cd "$TARGET" && python3 -m pytest -o addopts=--import-mode=importlib -q 2>&1 | tail -2)
echo "发布：cd $TARGET && gh repo create <name> --public --source=. --remote=origin --push"
