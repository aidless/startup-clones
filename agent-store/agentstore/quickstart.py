"""quickstart：在当前目录生成一个三分钟就能跑出自己结果的最小工作区。

设计上的两条硬约束：

1. **生成物必须真的能跑**：`run.py` 会 import 生成的 `agents/hello/agent.json`
   与 `handler.py`，走真实的 publish → install → execute → replay → conflict
   流程。做不到这一点的 quickstart 只是几个静态文件。
2. **不覆盖用户改过的文件**：目标文件已存在就跳过并打印 `skip`（要覆盖得显式
   `--force`）。模板被改过一次之后就是用户的代码，重跑不该把它冲掉。
"""

from __future__ import annotations

import json
from pathlib import Path

WORKSPACE_DIRNAME = "agentstore-quickstart"

# 三条"接下来跑什么"的命令也出现在这份 README 里，两处必须一致。
NEXT_STEPS = (
    "cd {dirname}",
    "python3 run.py",
    "python3 -m agentstore.cli demo",
)

AGENT_JSON = json.dumps(
    {
        "id": "hello",
        "name": "Hello Agent",
        "version": "0.1.0",
        "description": "把输入变大写的最小 agent（纯 stdlib）",
        "entrypoint": "handler:run",
        "needs": ["fs.read"],
        "permissions": ["fs.read"],
        "price": {"kind": "per_call", "cents_per_unit": 5},
    },
    indent=2,
    ensure_ascii=False,
) + "\n"

HANDLER_PY = '''"""hello agent：把输入变大写。只 import 标准库，没有第三方依赖。

Runtime 的 handler 契约是 `handler(request_id) -> (output, units)`：
拿到幂等键（可以拿它做下游请求的幂等），返回输出与计量单位数。
"""

from __future__ import annotations

import os

DEFAULT_INPUT = "hello agent store"


def uppercase(text: str) -> str:
    return text.upper()


def run(request_id: str) -> tuple:
    """输入走环境变量，同一个 handler 换个载荷不用改代码。

    这正是验证「同键换载荷会 idempotency_conflict」的入口：
        AGENTSTORE_INPUT="ship it" python3 run.py
    """
    text = os.environ.get("AGENTSTORE_INPUT", DEFAULT_INPUT)
    return uppercase(text), 1
'''

RUN_PY = '''"""quickstart 的驱动脚本：发布 → 安装 → 带幂等键执行 → 同键重放 → 同键换载荷 → 账单。

只用标准库 + agentstore 本体。跑法（二选一）：
    python3 run.py                      # 已 pip install -e 过 agentstore
    PYTHONPATH=<agentstore 源码目录> python3 run.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

from agentstore.manifest import load_manifest
from agentstore.meter import Ledger
from agentstore.registry import Registry
from agentstore.runtime import Runtime

HERE = Path(__file__).resolve().parent
AGENT_DIR = HERE / "agents" / "hello"
DB = HERE / "demo.db"       # 每次运行重建：演示从空库开始，不会累积上一次的账单
DEVELOPER = "you"
BUYER = "you"
KEY = "demo-key-1"
FEE_PCT = 20


def load_handler():
    """按文件路径加载生成的 handler.py —— 证明生成物真的被用上，而不是摆着看。"""
    spec = importlib.util.spec_from_file_location("hello_handler", AGENT_DIR / "handler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run


def main() -> int:
    for stale in (DB, Path(str(DB) + "-wal"), Path(str(DB) + "-shm")):
        if stale.exists():
            stale.unlink()

    manifest = load_manifest(AGENT_DIR / "agent.json")
    needs = tuple(manifest.needs)

    registry = Registry(str(DB))
    ledger = Ledger(str(DB))
    ledger.register(manifest)

    version = registry.publish(manifest, DEVELOPER)
    print(f"[1 发布] {version.agent_id}@{version.version} "
          f"digest={version.digest[:12]} 开发者={DEVELOPER}")

    registry.install(BUYER, manifest.agent_id, granted=needs)
    print(f"[2 安装] {BUYER} 只授予清单里的 {list(needs)}；越权的那份清单会被拒")

    runtime = Runtime(registry, ledger)
    handler = load_handler()

    first = runtime.execute(BUYER, manifest.agent_id, handler, KEY, needs=needs)
    print(f"[3 执行] ok={first.ok} id={first.id} 计费={first.charged_cents}¢ "
          f"输出={first.output!r}")

    again = runtime.execute(BUYER, manifest.agent_id, handler, KEY, needs=needs)
    print(f"[4 重放] duplicate={again.duplicate} id={again.id} "
          f"计费={again.charged_cents}¢ 输出={again.output!r}")
    assert again.id == first.id and again.duplicate, "同键同载荷必须回放同一次执行"

    conflict = runtime.execute(BUYER, manifest.agent_id, handler, KEY,
                               needs=needs, tokens=999)
    print(f"[5 换载荷] ok={conflict.ok} error={conflict.error}")
    assert conflict.ok is False, "同键换载荷必须被拒（幂等键不得复用）"

    statement = ledger.statement(BUYER, {manifest.agent_id: DEVELOPER}, fee_pct=FEE_PCT)
    print("[6 账单]")
    print(statement.to_markdown(FEE_PCT))
    print(f"库里的用量行数：{ledger.conn.execute('SELECT COUNT(*) FROM usage').fetchone()[0]}"
          "（重放与冲突都没有新增计费）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

WORKSPACE_README = """# agentstore quickstart 工作区

这三分钟得到的不是"能跑的示例"，而是一个**你自己可以改**的最小 agent 商店闭环：
发布一份清单、只授予它声明的权限、带幂等键执行，然后看同一个键被重放和被复用
时分别发生什么。

## 1. 装（一次）

```bash
pip install -e /path/to/agent-store        # 或者已经在源码目录里：pip install -e .
```

不想装，也可以每次带 `PYTHONPATH=/path/to/agent-store`。

## 2. 跑（一条命令）

```bash
python3 run.py
```

它会依次打印六步：发布 → 安装 → 执行 → 同键重放 → 同键换载荷 → 账单。重点看三行：

- `[3 执行] ok=True id=demo-key-1 计费=5¢` —— 第一次真跑，记一次账；
- `[4 重放] duplicate=True id=demo-key-1 计费=5¢` —— 同一个键，回放**同一次执行**，
  不再执行 handler、不再计费（`usage` 表没有第二行）；
- `[5 换载荷] ok=False error=idempotency_conflict: …` —— 同一个键换了载荷，直接拒。

## 3. 改

- `agents/hello/agent.json`：清单（id / name / version / needs / permissions / price）。
  `needs` 是调用期真正要用的权限，必须 ⊆ `permissions`；它参与 digest，
  上架之后被改动会在安装时报摘要不符。
- `agents/hello/handler.py`：把输入变大写的函数。换个输入不用改代码：
  `AGENTSTORE_INPUT="ship it" python3 run.py`。

想看一个多 agent、多计费口径的完整账单：

```bash
python3 -m agentstore.cli demo
```
"""


def workspace_files() -> list[tuple[str, str]]:
    """(相对路径, 内容)。顺序即打印顺序。"""
    return [
        ("agents/hello/agent.json", AGENT_JSON),
        ("agents/hello/handler.py", HANDLER_PY),
        ("README.md", WORKSPACE_README),
        ("run.py", RUN_PY),
    ]


def write_workspace(target: Path, force: bool = False) -> list[tuple[str, str]]:
    """把工作区写到 target；返回 [(相对路径, 'create'|'overwrite'|'skip')]。

    已存在的文件默认跳过：模板一旦被用户改过就是用户的代码。
    """
    target = Path(target)
    results: list[tuple[str, str]] = []
    for rel, content in workspace_files():
        path = target / rel
        existed = path.exists()
        if existed and not force:
            results.append((rel, "skip"))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        results.append((rel, "overwrite" if existed else "create"))
    return results
