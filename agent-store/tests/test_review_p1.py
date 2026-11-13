"""审查报告 P1（agent-store）五条的复现测试（2026-11-12 审查）。

对着「买家会被骗」的五处：凭据证据判定方向、重投重复执行、
未注册清单错误穿透、金额浮点丢分、订阅负价。
"""
from __future__ import annotations

import pytest

from agentstore.fixtures import INVOICE_BOT, RESEARCH
from agentstore.intake import ServerFacts, audit
from agentstore.manifest import Pricing, ManifestError
from agentstore.meter import Ledger, _money
from agentstore.registry import Registry
from agentstore.runtime import Runtime


# ---------------- P1-a 环境变量是「按权限方向」的证据 ----------------

def _facts(readme: str) -> ServerFacts:
    return ServerFacts(repo="x/y", name="x", version="1.0.0",
                       description="payments helper", readme=readme)


def test_env_var_proves_payment_permission_direction():
    """README 里写着 STRIPE_SECRET_KEY —— 环境变量名本身就是动钱的硬证据。

    原实现 `any(env in e for env in hard)`：拿「环境变量名」去问「是否被证据词包含」，
    方向反了。证据词是 stripe/payment，环境变量是 STRIPE_SECRET_KEY，
    `"STRIPE_SECRET_KEY" in "stripe"` 恒假 → 明明握着硬证据仍只报 medium。
    """
    f = _facts("Set STRIPE_SECRET_KEY before running. Charges cards via Stripe payment.")
    pay = [x for x in audit(f)
           if x.rule == "undeclared_sensitive_permission" and "payment.charge" in x.detail]
    assert pay and pay[0].severity == "high", f"实际 {[x.detail for x in audit(f)]}"


def test_keyword_only_evidence_still_medium():
    # 正对照：只有关键词、没有任何 KEY 名 → 保持 medium（不许一改全升 high）
    f = _facts("This tool charges cards via Stripe billing.")
    pay = [x for x in audit(f)
           if x.rule == "undeclared_sensitive_permission" and "payment.charge" in x.detail]
    assert pay and pay[0].severity == "medium"


def test_unrelated_env_var_does_not_promote_payment():
    # 假阳守卫：ANTHROPIC_API_KEY（secrets）不能被当成「动钱」的硬证据
    f = _facts("Needs ANTHROPIC_API_KEY. Also mentions payment docs in passing.")
    rows = [x for x in audit(f) if x.rule == "undeclared_sensitive_permission"]
    pay = [x for x in rows if "payment.charge" in x.detail]
    sec = [x for x in rows if "secrets.read" in x.detail]
    assert pay and pay[0].severity == "medium", "别的 KEY 名不能证明它会动钱"
    assert sec and sec[0].severity == "high", "有 KEY 名就要读密钥，这条仍是硬证据"


# ---------------- P1-b 同一 request_id 不重复执行 ----------------

def _runtime(manifest, buyer="buyer-1", register_manifest=True):
    r = Registry()
    r.publish(manifest, "dev-a")
    r.install(buyer, manifest.agent_id, granted=tuple(manifest.permissions))
    ledger = Ledger()
    if register_manifest:
        ledger.register(manifest)
    return Runtime(r, ledger), ledger


def test_same_request_id_runs_handler_once():
    rt, ledger = _runtime(INVOICE_BOT)
    calls = []

    def handler(rid):
        calls.append(rid)
        return "done", 1

    first = rt.execute("buyer-1", INVOICE_BOT.agent_id, handler, "req-1",
                       needs=tuple(INVOICE_BOT.permissions))
    second = rt.execute("buyer-1", INVOICE_BOT.agent_id, handler, "req-1",
                        needs=tuple(INVOICE_BOT.permissions))
    assert first.ok and second.ok
    assert len(calls) == 1, f"handler 被执行 {len(calls)} 次，重投不该再执行"
    assert second.duplicate is True
    st = ledger.statement("buyer-1", {"dev-a": INVOICE_BOT.agent_id})
    assert st.gross_cents == first.charged_cents, "重投不能第二次计费"


def test_different_request_ids_both_run():
    rt, ledger = _runtime(INVOICE_BOT)
    calls = []
    for rid in ("req-1", "req-2"):
        rt.execute("buyer-1", INVOICE_BOT.agent_id,
                   lambda r: (calls.append(r), ("ok", 1))[1], rid,
                   needs=tuple(INVOICE_BOT.permissions))
    assert len(calls) == 2
    st = ledger.statement("buyer-1", {"dev-a": INVOICE_BOT.agent_id})
    assert st.gross_cents == 2 * INVOICE_BOT.pricing.cents_per_unit


# ---------------- P1-c 未注册清单的错误不穿透 ----------------

def test_ledger_without_manifest_is_a_clean_error():
    """计量器不知道这个清单的价格时 meter.price 抛 KeyError 穿透到调用方 ——
    此时 handler 已经跑完（模型调用已经花掉），调用方拿到的却是一个裸 KeyError。"""
    rt, _ = _runtime(INVOICE_BOT, register_manifest=False)
    ex = rt.execute("buyer-1", INVOICE_BOT.agent_id, lambda r: ("ok", 1), "req-1",
                    needs=tuple(INVOICE_BOT.permissions))
    assert ex.ok is True
    assert ex.charged_cents == 0
    assert "未注册" in (ex.error or ""), f"要给出可读原因，实际 error={ex.error!r}"


def test_uninstalled_buyer_is_a_clean_error():
    r = Registry()
    r.publish(INVOICE_BOT, "dev-a")
    ex = Runtime(r, Ledger()).execute("nobody", INVOICE_BOT.agent_id,
                                      lambda rid: ("ok", 1), "req-1")
    assert ex.ok is False
    assert "未安装" in ex.error


# ---------------- P1-d 金额不用浮点 ----------------

def test_money_is_exact_for_large_amounts():
    """cents / 100 走 float：2**53+1 美分以上必然丢精度，账单金额对不上。"""
    assert _money(2 ** 53 + 1) == "$90,071,992,547,409.93"


def test_money_small_values_unchanged():
    assert _money(123456) == "$1,234.56"
    assert _money(0) == "$0.00"


# ---------------- P1-e 订阅价不许为负 ----------------

def test_subscription_negative_price_rejected():
    with pytest.raises(ManifestError):
        Pricing("subscription", cents_per_unit=-500).validate()


def test_subscription_zero_price_rejected():
    # 0 元订阅同样无意义：白送就别走计费通道
    with pytest.raises(ManifestError):
        Pricing("subscription", cents_per_unit=0).validate()


def test_subscription_positive_price_ok():
    Pricing("subscription", cents_per_unit=900, period="month").validate()
