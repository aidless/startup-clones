"""三个上架 agent：一个按次、一个按 token、一个订阅。"""

from .manifest import AgentManifest, Pricing

INVOICE_BOT = AgentManifest(
    agent_id="invoice-bot", version="1.2.0", name="发票核对机器人",
    entrypoint="handlers.invoice:run",
    pricing=Pricing(kind="per_call", cents_per_unit=5),
    permissions=("fs.read", "net.outbound"),
    description="读邮箱里的发票 PDF，与账上应付做三方匹配。",
)

RESEARCH = AgentManifest(
    agent_id="deck-research", version="0.4.1", name="投研摘要",
    entrypoint="handlers.research:run",
    pricing=Pricing(kind="per_token", cents_per_unit=30),
    permissions=("net.outbound", "secrets.read"),
    description="按问题检索公开披露文件并生成带引用的摘要。",
)

CFO = AgentManifest(
    agent_id="cfo-copilot", version="2.0.0", name="CFO 助手",
    entrypoint="handlers.cfo:run",
    pricing=Pricing(kind="subscription", cents_per_unit=900, period="month"),
    permissions=("fs.read", "fs.write", "net.outbound"),
    description="月度经营分析、预算差异、现金预测。",
)
