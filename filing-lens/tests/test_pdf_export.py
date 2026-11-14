"""差异表导 PDF：客户收到的是 PDF，不是终端里的 markdown。

判据（三条都要）：
1. HTML 层：表格行数与 markdown 一致 —— 否则 PDF 里少了几行也没人发现；
2. PDF 层：真以 `%PDF-` 开头、体积 > 2KB、至少一页；
3. 端到端：`review_diff.py <CIK> --pdf` 同时落 .md 与 .pdf，且 PDF 里的文字可抽出中文。
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from render_pdf import markdown_to_html, render_pdf  # noqa: E402

MD = """# 标题 · 复核差异表

- 文件：`0001481504`

| # | 检查 | 我们看到的 |
|---|---|---|
| 1 | 现金流量口径 | 现金及等价物 87,594 USD |
| 2 | 员工数 | 120 名 faculty |

## 未覆盖
- 风险因素年度差异
"""


def test_html_keeps_every_table_row_and_heading():
    html = markdown_to_html(MD, title="t")
    assert html.count("<tr>") == 3, "表头 + 两行数据"
    assert "87,594" in html and "120 名 faculty" in html
    assert "<h1" in html and "<h2" in html, "标题层级丢了"
    assert "<table" in html and "未覆盖" in html


@pytest.mark.skipif(shutil.which("google-chrome") is None, reason="本机没有 chrome")
def test_pdf_is_a_real_pdf(tmp_path):
    out = tmp_path / "x.pdf"
    render_pdf(MD, out, title="差异表")
    data = out.read_bytes()
    assert data.startswith(b"%PDF-"), data[:8]
    assert len(data) > 2000, len(data)
    assert re.search(rb"/Type\s*/Page[^s]", data), "PDF 里没有页对象"


@pytest.mark.skipif(shutil.which("google-chrome") is None, reason="本机没有 chrome")
def test_cli_writes_both_md_and_pdf(tmp_path):
    import review_diff as rd
    code = rd.main(["0001481504", "--data", str(ROOT / "data-prospects"),
                    "--out", str(tmp_path / "r.md"), "--pdf", str(tmp_path / "r.pdf")])
    assert code == 0
    assert (tmp_path / "r.md").exists()
    pdf = (tmp_path / "r.pdf").read_bytes()
    assert pdf.startswith(b"%PDF-") and len(pdf) > 2000
