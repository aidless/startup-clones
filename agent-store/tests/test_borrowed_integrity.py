"""借用外部机制：安装时校验清单摘要（sigstore/npm integrity 的思路，见 docs/BORROWED.md B-5）。

版本表里同时存 digest 与 manifest 正文，但 install() 只读 manifest、从不复核
digest。库文件被改一行（或同步/迁移时被批量改写）就能让买家按「已发布摘要」
的名义装到另一份权限清单 —— 摘要的唯一用途就是在这种时候说话。
"""
from __future__ import annotations

import json

import pytest

from agentstore.manifest import AgentManifest, Pricing
from agentstore.registry import Registry, RegistryError


def _manifest(version: str = "1.0.0") -> AgentManifest:
    return AgentManifest(
        agent_id="northwind.expense",
        version=version,
        name="Northwind Expense",
        entrypoint="northwind.main:run",
        pricing=Pricing(kind="per_call", cents_per_unit=5),
        permissions=("fs.read",),
        description="expense agent",
    )


def test_install_refuses_manifest_that_no_longer_matches_digest():
    reg = Registry()
    v = reg.publish(_manifest(), developer="northwind")
    # 模拟库文件被改写：正文换成了带 payment.charge 的清单，digest 列还是发布时那份
    tampered = {
        "agent_id": "northwind.expense",
        "version": "1.0.0",
        "name": "Northwind Expense",
        "entrypoint": "northwind.main:run",
        "pricing": {"kind": "per_call", "cents_per_unit": 5, "period": "month"},
        "permissions": ["payment.charge"],
        "description": "expense agent",
    }
    reg.conn.execute("UPDATE versions SET manifest=? WHERE agent_id=? AND version=?",
                     (json.dumps(tampered), "northwind.expense", "1.0.0"))
    reg.conn.commit()
    with pytest.raises(RegistryError, match="摘要"):
        reg.install("buyer-1", "northwind.expense")
    assert v.digest  # 发布返回值本身仍是可信的那一份


def test_clean_install_still_works():
    reg = Registry()
    reg.publish(_manifest(), developer="northwind")
    got = reg.install("buyer-1", "northwind.expense")
    assert got.version == "1.0.0"
    assert reg.granted("buyer-1", "northwind.expense") == ("fs.read",)
