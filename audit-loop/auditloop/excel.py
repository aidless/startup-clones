"""Excel 进出：审计师填的是 Excel，分析性程序吃的是年度序列 dict。

这一层只做两件事，都要求**可逆且不撒谎**：

1. `write_facts_template()` 写一张审计师看得懂的模板 —— 表头是中文科目名，
   单位写在第二行注释里，下面四行是可直接替换成自家数的示例。
2. `read_facts()` 把填好的表读回 `{"entity": ..., "years": {...}}`，
   **空单元格表示「这家没这个数」，不是 0**。写 0 会让毛利率、现金含量算出
   一个凭空成立的结论；缺失只会让那条程序报「数据不足」，那是诚实的。
"""
from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook, load_workbook

SHEET = "年度数据"
HEADERS = ["年度", "营业收入", "应收账款", "毛利", "经营活动现金流"]
UNIT_NOTE = "单位：元，可只填有数据的年份"
ENTITY_PREFIX = "主体："

# 列号（1-based）→ facts JSON 里的字段名。顺序与 HEADERS 一一对应。
FIELDS = {1: "year", 2: "revenue", 3: "receivables", 4: "gross_profit", 5: "cfo"}
DATA_START_ROW = 3  # 1=表头，2=单位说明，3 起是数据

SAMPLE_ROWS = [
    (2023, 1000.0, 100.0, 400.0, 250.0),
    (2024, 1050.0, 108.0, 420.0, 210.0),
    (2025, 1100.0, 115.0, 462.0, 200.0),
    (2026, 1155.0, 250.0, 530.0, 150.0),
]


def write_facts_template(path: str | Path, entity: str = "Acme Industrial") -> Path:
    """写出分析性程序的填空模板，返回实际写入的路径。

    表头逐字固定（`read_facts` 按它认表），第二行是给人看的单位说明，
    A 列非数字的行会被 `read_facts` 当注释跳过 —— 所以说明行可以随便改字，
    但不要删掉它上面的表头。
    """
    p = Path(path)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append(HEADERS)
    ws.append([UNIT_NOTE])
    # 主体名放在表头右侧，用户改公司名不用碰数据区；读回时按「主体：」前缀解析。
    ws.cell(row=1, column=7, value=f"{ENTITY_PREFIX}{entity}")
    for row in SAMPLE_ROWS:
        ws.append(list(row))
    # 年度按整数显示，别让 Excel 把 2023 显示成 2,023.00
    for r in range(DATA_START_ROW, DATA_START_ROW + len(SAMPLE_ROWS)):
        ws.cell(row=r, column=1).number_format = "0"
    ws.freeze_panes = f"A{DATA_START_ROW}"
    widths = {"A": 10, "B": 16, "C": 16, "D": 16, "E": 20, "G": 28}
    for col, width in widths.items():
        ws.column_dimensions[col].width = width
    wb.save(p)
    return p


def _parse_year(value: object, row: int) -> int:
    """年度列必须是数字（或纯数字字符串）。报错必须带行号 —— 现场只看报错文本。"""
    if isinstance(value, bool):
        raise ValueError(f"第 {row} 行：年度 {value!r} 不是数字")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise ValueError(f"第 {row} 行：年度 {value!r} 不是整数年份")
    if isinstance(value, str):
        text = value.strip()
        # 容忍 "2023年" / "FY2023" 这类手工输入
        cleaned = text.replace("FY", "").replace("fy", "").rstrip("年").strip()
        try:
            return int(cleaned)
        except ValueError:
            raise ValueError(f"第 {row} 行：年度 {value!r} 不是数字") from None
    raise ValueError(f"第 {row} 行：年度 {value!r} 不是数字")


def _number(value: object, row: int, header: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"第 {row} 行：{header} {value!r} 不是数字")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", ""))
        except ValueError:
            pass
    raise ValueError(f"第 {row} 行：{header} {value!r} 不是数字")


def _check_headers(ws) -> None:
    actual = [ws.cell(row=1, column=i + 1).value for i in range(len(HEADERS))]
    normalized = [str(v).strip() if v is not None else "" for v in actual]
    if normalized != HEADERS:
        raise ValueError(
            f"表头认不出：期望 {HEADERS}，实际 {normalized}。"
            f"请使用 auditloop init 生成的模板，或把第一行改成上述五个表头。"
        )


def _entity(ws, path: Path) -> str:
    for col in range(6, 12):
        value = ws.cell(row=1, column=col).value
        if isinstance(value, str) and value.startswith(ENTITY_PREFIX):
            return value[len(ENTITY_PREFIX):].strip() or path.stem
    return path.stem


def read_facts_xlsx(path: str | Path) -> dict:
    """读 `.xlsx`，产出与 `acme_annual.json` 同构的 dict。"""
    p = Path(path)
    wb = load_workbook(p, data_only=True)
    if SHEET not in wb.sheetnames:
        raise ValueError(
            f"找不到工作表 {SHEET!r}（现有：{wb.sheetnames}）。"
            f"请使用 auditloop init 生成的模板。"
        )
    ws = wb[SHEET]
    _check_headers(ws)

    years: dict[str, dict[str, float]] = {}
    seen: dict[int, int] = {}  # 年份 → 首次出现的行号，重复年份要报错而不是静默覆盖
    for row in range(DATA_START_ROW, ws.max_row + 1):
        raw = {col: ws.cell(row=row, column=col).value for col in FIELDS}
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in raw.values()):
            continue  # 整行空：模板尾部或用户删掉的行
        year_cell = raw[1]
        if isinstance(year_cell, str) and year_cell.strip().startswith(("单位", "注释", "说明")):
            continue  # 注释性说明行（模板第二行就是这种）
        if year_cell is None or (isinstance(year_cell, str) and not year_cell.strip()):
            raise ValueError(f"第 {row} 行：年度为空，但有数据填在旁边")

        year = _parse_year(year_cell, row)
        if year in seen:
            raise ValueError(
                f"第 {row} 行：年度 {year} 与第 {seen[year]} 行重复，"
                f"一个年度只能有一行"
            )
        seen[year] = row

        record: dict[str, float] = {}
        for col, field in FIELDS.items():
            if field == "year":
                continue
            value = raw[col]
            if value is None or (isinstance(value, str) and not value.strip()):
                continue  # 空单元格 = 这个字段缺失，不是 0
            record[field] = _number(value, row, HEADERS[col - 1])
        years[str(year)] = record

    if not years:
        raise ValueError(f"{SHEET!r} 里没有任何数据行：请填入至少一个年度的营业收入")
    return {"entity": _entity(ws, p), "years": years}


def read_facts(path: str | Path) -> dict:
    """读 facts：按后缀分派 `.xlsx` / `.json`，两种输入同构。"""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".xlsx":
        return read_facts_xlsx(p)
    if suffix == ".json":
        payload = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("facts JSON 顶层必须是对象")
        if not isinstance(payload.get("years"), dict) or not payload["years"]:
            raise ValueError("facts JSON 里没有 years 对象")
        return payload
    raise ValueError(f"不认识的扩展名 {p.suffix!r}：只支持 .xlsx 与 .json")
