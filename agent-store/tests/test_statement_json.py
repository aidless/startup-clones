"""`statement --json` 的契约：出账既要能给机器读的 JSON，又不能弄丢人读的那一份。

出账是「变更」而不是纯查询：`--request-id` 给出的那一刻，账单被落成快照，
同一个 id 再来一次必须**回放那条快照**（不是重新聚合）。所以这里除了「字段齐、
整数分对得上」，还要钉住三件事：

1. stdout 整体是一个 JSON 对象（`json.loads(stdout)` 直接成功）；
2. `platform_cents + developer_cents == gross_cents`，逐行也成立；
3. JSON 里的每个金额都能在 Markdown 账单里找到同一个数 —— 两种视图不许各算一遍。

正对照：不带 `--json` 的 demo 输出必须还是原来那份人读文本（不是 JSON、合计不变）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from agentstore.fixtures import INVOICE_BOT
from agentstore.meter import Ledger

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "agentstore.cli", *args],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)


def _json(*args: str) -> dict:
    p = _run(*args)
    assert p.returncode == 0, f"exit={p.returncode}\nstdout={p.stdout[-500:]}\nstderr={p.stderr[-800:]}"
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        raise AssertionError(f"stdout 不是纯 JSON：\n{p.stdout[:600]}")


def _usd(cents: int) -> str:
    return f"${Decimal(int(cents)) / Decimal(100):,.2f}"


@pytest.fixture
def db(tmp_path) -> Path:
    """真实落盘的商店库：demo 把 6 次调用（含 1 次拦截、1 次重投）记进 usage。"""
    path = tmp_path / "store.db"
    _run("demo", "--db", str(path))     # 退出码由 _json()/断言检查，夹具不吞红
    return path


def test_statement_json_is_pure_json_and_balances(db):
    data = _json("statement", "--db", str(db), "--buyer", "acme", "--json")

    assert {"gross_cents", "platform_cents", "developer_cents", "rows"} <= set(data)
    # demo 的真实用量：2×5¢ + 2400 token(3×30¢) + 900¢ 订阅 = 1000¢，20% 抽成 = 200¢
    assert data["gross_cents"] == 1000
    assert data["platform_cents"] == 200
    assert data["developer_cents"] == 800
    assert data["platform_cents"] + data["developer_cents"] == data["gross_cents"]
    assert data["fee_pct"] == 20
    assert data["idempotent_replay"] is False

    assert len(data["rows"]) == 3
    for row in data["rows"]:
        assert {"agent_id", "developer", "calls", "units",
                "gross_cents", "platform_cents", "developer_cents"} <= set(row)
        assert row["platform_cents"] + row["developer_cents"] == row["gross_cents"]
    # 合计必须由逐行算出，不能另算一遍
    assert sum(r["gross_cents"] for r in data["rows"]) == data["gross_cents"]
    assert sum(r["platform_cents"] for r in data["rows"]) == data["platform_cents"]
    assert sum(r["developer_cents"] for r in data["rows"]) == data["developer_cents"]
    # 拦截掉的调用（req-1003）不该出现在账单里
    assert [r["calls"] for r in data["rows"] if r["agent_id"] == "invoice-bot"] == [2]
    # 开发者归属由 --developer 显式给出，没有就是 unknown（不瞎猜）
    assert [r["developer"] for r in data["rows"] if r["agent_id"] == "invoice-bot"] == ["unknown"]


def test_statement_json_and_markdown_carry_the_same_numbers(db):
    md = _run("statement", "--db", str(db), "--buyer", "acme",
              "--developer", "invoice-bot=northwind-labs").stdout
    data = _json("statement", "--db", str(db), "--buyer", "acme",
                 "--developer", "invoice-bot=northwind-labs", "--json")

    assert "合计应付 **$10.00**（平台抽成 20%）" in md, md[:400]
    assert data["gross_cents"] == 1000
    for row in data["rows"]:
        for key in ("gross_cents", "platform_cents", "developer_cents"):
            assert _usd(row[key]) in md, f"{row['agent_id']}.{key}={row[key]} 在 Markdown 里找不到"
    inv = [r for r in data["rows"] if r["agent_id"] == "invoice-bot"][0]
    assert inv["developer"] == "northwind-labs"
    assert "northwind-labs" in md


def test_plain_demo_output_stays_human_readable():
    """正对照：没有 --json 时旧的人读行为一个字都不许变（也不是 JSON）。"""
    p = _run("demo")
    assert p.returncode == 0
    out = p.stdout
    assert "== 上架 ==" in out
    assert "invoice-bot@1.2.0  per_call" in out
    assert "permission_denied: secrets.read" in out
    assert "合计应付 **$10.00**（平台抽成 20%）" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


def test_statement_usage_errors_exit_2(db):
    # 缺 --buyer
    p = _run("statement", "--db", str(db), "--json")
    assert p.returncode == 2
    assert "--buyer" in p.stderr
    # 缺 --db
    p = _run("statement", "--buyer", "acme", "--json")
    assert p.returncode == 2
    assert "--db" in p.stderr
    # 抽成越界
    p = _run("statement", "--db", str(db), "--buyer", "acme", "--fee-pct", "120", "--json")
    assert p.returncode == 2
    # --developer 必须 agent=dev
    p = _run("statement", "--db", str(db), "--buyer", "acme", "--developer", "northwind-labs", "--json")
    assert p.returncode == 2


def test_repeated_request_id_replays_the_snapshot(db):
    first = _json("statement", "--db", str(db), "--buyer", "acme",
                  "--request-id", "st-1", "--json")
    assert first["request_id"] == "st-1"
    assert first["idempotent_replay"] is False
    assert first["gross_cents"] == 1000

    # 快照之后又有新用量：回放必须仍是旧数（否则「同一张账单」四个字就没意义）
    ledger = Ledger(str(db))
    ledger.register(INVOICE_BOT)
    ledger.record("acme", "invoice-bot", "1.2.0", "req-late", 1)

    again = _json("statement", "--db", str(db), "--buyer", "acme",
                  "--request-id", "st-1", "--json")
    assert again["idempotent_replay"] is True
    assert again["gross_cents"] == 1000
    assert again["issued_at"] == first["issued_at"]
    assert again["rows"] == first["rows"]

    # 换比例也回放原快照：新参数不生效，得换新的 request_id
    replay_fee = _json("statement", "--db", str(db), "--buyer", "acme",
                       "--request-id", "st-1", "--fee-pct", "50", "--json")
    assert replay_fee["fee_pct"] == 20
    assert replay_fee["platform_cents"] == first["platform_cents"]

    # 新 id 才会重新聚合，看到那笔 5¢
    fresh = _json("statement", "--db", str(db), "--buyer", "acme",
                  "--request-id", "st-2", "--json")
    assert fresh["idempotent_replay"] is False
    assert fresh["gross_cents"] == 1005


def test_request_id_is_scoped_per_buyer(db):
    """幂等键是 (buyer, request_id)：B 撞上 A 的账单号，不能看到 A 的数。"""
    mine = _json("statement", "--db", str(db), "--buyer", "acme",
                 "--request-id", "shared", "--json")
    assert mine["gross_cents"] == 1000

    other = _json("statement", "--db", str(db), "--buyer", "beta",
                  "--request-id", "shared", "--json")
    assert other["idempotent_replay"] is False
    assert other["gross_cents"] == 0
    assert other["rows"] == []
    assert other["platform_cents"] == other["developer_cents"] == 0
