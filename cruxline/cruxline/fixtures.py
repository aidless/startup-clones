"""夹具：8 条 agent 轨迹 + 人工标注，覆盖 5 种失败模式。

每条轨迹的失败原因在 tests 里被逐条断言 —— 夹具不是「差不多」，是检测能力的证明。
"""
from __future__ import annotations

from .trace import ToolCall, Trace


def _t(case_id: str, output: str, tools: list[ToolCall], meta: dict | None = None) -> Trace:
    return Trace(case_id=case_id, input=f"客户问题 {case_id}", output=output,
                 tool_calls=tools, meta=meta or {})


SEARCH_OK = ToolCall("search_orders", {"q": "A100"}, result="找到 2 条订单")
REFUND_OK = ToolCall("create_refund", {"order": "A100", "amount": 120}, result="退款单 R-77 已创建")

TRACES: list[Trace] = [
    # 1) 好：查单 → 退款，答案含期望要点
    _t("c1", "已为订单 A100 创建退款，金额 120 元，退款单号 R-77。",
       [SEARCH_OK, REFUND_OK], {"expected_terms": ["退款", "R-77", "120"], "max_steps": 4}),
    # 2) 差：全程不查工具，直接凭记忆答
    _t("c2", "订单 A100 的退款应该已经处理好了，请稍等。",
       [], {"expected_terms": ["退款单号", "金额"], "max_steps": 4}),
    # 3) 差：工具报错后继续编
    _t("c3", "退款已成功，单号 R-99。",
       [ToolCall("create_refund", {"order": "A100"}, error="payment gateway 502")],
       {"expected_terms": ["退款", "R-99"], "max_steps": 4}),
    # 4) 差：拒答
    _t("c4", "抱歉，我不能帮你操作退款，请自行联系银行。",
       [SEARCH_OK], {"expected_terms": ["退款"], "max_steps": 4}),
    # 5) 差：死循环超预算
    _t("c5", "正在查询……（已查询 9 次）",
       [SEARCH_OK] * 9, {"expected_terms": ["退款单号"], "max_steps": 4}),
    # 6) 差：答了但答不到点子上
    _t("c6", "我帮你看了下，这个订单属于售后范围，建议联系人工客服。",
       [SEARCH_OK], {"expected_terms": ["退款", "R-77", "金额"], "max_steps": 4}),
    # 7) 好：多工具链路完整
    _t("c7", "已核对订单 A101 状态为已签收，退款 260 元，单号 R-78。",
       [ToolCall("search_orders", {"q": "A101"}, result="已签收"),
        ToolCall("check_policy", {"order": "A101"}, result="7 天内可退"),
        ToolCall("create_refund", {"order": "A101", "amount": 260}, result="R-78")],
       {"expected_terms": ["退款", "R-78", "260"], "max_steps": 5}),
    # 8) 差：报错 + 拒答
    _t("c8", "抱歉，我无法协助处理。",
       [ToolCall("create_refund", {"order": "A102"}, error="timeout")],
       {"expected_terms": ["退款"], "max_steps": 4}),
]

# 人工标注（资深客服主管逐条复核）
HUMAN_LABELS: dict[str, bool] = {
    "c1": True, "c2": False, "c3": False, "c4": False,
    "c5": False, "c6": False, "c7": True, "c8": False,
}


def second_run_labels() -> dict[str, bool]:
    """模拟新版 agent 的一次运行：修好 c2/c6，弄坏 c1。"""
    return {"c1": False, "c2": True, "c3": False, "c4": False,
            "c5": False, "c6": True, "c7": True, "c8": False}
