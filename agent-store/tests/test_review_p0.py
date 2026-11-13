"""审查报告 P0 三条 + 两条 P1 的复现测试（2026-11-12 审查）。

agent-store 的三条 P0 都指向同一个产品承诺：
「买到的就是原开发者发布的那个版本，且每个请求只收一次钱」。
- P0-10 versions 不记 developer、不校验归属 → 任何人抢发 9.9.9 就能顶掉原开发者的最新版
- P0-11 幂等键缺 buyer → 别的买家撞同一个 request_id，永久免单
- P0-12 分成行级取整 → 100 行 1 分钱 @20% 平台实收 0
"""
from __future__ import annotations

import pytest

from agentstore.manifest import AgentManifest, Pricing
from agentstore.meter import Ledger
from agentstore.registry import Registry, RegistryError

BASE = dict(name="Acme 助手", entrypoint="main:run", description="demo")


def manifest(agent_id: str, version: str, perms=("net.outbound",), cents=5) -> AgentManifest:
    base = {k: v for k, v in BASE.items() if k != "pricing"}
    return AgentManifest(agent_id=agent_id, version=version, **base,
                         pricing=Pricing(kind="per_call", cents_per_unit=cents),
                         permissions=tuple(perms))


# ---- P0-10：版本归属 ----

def test_other_developer_cannot_claim_latest_version():
    r = Registry()
    r.publish(manifest("acme-bot", "1.0.0"), developer="northwind")
    with pytest.raises(RegistryError):
        r.publish(manifest("acme-bot", "9.9.9", perms=("net.outbound", "payment.charge")),
                  developer="attacker")
    latest = r.latest("acme-bot")
    assert latest.version == "1.0.0"
    assert "payment.charge" not in latest.manifest.permissions


def test_same_developer_can_publish_next_version():
    # 正对照：同一位开发者发新版本必须仍然可以
    r = Registry()
    r.publish(manifest("acme-bot", "1.0.0"), developer="northwind")
    v = r.publish(manifest("acme-bot", "1.1.0"), developer="northwind")
    assert v.version == "1.1.0"
    assert r.latest("acme-bot").version == "1.1.0"


def test_version_records_its_developer():
    r = Registry()
    r.publish(manifest("acme-bot", "1.0.0"), developer="northwind")
    assert r.get("acme-bot", "1.0.0").developer == "northwind"


def test_install_sees_original_developer_permissions():
    r = Registry()
    r.publish(manifest("acme-bot", "1.0.0"), developer="northwind")
    v = r.install("buyerA", "acme-bot")
    assert v.version == "1.0.0"
    assert r.granted("buyerA", "acme-bot") == ("net.outbound",)


# ---- P0-11：幂等键必须带 buyer ----

def test_idempotency_key_is_per_buyer():
    led = Ledger()
    led.register(manifest("acme-bot", "1.0.0"))
    a = led.record("buyerA", "acme-bot", "1.0.0", "R1", 1)
    b = led.record("buyerB", "acme-bot", "1.0.0", "R1", 1)
    assert a.duplicate is False and b.duplicate is False, "同一 request_id 跨买家不能视为重投"
    st = led.statement("buyerB", {"acme-bot": "northwind"})
    assert st.gross_cents > 0, f"buyerB 不该因为没有自己下过单而免单：{st}"


def test_same_buyer_same_request_id_is_still_deduped():
    # 正对照：真正的重投（同一买家同一 request_id）仍必须去重
    led = Ledger()
    led.register(manifest("acme-bot", "1.0.0"))
    led.record("buyerA", "acme-bot", "1.0.0", "R1", 1)
    again = led.record("buyerA", "acme-bot", "1.0.0", "R1", 1)
    assert again.duplicate is True
    st = led.statement("buyerA", {"acme-bot": "northwind"})
    assert st.gross_cents == 5


# ---- P0-12：分成不能行级取整 ----

def test_many_pennies_do_not_round_platform_share_to_zero():
    led = Ledger()
    for i in range(100):
        led.record("buyerA", "acme-bot", "1.0.0", f"R{i}", 1, cents=1)
    st = led.statement("buyerA", {"acme-bot": "northwind"}, fee_pct=20)
    platform = sum(l.platform_cents for l in st.lines)
    assert st.gross_cents == 100
    assert platform == 20, f"100 行 ×1¢ @20% 平台应得 20¢，实际 {platform}¢"
    assert sum(l.developer_cents for l in st.lines) == 80


def test_split_still_exact_for_normal_amounts():
    # 正对照：5¢ @20% 仍是平台 1 / 开发者 4
    led = Ledger()
    led.record("buyerA", "acme-bot", "1.0.0", "R1", 1, cents=5)
    st = led.statement("buyerA", {"acme-bot": "northwind"}, fee_pct=20)
    line = st.lines[0]
    assert (line.gross_cents, line.platform_cents, line.developer_cents) == (5, 1, 4)


# ---- P1：未注册清单不能穿透成 KeyError ----

def test_unregistered_manifest_is_a_clean_error():
    r = Registry()
    with pytest.raises(RegistryError):
        r.get("nobody", "1.0.0")
