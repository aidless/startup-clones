"""离线夹具：一份精简但结构完整的 10-K + 对应 XBRL companyfacts。

用途：没有网络、没有 SEC User-Agent 也能跑通全链路与测试。
"""
from __future__ import annotations

FAKE_10K_HTML = """
<html><body>
<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p>
<p>FORM 10-K — Acme Robotics, Inc. (CIK 0001234567) — Fiscal year ended 2025-12-31</p>

<p>Item 1. Business</p>
<p>Acme Robotics designs and sells autonomous mobile robots for warehouse logistics.
Our robots are sold on a subscription basis with a three-year minimum commitment.
We derived 62% of fiscal 2025 revenue from customers in North America and 38% from Europe.</p>
<p>We manufacture through two contract manufacturers in Taiwan and Mexico. A single supplier
provides the lidar module used in every robot; substituting that supplier would require
re-certification of the entire platform.</p>

<p>Item 1A. Risk Factors</p>
<p>Supply chain concentration is our most significant operational risk. The lidar module is
sourced from one supplier, and lead times have ranged from 14 to 40 weeks. Any interruption
in lidar supply would delay customer deployments and could trigger contractual penalties.</p>
<p>We depend on a limited number of large customers. Our top five customers accounted for
48% of revenue in fiscal 2025. The loss of any one of them would materially reduce revenue.</p>
<p>Our subscription model requires significant upfront capital expenditure. If customers
terminate early, we may be unable to recover the deployed hardware cost.</p>

<p>Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations</p>
<p>Total revenue increased 35% to $175.0 million in fiscal 2025, driven by a 41% increase in
subscription revenue and a 12% increase in hardware revenue. Gross margin improved from 51%
to 55% as service costs per robot declined.</p>
<p>Research and development expense increased to $33.0 million, or 19% of revenue, as we
expanded the autonomy software team. We expect research and development expense to grow in
absolute dollars but decline as a percentage of revenue over time.</p>
<p>Net income was $15.0 million in fiscal 2025 compared with $8.0 million in fiscal 2024.
The improvement was primarily attributable to operating leverage and a one-time gain on the
sale of a former manufacturing facility.</p>

<p>Item 8. Financial Statements and Supplementary Data</p>
<table>
<tr><th>Year ended December 31</th><th>2025</th><th>2024</th><th>2023</th></tr>
<tr><td>Revenue</td><td>175,000</td><td>130,000</td><td>100,000</td></tr>
<tr><td>Gross profit</td><td>96,250</td><td>66,300</td><td>47,000</td></tr>
<tr><td>Net income</td><td>15,000</td><td>8,000</td><td>10,000</td></tr>
</table>
</body></html>
"""


def _facts(tag: str, values: dict[int, float]) -> dict:
    entries = [
        {"fy": fy, "fp": "FY", "form": "10-K", "end": f"{fy}-12-31", "val": v,
         "filed": f"{fy + 1}-02-15", "accn": f"0001234567-{fy}-000001", "frame": f"CY{fy}"}
        for fy, v in values.items()
    ]
    return {"label": tag, "units": {"USD": entries}}


FAKE_FACTS = {
    "cik": 1234567,
    "entityName": "Acme Robotics, Inc.",
    "facts": {
        "us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": _facts(
                "Revenue", {2023: 100_000_000, 2024: 130_000_000, 2025: 175_000_000}),
            "GrossProfit": _facts("Gross Profit", {2023: 47_000_000, 2024: 66_300_000, 2025: 96_250_000}),
            "NetIncomeLoss": _facts("Net Income", {2023: 10_000_000, 2024: 8_000_000, 2025: 15_000_000}),
            "ResearchAndDevelopmentExpense": _facts("R&D", {2023: 20_000_000, 2024: 26_000_000, 2025: 33_000_000}),
        }
    },
}
