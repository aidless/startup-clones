#!/bin/sh
# 把版本化的钩子挂上：core.hooksPath 指向 scripts/git-hooks，钩子随仓库一起改。
set -eu
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath scripts/git-hooks
echo "core.hooksPath = $(git config core.hooksPath)"
ls -l scripts/git-hooks
