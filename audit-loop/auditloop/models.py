"""审计数据模型：全部用纯 dataclass，方便从 CSV / Excel / ERP 导出的表格逐行构造。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# 审计认定（assertions）—— 每个检查都必须挂一个，否则底稿无法被复核
EXISTENCE = "存在性"
COMPLETENESS = "完整性"
VALUATION = "计价与分摊"
CUTOFF = "截止"
RIGHTS = "权利与义务"
CLASSIFICATION = "分类"


@dataclass
class Entry:
    """总账分录（现金科目用）。"""
    entry_id: str
    date: date
    account: str
    debit: float = 0.0
    credit: float = 0.0
    memo: str = ""
    vendor: str = ""

    @property
    def amount(self) -> float:
        return round(self.debit - self.credit, 2)


@dataclass
class BankLine:
    line_id: str
    date: date
    amount: float          # 正=存入，负=支出
    memo: str = ""


@dataclass
class Invoice:
    invoice_id: str
    customer: str
    amount: float
    issue_date: date
    due_date: date
    shipped_date: date | None = None
    revenue_date: date | None = None

    @property
    def recognized(self) -> bool:
        return self.revenue_date is not None


@dataclass
class Finding:
    check: str
    assertion: str
    ref: str
    severity: str          # high | medium | low
    detail: str
    amount: float = 0.0


@dataclass
class StepResult:
    name: str
    assertion: str
    status: str = "ok"     # ok | error
    findings: list[Finding] = field(default_factory=list)
    rows_examined: int = 0
    error: str = ""

    @property
    def high(self) -> int:
        return sum(1 for f in self.findings if f.severity == "high")
