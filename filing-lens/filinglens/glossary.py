"""中文提问 → 英文关键词的桥。

10-K 是英文件，而用户用中文问。BM25 在跨语言上是零召回：中文被切成单字，
英文语料里一个都不出现，结果就是「明明在文件里，却答证据不足」。
这里用一张小而准的财务词表做查询扩展——不是翻译，只是把召回桥接过去；
答案仍然逐字引用英文原文，不生成任何译句。
"""

from __future__ import annotations

GLOSSARY: dict[str, str] = {
    # 财报科目
    "营收": "revenue net sales",
    "收入": "revenue net sales",
    "营业额": "revenue net sales",
    "净利润": "net income",
    "净利": "net income",
    "毛利": "gross margin gross profit",
    "毛利率": "gross margin",
    "营业利润": "operating income",
    "研发": "research development",
    "费用": "expense expenses",
    "成本": "cost of sales",
    "现金流": "cash flow",
    "资产负债": "total assets liabilities",
    "存货": "inventory",
    "应收": "accounts receivable",
    "回购": "repurchase",
    "股息": "dividend",
    "分红": "dividend",
    "税率": "effective tax rate",
    "毛利率变化": "gross margin",
    # 业务与风险
    "供应链": "supply chain suppliers manufacturing",
    "供应商": "suppliers contract manufacturers",
    "代工": "contract manufacturers outsourcing",
    "关税": "tariff tariffs trade",
    "贸易": "trade restrictions",
    "制裁": "sanctions export controls",
    "出口管制": "export controls",
    "竞争": "competition competitors",
    "客户": "customers",
    "渠道": "distribution channel resellers",
    "市场": "market",
    "中国": "China greater China",
    "欧洲": "Europe",
    "日本": "Japan",
    "印度": "India",
    "汇率": "foreign exchange rate",
    "通胀": "inflation",
    "利率": "interest rate",
    "诉讼": "legal proceedings litigation",
    "监管": "regulations regulatory",
    "合规": "compliance",
    "隐私": "privacy data protection",
    "网络攻击": "cyberattack cybersecurity",
    "安全": "security breach",
    "知识产权": "intellectual property",
    "专利": "patents",
    "员工": "employees full-time equivalent headcount workforce",
    "人力": "employees headcount",
    "高管": "executive officers",
    "董事会": "board of directors",
    "审计": "audit auditor",
    "内部控制": "internal control",
    "商誉": "goodwill",
    "减值": "impairment",
    "重组": "restructuring",
    "收购": "acquisition business combination",
    "分红政策": "dividend policy",
    "风险因素": "risk factors",
    "季节性": "seasonality",
    "产能": "capacity",
    "库存": "inventory",
    "物流": "logistics shipping",
    "原材料": "raw materials components",
    "芯片": "chip semiconductor silicon",
    "制造": "manufacturing",
    "外包": "outsourcing",
}

# 单字/双字也常见，但单字扩展噪声太大，只处理 >=2 字的键
def expand_groups(query: str) -> list[list[str]]:
    """按「概念」返回扩写词——一个中文词对应一组英文词，而不是一锅平铺的词。

    平铺会失真：供应链 → supply chain suppliers manufacturing，段落里只用上
    supply chain，覆盖率就被剩下两个词拉低，真答案被判成证据不足。
    """
    return [en.split() for zh, en in GLOSSARY.items() if zh in query]


def expand(query: str) -> str:
    extra: list[str] = []
    for zh, en in GLOSSARY.items():
        if zh in query:
            extra.append(en)
    if not extra:
        return query
    return query + " " + " ".join(dict.fromkeys(extra))
