"""审批队列的落盘：`route` 与 `queue` 是两次独立进程，队列必须在它们之间活着。

为什么不让 `Policy` 自己持久化：`Policy` 的单元测试全是内存语义（`pending()`、
`decide()`、终态不可改判），把 IO 塞进去会让 54 个测试都要管临时目录。这里只做
「命令行把待审批写一行、`queue` 读回来」这一件事，策略仍是内存对象。

格式：JSONL，一行一个审批，追加写。不做去重也不做锁——单机单人工具，
并发写同一行是使用错误，不是要静默兜住的情况。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_PATH = Path(".agentinbox") / "approvals.jsonl"


def path_of(explicit: str | None) -> Path:
    return Path(explicit) if explicit else DEFAULT_PATH


def append(approval, path: Path, *, sender: str = "", channel: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "approval_id": approval.approval_id,
        "risk": approval.risk,
        "text": approval.text,
        "thread_id": approval.thread_id,
        "status": approval.status,
        "created_at": approval.created_at,
        "sender": sender,
        "channel": channel,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def pending(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("status") == "pending":
            out.append(row)
    return out
