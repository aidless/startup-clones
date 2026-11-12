import pytest

from agentstore.manifest import AgentManifest, ManifestError, Pricing, bump, parse_version
from agentstore.meter import Ledger
from agentstore.registry import Registry, RegistryError
from agentstore.runtime import Runtime
from agentstore.fixtures import CFO, INVOICE_BOT, RESEARCH


def _reg():
    return Registry()


def test_publish_is_immutable():
    r = _reg()
    r.publish(INVOICE_BOT, developer="dev-a")
    # 同版本号再发一次必须失败（内容可能不同，版本号是信任锚）
    changed = AgentManifest(**{**INVOICE_BOT.__dict__, "description": "偷偷改了行为"})
    with pytest.raises(RegistryError) as exc:
        r.publish(changed, developer="dev-a")
    assert "已发布" in str(exc.value)
    assert r.latest("invoice-bot").version == "1.2.0"


def test_digest_tracks_content():
    a = INVOICE_BOT.digest()
    b = AgentManifest(**{**INVOICE_BOT.__dict__, "permissions": ("fs.read",)}).digest()
    assert a != b
    # 权限顺序不影响哈希（canonical 里排序）
    c = AgentManifest(**{**INVOICE_BOT.__dict__, "permissions": ("net.outbound", "fs.read")})
    assert c.digest() == a


def test_unknown_permission_and_bad_version_rejected():
    with pytest.raises(ManifestError):
        AgentManifest(agent_id="x1", version="1.0.0", name="x", entrypoint="h",
                      pricing=Pricing("per_call", 5), permissions=("root.shell",)).validate()
    with pytest.raises(ManifestError):
        AgentManifest(agent_id="x1", version="1.0", name="x", entrypoint="h",
                      pricing=Pricing("per_call", 5)).validate()


def test_version_helpers():
    assert parse_version("1.2.3") == (1, 2, 3)
    assert bump("1.2.3", "patch") == "1.2.4"
    assert bump("1.2.3", "minor") == "1.3.0"
    assert bump("1.9.9", "major") == "2.0.0"


def test_permission_denied_charges_nothing():
    r = _reg()
    r.publish(RESEARCH, "dev-b")
    r.install("buyer-1", "deck-research", granted=("net.outbound",))   # 没给 secrets.read
    ledger = Ledger()
    ledger.register(RESEARCH)
    rt = Runtime(r, ledger)

    ex = rt.execute("buyer-1", "deck-research", lambda rid: ("不该运行", 1000),
                    request_id="req-1", needs=("secrets.read",))
    assert not ex.ok and ex.error.startswith("permission_denied")
    assert ex.charged_cents == 0
    assert ledger.statement("buyer-1", {}).lines == []      # 被拦的请求不进账单
    assert [a["step"] for a in ex.audit] == ["resolve", "gate"]


def test_failed_handler_charges_nothing():
    r = _reg()
    r.publish(INVOICE_BOT, "dev-a")
    r.install("buyer-1", "invoice-bot")
    ledger = Ledger(); ledger.register(INVOICE_BOT)
    rt = Runtime(r, ledger)

    def boom(_rid):
        raise RuntimeError("模型超时")

    ex = rt.execute("buyer-1", "invoice-bot", boom, "req-boom", needs=("fs.read",))
    assert not ex.ok and "handler_error" in ex.error and ex.charged_cents == 0
    assert ledger.statement("buyer-1", {}).lines == []


def test_successful_call_is_charged_once():
    r = _reg()
    r.publish(INVOICE_BOT, "dev-a")
    r.install("buyer-1", "invoice-bot")
    ledger = Ledger(); ledger.register(INVOICE_BOT)
    rt = Runtime(r, ledger)

    ex = rt.execute("buyer-1", "invoice-bot", lambda rid: ("3 张全部匹配", 1),
                    "req-dup", needs=("fs.read",))
    assert ex.ok and ex.charged_cents == 5
    again = rt.execute("buyer-1", "invoice-bot", lambda rid: ("再来一次", 1),
                       "req-dup", needs=("fs.read",))
    assert again.charged_cents == 5                      # 返回值来自同一条记录
    st = ledger.statement("buyer-1", {"invoice-bot": "dev-a"})
    assert st.gross_cents == 5 and st.lines[0].calls == 1  # 幂等：只算一次


def test_per_token_rounds_up_to_thousand():
    ledger = Ledger(); ledger.register(RESEARCH)
    assert ledger.price("deck-research", "0.4.1", 1) == 30        # 不足 1k 按 1k
    assert ledger.price("deck-research", "0.4.1", 1000) == 30
    assert ledger.price("deck-research", "0.4.1", 1500) == 60
    assert ledger.price("deck-research", "0.4.1", 2000) == 60


def test_split_rounding_favours_developer():
    ledger = Ledger(); ledger.register(INVOICE_BOT)
    ledger.record("buyer-2", "invoice-bot", "1.2.0", "r1", 1)   # 5 美分
    st = ledger.statement("buyer-2", {"invoice-bot": "dev-a"}, fee_pct=20)
    line = st.lines[0]
    assert (line.gross_cents, line.platform_cents, line.developer_cents) == (5, 1, 4)
    assert line.gross_cents == line.platform_cents + line.developer_cents


def test_yanked_version_blocks_execution():
    r = _reg()
    r.publish(CFO, "dev-c")
    r.install("buyer-3", "cfo-copilot")
    r.yank("cfo-copilot", "2.0.0")
    ledger = Ledger(); ledger.register(CFO)
    rt = Runtime(r, ledger)
    ex = rt.execute("buyer-3", "cfo-copilot", lambda rid: ("ok", 1), "req-y", needs=("fs.read",))
    assert not ex.ok and "下架" in ex.error
    with pytest.raises(RegistryError):
        r.latest("cfo-copilot")


def test_install_cannot_grant_extra_permission():
    r = _reg()
    r.publish(INVOICE_BOT, "dev-a")
    with pytest.raises(RegistryError):
        r.install("buyer-4", "invoice-bot", granted=("fs.read", "secrets.read"))
