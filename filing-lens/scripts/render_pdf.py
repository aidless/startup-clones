"""把差异表 markdown 导成可直接发给客户的 PDF。

为什么不是 reportlab：差异表的主体是宽表格 + 中文 + 行内代码（`XBRL:TAG@2026`）。
reportlab 要自己做表格折行、CJK 字体注册和单元格样式，改一次表头就得重调版面；
Chrome 的无头打印一行命令就把 HTML 表格排好，中文字体走 fontconfig。
所以链路是 markdown → 极简 HTML（只认差异表真用到的那几种语法）→ Chrome 打印。

依赖：本机 `google-chrome`。缺了会抛 `PDFUnavailable`，由调用方决定怎么处置 ——
不要静默产出一个空 PDF。
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

CHROME = ("google-chrome", "chromium", "chromium-browser", "chrome")

_CSS = """
@page { size: A4; margin: 14mm 12mm; }
body { font-family: "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Zen Hei",
       "DejaVu Sans", sans-serif; font-size: 9.5pt; line-height: 1.45; color: #111; }
h1 { font-size: 15pt; margin: 0 0 6pt; }
h2 { font-size: 11pt; margin: 14pt 0 4pt; border-bottom: 0.6pt solid #999; padding-bottom: 2pt; }
ul { margin: 3pt 0 3pt 14pt; padding: 0; }
li { margin: 1.5pt 0; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; table-layout: fixed; }
th, td { border: 0.5pt solid #777; padding: 3pt 4pt; vertical-align: top;
         font-size: 8.5pt; word-break: break-word; }
th { background: #eee; text-align: left; }
code { font-family: "DejaVu Sans Mono", monospace; font-size: 8pt; }
p { margin: 4pt 0; }
"""


class PDFUnavailable(RuntimeError):
    """本机没有可用的无头浏览器。"""


def _browser() -> str:
    for name in CHROME:
        path = shutil.which(name)
        if path:
            return path
    raise PDFUnavailable("找不到 google-chrome / chromium，无法导出 PDF")


def _inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    return out


def _cells(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def markdown_to_html(md: str, title: str = "") -> str:
    """只支持差异表用到的语法：`#`/`##` 标题、`-` 列表、`|` 表格、行内 `code`/`**bold**`。

    刻意不做通用 markdown：通用转换器会把表格里的 `|` 和 `XBRL:A@2026` 这类
    行内代码吃掉，宁可窄也要稳。
    """
    body: list[str] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("|"):
            header = _cells(stripped)
            i += 1
            rows: list[list[str]] = []
            if i < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i]):
                i += 1
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            body.append("<table><thead><tr>"
                        + "".join(f"<th>{_inline(c)}</th>" for c in header)
                        + "</tr></thead><tbody>")
            for row in rows:
                body.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>")
            body.append("</tbody></table>")
            continue
        if stripped.startswith("#"):
            level = min(len(stripped) - len(stripped.lstrip("#")), 3)
            body.append(f"<h{level}>{_inline(stripped.lstrip('#').strip())}</h{level}>")
            i += 1
            continue
        if stripped.startswith("- "):
            body.append("<ul>")
            while i < len(lines) and lines[i].strip().startswith("- "):
                body.append(f"<li>{_inline(lines[i].strip()[2:])}</li>")
                i += 1
            body.append("</ul>")
            continue
        body.append(f"<p>{_inline(stripped)}</p>")
        i += 1
    head = f"<title>{html.escape(title)}</title>" if title else ""
    return ("<!doctype html><html><head><meta charset=\"utf-8\">"
            f"{head}<style>{_CSS}</style></head><body>"
            + "\n".join(body) + "</body></html>")


def render_pdf(md: str, out: str | Path, title: str = "") -> Path:
    """markdown → PDF。返回落盘路径。"""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    browser = _browser()
    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "report.html"
        page.write_text(markdown_to_html(md, title=title or out.stem), encoding="utf-8")
        proc = subprocess.run(
            [browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
             f"--print-to-pdf={out}", page.as_uri()],
            capture_output=True, text=True, timeout=180)
    if not out.exists() or out.stat().st_size < 1024:
        raise PDFUnavailable(
            f"Chrome 没有产出有效 PDF（exit={proc.returncode}）：{proc.stderr[-400:]}")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="render_pdf", description="markdown 差异表 → PDF")
    ap.add_argument("md")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args(argv)
    path = render_pdf(Path(a.md).read_text(encoding="utf-8"), a.out)
    print(f"写出 {path}（{path.stat().st_size} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
