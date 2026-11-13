"""入市审查：从清单文本里推断「这个 agent 大概要什么权限」，再对照它声明了什么。

为什么需要这一层：`registry` 只能校验「授予的权限 ⊆ 声明的权限」，
但真实世界的清单**根本不声明权限**。苹果 App Store 的隐私标签是人工填的，
填错没人管——所以审核方必须自己能从代码/文档里推出它实际会干什么。

这里的推断是关键词规则，不装成 AST 分析。它只做一件事：
把「你没说的」和「你文档里写着的」摆到一起，让人判断。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# 关键词 → 权限。故意粗：宁可多报（要求开发者解释），不可漏报（放过取密钥的）。
# 每一项都写清匹配理由，审核员要能反驳单条判断。
KEYWORD_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "net.outbound": ("http", "https", "api", "fetch", "web", "search", "crawl",
                     "url", "request", "endpoint", "graphql"),
    "fs.read": ("read", "file", "filesystem", "directory", "parse", "excel",
                "spreadsheet", "pdf", "csv", "local"),
    "fs.write": ("write", "save file", "create file", "export file", "upload",
                 "edit file", "modify file", "write access"),
    "secrets.read": ("api key", "apikey", "token", "credential", "secret",
                     "password", "auth", "bearer", "oauth"),
    "email.send": ("send email", "email", "smtp", "mail", "inbox", "outlook"),
    # 实测踩坑：原来把 "charge"/"invoice"/"purchase" 也当证据，
    # 结果一个讲「charge 用户」的多模型代理被误判成要动钱。
    # 只留真正指向资金动作的词。
    "payment.charge": ("payment", "billing", "stripe", "credit card", "pay now"),
}

# 环境变量名本身就是证据：出现这个模式，说明它要拿一个凭据去调外部服务
ENV_SECRET_RE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}(?:_API_KEY|_TOKEN|_SECRET|_KEY|_PASSWORD)\b")

# 权限字段的常见叫法。真实的 npm 包一个都没有，但审核方需要一个口径。
PERMISSION_FIELDS = ("permissions", "capabilities", "scopes", "mcp")

PINNED_RE = re.compile(r"^\d+\.\d+\.\d+$")

# 关键词必须按词边界匹配。踩过的坑：substring 匹配把 "credits" 里的 "edit"
# 当成写文件、把 "capital" 里的 "api" 当成联网、把 GitHub Actions 的
# "checkout" 当成收款。这类假阳性会让整个审查结论失去意义。
_ASCII_WORD_RE = {}


def _word_re(kw: str) -> re.Pattern:
    if kw not in _ASCII_WORD_RE:
        _ASCII_WORD_RE[kw] = re.compile(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])")
    return _ASCII_WORD_RE[kw]


def _hits(words: tuple[str, ...], text: str) -> list[str]:
    return [w for w in words if _word_re(w).search(text)]


@dataclass
class ServerFacts:
    """一份清单能提供的全部证据。字段少而实，缺的就是缺的（不猜）。"""

    repo: str
    name: str = ""
    version: str = ""
    description: str = ""
    readme: str = ""
    deps: dict[str, str] = field(default_factory=dict)
    declared: dict[str, list[str]] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """用于关键词推断的全文（描述 + README，小写）。"""
        return f"{self.description}\n{self.readme}".lower()

    def env_vars(self) -> list[str]:
        return sorted(set(ENV_SECRET_RE.findall(f"{self.description}\n{self.readme}")))


def from_manifest(payload: dict) -> ServerFacts:
    """把 fetch 下来的原始 JSON 变成审核用的证据对象。"""
    pkg = payload.get("package_json") or {}
    declared = {k: list(pkg[k]) for k in PERMISSION_FIELDS
                if isinstance(pkg.get(k), list)}
    return ServerFacts(
        repo=payload.get("repo", "?"),
        name=str(pkg.get("name") or payload.get("repo", "?")),
        version=str(pkg.get("version") or ""),
        description=str(pkg.get("description") or payload.get("description") or ""),
        readme=str(payload.get("readme") or ""),
        deps=dict(pkg.get("dependencies") or {}),
        declared=declared,
    )


def declared_permissions(facts: ServerFacts) -> set[str]:
    """把各家的字段名统一成我们的权限词表。认不出的原样保留（不静默丢弃）。"""
    out: set[str] = set()
    for values in facts.declared.values():
        for v in values:
            if v.startswith("!"):
                continue
            out.add(str(v))
    return out


def infer_permissions(facts: ServerFacts) -> dict[str, list[str]]:
    """返回 {权限: [触发的关键词或环境变量]}。空 dict 表示没找到任何需求证据。"""
    text = facts.text
    found: dict[str, list[str]] = {}
    for perm, words in KEYWORD_PERMISSIONS.items():
        hits = _hits(words, text)
        if hits:
            found[perm] = hits
    envs = facts.env_vars()
    if envs:
        # 环境变量是硬证据，比关键词强：写进 README 的 KEY 名就是要填的凭据
        found.setdefault("secrets.read", []).extend(envs)
    # 有外部依赖包（sdk/client）也说明要联网
    if any(re.search(r"(sdk|client|api)", d.lower()) for d in facts.deps):
        found.setdefault("net.outbound", []).append("dependency:*-sdk/client")
    return found


@dataclass
class Finding:
    rule: str
    severity: str  # high / medium / low
    detail: str


# 这两类权限「存在任何环境变量名」本身就是硬证据：要拿凭据 = 要读密钥
_ENV_ITSELF_IS_PROOF = {"secrets.read"}


def _env_proves(perm: str, evidence: list[str], hard: set[str]) -> bool:
    """判断环境变量名是否构成这条权限的硬证据。

    原实现 `any(env in e ...)` 方向反了：拿整个环境变量名去问「是否被证据词包含」，
    而证据词是 stripe/payment 这类短词 —— `"STRIPE_SECRET_KEY" in "stripe"` 恒假。
    于是只剩「环境变量名自己出现在证据列表里」这一种自证，结果任何 KEY 名都能把
    *每一条* 敏感权限顶成 high（ANTHROPIC_API_KEY 也被当成动钱证据）。

    正确判据：证据词出现在环境变量名里（stripe ⊂ STRIPE_SECRET_KEY）。
    """
    if not hard:
        return False
    if perm in _ENV_ITSELF_IS_PROOF:
        return True
    for e in evidence:
        token = e.lower().strip()
        if not token:
            continue
        if any(token in env.lower() for env in hard):
            return True
    return False


def audit(facts: ServerFacts) -> list[Finding]:
    """把「需要的」和「声明的」对起来，产出可读的入市结论。"""
    need = infer_permissions(facts)
    have = declared_permissions(facts)
    out: list[Finding] = []

    if need and not have:
        # 等级定 medium 而不是 high：在真实 MCP 生态里「不声明」是 16/16 的普遍状态，
        # 定成 high 会让每份清单都红，审查结论就失去区分度（全是 high = 没有 high）。
        # high 留给真正危险且被具体证据钉住的情况。
        out.append(Finding(
            "no_permission_declaration", "medium",
            f"清单没有任何权限声明，但文档/依赖显示需要 {sorted(need)}"))

    hard = set(facts.env_vars())
    for perm in sorted(set(need) - have):
        if perm in ("secrets.read", "payment.charge", "email.send"):
            # 证据强度分级：README 里出现具体 KEY 名 = 硬证据；
            # 只有「token/secret」这类词 = 软证据，可能是讲别人的东西。
            proven = _env_proves(perm, need[perm], hard)
            out.append(Finding(
                "undeclared_sensitive_permission", "high" if proven else "medium",
                f"需要 {perm}（依据：{need[perm][:4]}）却未声明"
                f"{'；环境变量名为硬证据' if proven else '；仅关键词推断'}"))
        elif perm in ("fs.write",):
            out.append(Finding(
                "undeclared_write_permission", "medium",
                f"需要 {perm}（依据：{need[perm][:4]}）却未声明"))

    if have and not (have <= set(need)):
        extra = sorted(have - set(need))
        out.append(Finding(
            "over_requested_permission", "medium",
            f"声明的权限在文档里找不到依据：{extra}"))

    if not facts.version or not PINNED_RE.match(facts.version):
        out.append(Finding(
            "unpinned_version", "medium",
            f"版本无法固定（{facts.version or '缺失'}），买家装到的东西不可复现"))

    if not facts.readme.strip():
        out.append(Finding(
            "no_documentation", "medium", "清单无 README，审核员无法判断它做什么"))

    return out


def review(payload: dict) -> dict:
    """一份清单的完整入市审查结果，便于脚本批量跑。"""
    facts = from_manifest(payload)
    findings = audit(facts)
    worst = "clean"
    for sev in ("high", "medium", "low"):
        if any(f.severity == sev for f in findings):
            worst = sev
            break
    return {"repo": facts.repo, "version": facts.version or "-",
            "inferred": sorted(infer_permissions(facts)),
            "declared": sorted(declared_permissions(facts)),
            "findings": [f.__dict__ for f in findings], "worst": worst}


def load_dir(path: str) -> list[dict]:
    from pathlib import Path

    return [json.loads(p.read_text()) for p in sorted(Path(path).glob("*.json"))]
