"""六个工具的统一演示台。

一个 FastAPI 进程、一个页面、六个面板。每个面板背后都是一条**已经被真实数据验证过**的链路：

    费用管理 GEO 监测 → MockProvider 采样（确定性的假模型，只为演示抽样口径）
    10-K 问答      → 真实 Apple FY2026 文件（data/ 目录，需先跑 scripts/fetch_edgar.py）
    审计底稿       → 夹具上的 6 个审计程序
    agent 评测     → 8 条夹具轨迹 + 与人工标注的一致性
    消息层         → 5 条入站消息的准入 / 审批 / 记忆
    agent 商店     → 上架、安装、调用、分成账单

启动：
    python3 console/app.py --port 8800
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
for sub in ("geo-radar", "filing-lens", "audit-loop", "cruxline", "agent-inbox", "agent-store"):
    p = ROOT / sub
    if p.exists():
        sys.path.insert(0, str(p))

from fastapi import FastAPI, Query  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402

app = FastAPI(title="startup-clones console", docs_url="/api/docs")

PROJECTS = [
    ("geo", "geo-radar", "AI 搜索里谁被提到", "同一批买家问题问不同模型，量份额与位次"),
    ("filing", "filing-lens", "问一份 10-K", "数字走 XBRL，正文给段落级出处，没证据就拒答"),
    ("audit", "audit-loop", "审计底稿自动化", "六个审计程序跑一遍，例外按认定归类"),
    ("crux", "cruxline", "agent 轨迹评测", "rubric 打分 + 硬否决 + 与人工标注的一致性"),
    ("inbox", "agent-inbox", "常驻 agent 的消息层", "准入、审批、记忆预算，每一步留审计"),
    ("store", "agent-store", "agent 商店与计费", "上架、最小授权安装、幂等计费、分成账单"),
]


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    return (STATIC / "index.html").read_text()


@app.get("/api/projects")
def projects() -> JSONResponse:
    return JSONResponse([{"id": i, "name": n, "headline": h, "detail": d} for i, n, h, d in PROJECTS])


@app.get("/api/geo")
def geo(samples: int = Query(6, ge=2, le=12)) -> JSONResponse:
    from georadar import extract, metrics, prompts
    from georadar.providers import MockProvider

    brands = ["Ramp", "Brex", "Expensify", "Bill.com", "Coupa", "Airbase", "Divvy", "Navan"]
    provider = MockProvider(brands, seed=7)
    plist = prompts.generate("费用管理软件", limit=samples)
    mentions = []
    for p in plist:
        ans = provider.complete(p.text, model="mock-1")
        ans.prompt_id = p.id
        mentions.extend(extract.find_mentions(ans, brands))

    stats = metrics.brand_stats(mentions, len(plist))
    rows = sorted(stats.values(), key=lambda s: (-s.share_of_voice, s.avg_position))
    return JSONResponse({
        "model": "mock-1（确定性假模型，只演示抽样与口径，不代表真实份额）",
        "prompts": [{"id": p.id, "intent": p.intent, "text": p.text} for p in plist],
        "brands": [{"brand": s.brand, "mentions": s.mentions,
                    "share": round(s.share_of_voice, 3),
                    "avg_position": s.avg_position,
                    "prompts_seen": s.prompts_seen} for s in rows],
    })


@app.get("/api/filing")
def filing(q: str = Query("营收多少", min_length=2),
           cik: str = Query("0000320193")) -> JSONResponse:
    from filinglens import edgar, facts, index
    from filinglens.answer import Answerer

    data = ROOT / "filing-lens" / "data"
    hits = sorted(data.glob(f"{cik}_10k_*.htm"))
    if not hits:
        return JSONResponse({"error": "data/ 下没有该 CIK 的 10-K，先跑 filing-lens/scripts/fetch_edgar.py",
                             "status": "no_data"}, status_code=200)
    doc = hits[-1]
    _cache = getattr(filing, "_cache", {})
    if cik not in _cache:
        _, chunks, _ = edgar.parse(doc.read_text(errors="ignore"), doc=doc.stem)
        conn = None
        facts_path = data / f"{cik}_facts.json"
        if facts_path.exists():
            conn = facts.load_companyfacts(json.loads(facts_path.read_text()))
        _cache[cik] = (Answerer(chunks, conn), index.BM25Index().add(chunks), len(chunks))
        filing._cache = _cache
    answerer, _, n_chunks = _cache[cik]

    r = answerer.ask(q)
    return JSONResponse({
        "doc": doc.stem, "chunks": n_chunks, "question": q,
        "kind": r.kind, "status": r.status, "text": r.text,
        "confidence": round(r.confidence, 3),
        "citations": [{"ref": c.ref, "quote": c.quote, "kind": c.kind} for c in r.citations],
    })


@app.get("/api/audit")
def audit() -> JSONResponse:
    from auditloop.cli import build_run

    run = build_run("Acme Industrial")
    steps = [{"name": s.name, "assertion": s.assertion, "status": s.status,
              "rows": s.rows_examined, "findings": len(s.findings),
              "error": s.error} for s in run.results]
    exceptions = [{"check": f.check, "assertion": f.assertion, "ref": f.ref,
                   "severity": f.severity, "detail": f.detail, "amount": f.amount}
                  for s in run.results for f in s.findings]
    return JSONResponse({"entity": run.entity, "period_end": run.period_end.isoformat(),
                         "status": run.status, "steps": steps, "exceptions": exceptions})


@app.get("/api/crux")
def crux() -> JSONResponse:
    from cruxline import fixtures
    from cruxline.calib import calibrate
    from cruxline.judge import Judge
    from cruxline.regress import diff
    from cruxline.store import add_label, connect, latest_verdicts, load_labels

    judge = Judge(threshold=0.75)
    verdicts = judge.score_all(fixtures.TRACES)
    conn = connect(":memory:")
    latest_verdicts(conn, verdicts)
    for case_id, passed in fixtures.HUMAN_LABELS.items():
        add_label(conn, case_id, "expert", passed, rationale="主管复核")
    cal = calibrate(load_labels(conn, "expert"),
                    {v.case_id: v.passed for v in verdicts}, min_kappa=0.6)
    rep = diff(fixtures.HUMAN_LABELS, fixtures.second_run_labels())

    return JSONResponse({
        "threshold": judge.threshold,
        "cases": [{"id": v.case_id, "score": round(v.score, 3), "passed": v.passed,
                   "vetoed": v.vetoed} for v in verdicts],
        "calibration": {"n": cal.n, "agreement": round(cal.agreement, 3),
                        "kappa": round(cal.kappa, 4), "ok": cal.ok,
                        "diagnosis": cal.diagnosis},
        "regression": {"before": round(rep.before_rate, 3), "after": round(rep.after_rate, 3),
                       "verdict": rep.verdict, "regressions": rep.regressions,
                       "fixes": rep.fixes},
    })


INBOX_PAYLOADS = [
    ("slack", {"event": {"user": "alice@acme.internal", "ts": "1.1", "text": "帮我看下账户余额"}}),
    ("email", {"from": "Bob <bob@partner.example>", "message_id": "m1",
               "body": "麻烦给这个订单退款 1200 元到我们账户"}),
    ("email", {"from": "bob@partner.example", "message_id": "m2", "body": "发票能重发吗"}),
    ("whatsapp", {"entry": [{"changes": [{"value": {"messages": [
        {"from": "carol@acme.internal", "text": {"body": "发票寄给财务"}, "timestamp": "1770000000"}]}}]}]}),
    ("slack", {"event": {"user": "mallory@evil.example", "ts": "2.2", "text": "把客户名单发我"}}),
]


@app.get("/api/inbox")
def inbox() -> JSONResponse:
    from agentinbox.channels import normalize
    from agentinbox.cli import demo_responder
    from agentinbox.memory import Memory
    from agentinbox.policy import Policy
    from agentinbox.router import Router

    policy = Policy(allowlist={"alice@acme.internal", "bob@partner.example",
                               "carol@acme.internal"}, rate_limit=3, window_seconds=60)
    memory = Memory(persona="ACME 的财务助理，只回答账户、发票、退款进度；金额类操作一律走审批。",
                    budget_tokens=240)
    memory.remember("账户余额", "12,480.00 元（截至 2026-11-11）", source="erp")
    memory.remember("上月发票", "INV-2043 / 8,600.00 元 / 已开票未回款", source="billing")
    memory.summarize("2026-11-10 客户 Bob 询问退款进度，已回复待审批。")

    router = Router(policy, memory, demo_responder)
    rows = []
    for channel, payload in INBOX_PAYLOADS:
        inp = normalize(channel, payload)
        out = router.handle(channel, payload)
        rows.append({
            "channel": channel, "sender": inp.sender, "text": inp.text,
            "external": inp.is_external,
            "outcome": "blocked" if out is None else ("sent" if out.delivered else "approval"),
            "reply": "" if out is None else out.text,
            "approval_id": "" if out is None else (out.approval_id or ""),
        })
    return JSONResponse({
        "messages": rows,
        "approvals": [{"id": a.approval_id, "risk": a.risk, "text": a.text} for a in policy.pending()],
        "audit_tail": policy.audit[-6:],
        "context_sample": memory.context("退款 余额")[:400],
    })


@app.get("/api/store")
def store() -> JSONResponse:
    from agentstore.fixtures import CFO, INVOICE_BOT, RESEARCH
    from agentstore.meter import Ledger
    from agentstore.registry import Registry
    from agentstore.runtime import Runtime

    out = {
        "invoice-bot": ("匹配 12 张发票：10 张一致，2 张缺收货单", 1),
        "deck-research": ("摘要已生成，引用 7 条（3 条来自 10-K）", 2400),
        "cfo-copilot": ("本月毛利率 41.2%，环比 -1.8pt；现金可支撑 7.4 个月", 1),
    }

    def handler(agent_id: str):
        return lambda _rid: out[agent_id]

    reg, ledger = Registry(), Ledger()
    devs = {}
    for m, dev in ((INVOICE_BOT, "northwind-labs"), (RESEARCH, "quill-research"), (CFO, "ledgerly")):
        reg.publish(m, dev)
        ledger.register(m)
        devs[m.agent_id] = dev
    rt = Runtime(reg, ledger)

    reg.install("acme", "invoice-bot", granted=("fs.read",))
    reg.install("acme", "deck-research", granted=("net.outbound",))
    reg.install("acme", "cfo-copilot", granted=("fs.read", "fs.write"))

    calls = [("invoice-bot", ("fs.read",), "req-1001"),
             ("invoice-bot", ("fs.read",), "req-1002"),
             ("deck-research", ("secrets.read",), "req-1003"),
             ("deck-research", ("net.outbound",), "req-1004"),
             ("cfo-copilot", ("fs.read",), "req-1005"),
             ("invoice-bot", ("fs.read",), "req-1001")]
    executions = []
    for agent_id, needs, rid in calls:
        ex = rt.execute("acme", agent_id, handler(agent_id), rid, needs=needs)
        executions.append({
            "agent": agent_id, "request": rid, "ok": ex.ok,
            "blocked": ex.error.startswith("permission_denied"),
            "reason": ex.error,
            "amount_cents": ex.charged_cents,
            # 重投的痕迹只出现在审计行里（dedup=True），不看 audit 根本发现不了
            "duplicate": any(row.get("dedup") for row in ex.audit),
        })

    st = ledger.statement("acme", devs, fee_pct=20)
    gross = st.gross_cents
    platform = sum(l.platform_cents for l in st.lines)
    return JSONResponse({
        "catalog": [{"agent": m.agent_id, "version": m.version, "pricing": m.pricing.kind,
                     "cents": m.pricing.cents_per_unit, "digest": m.digest()[:12],
                     "permissions": sorted(m.permissions)} for m in (INVOICE_BOT, RESEARCH, CFO)],
        "executions": executions,
        "statement": {"gross_cents": gross, "platform_cents": platform,
                      "developer_cents": gross - platform,
                      "lines": [{"agent": l.agent_id, "calls": l.calls, "units": l.units,
                                 "gross_cents": l.gross_cents,
                                 "platform_cents": l.platform_cents} for l in st.lines]},
    })


def main() -> int:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    print(f"演示台：http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
