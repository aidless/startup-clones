"""R3 审查发现（geo-radar）的复现测试：先红后绿。

四条都来自第三方审查报告 `docs/REVIEW-R3-filing-geo.md`，第 1 条是真实 run 就能看到的：

- P0-4 差距句把三个维度用一句话下结论：`gap_sov < 0` 就先写「领先」，然后把
  出现率差、位次差**取反后照抄**——于是出现「出现率多 -1 条」「平均位次领先 -0.8 位」
  这种负数量的「领先」，以及声量持平但位次差为正时印「平均位次差 2.0 位」。
  三个维度各有各的方向，必须各判各的。
- P2-3 声量份额差是**百分点**，印成 `%` 会被读成相对变化。
- P2-4 零提及的品牌 `avg_position` 返回 0.0，报表里 0.0 是最**好**的名次。
- P1-1 `georadar.cli demo` 手搓 Namespace 漏了 `json` 字段：串到 `cmd_run` 里
  `AttributeError` 退出 1，而 `save_run` 已经落库——崩在写完一半之后。
- P2-2 README 说 `--provider ollama` 没接线、CLI choices 里没这个值（实际有），
  而 README 教用户用的 `--provider=magpie` 反而真的不在 choices 里：说法和实现对调了。
"""
from __future__ import annotations

import pytest

from georadar import cli, report, store
from georadar.metrics import BrandStats


def _stat(brand: str, mentions: int, prompts_seen: int, positions: list[int],
          total: int) -> BrandStats:
    s = BrandStats(brand=brand, mentions=mentions, prompts_seen=prompts_seen,
                   positions=list(positions))
    s._total_mentions = total
    return s


def _md(stats: dict[str, BrandStats], brand: str = "Acme",
        competitors: list[str] | None = None, prompts_total: int = 10) -> str:
    return report.markdown_report(brand, "AI SRE", competitors or ["Rival"],
                                  stats, [], [], prompts_total)


def _gap_sentence(md: str) -> str:
    return md.split("## 2. 差距")[1].split("## 3.")[0]


# ---------------------------------------------------------------- P0-4 方向

def test_each_dimension_is_judged_on_its_own_direction():
    """声量落后、出现率多、位次领先：三种方向同时出现，不能共用「领先/落后」一个词。"""
    stats = {
        # 竞品声量更高（8/20 > 6/20），但出现率更低（2 < 4 条提示词），位次更差（3.0 > 1.5）
        "Acme": _stat("Acme", mentions=6, prompts_seen=4, positions=[1, 2], total=20),
        "Rival": _stat("Rival", mentions=8, prompts_seen=2, positions=[3], total=20),
    }
    gap = _gap_sentence(_md(stats))
    assert "声量落后" in gap, gap
    assert "出现率多 **2** 条提示词" in gap, gap
    assert "平均位次领先 **1.5** 位" in gap, gap
    assert "落后 -" not in gap and "多 **-" not in gap and "领先 **-" not in gap, gap


def test_lagging_visibility_is_not_printed_as_negative_count():
    """出现率差为负时旧代码印「出现率少 -1 条提示词」。"""
    stats = {
        "Acme": _stat("Acme", mentions=6, prompts_seen=5, positions=[1], total=20),
        "Rival": _stat("Rival", mentions=6, prompts_seen=4, positions=[1], total=20),
    }
    gap = _gap_sentence(_md(stats))
    assert "出现率多 **1** 条提示词" in gap, gap
    assert "-1" not in gap, gap


def test_tie_on_voice_keeps_even_wording_and_reports_position_direction():
    """声量/出现率并列时保留「持平」，但位次这一维仍要说出方向（差 1 位是我们领先）。"""
    stats = {
        "Acme": _stat("Acme", mentions=4, prompts_seen=2, positions=[1], total=8),
        "Traversal": _stat("Traversal", mentions=4, prompts_seen=2, positions=[2], total=8),
    }
    gap = _gap_sentence(_md(stats, competitors=["Traversal"]))
    assert "持平" in gap, gap
    assert "平均位次领先 **1.0** 位" in gap, gap
    assert "落后 **Traversal** 声量 **0.0%" not in gap, gap


# ------------------------------------------------------ P2-3 百分点 vs 百分比

def test_voice_gap_is_printed_in_percentage_points():
    stats = {
        "Acme": _stat("Acme", mentions=6, prompts_seen=4, positions=[1], total=20),
        "Rival": _stat("Rival", mentions=8, prompts_seen=4, positions=[1], total=20),
    }
    gap = _gap_sentence(_md(stats))
    assert "**10.0 个百分点**" in gap, gap
    assert "**10.0%**" not in gap, gap


# ------------------------------------------------ P2-4 零提及的 avg_position

def test_brand_without_mentions_has_no_average_position():
    s = BrandStats(brand="Ghost")
    assert s.avg_position is None, "零提及被算成 0.0 位，看起来是第一名"


def test_report_prints_dash_for_missing_position():
    stats = {
        "Acme": _stat("Acme", mentions=2, prompts_seen=2, positions=[1, 2], total=4),
        "Ghost": BrandStats(brand="Ghost"),   # 有统计行、但没有位次
    }
    stats["Ghost"]._total_mentions = 4
    md = _md(stats)
    ghost_line = next(l for l in md.splitlines() if l.startswith("| Ghost "))
    assert "| — |" in ghost_line, ghost_line
    assert "| 0.0 |" not in ghost_line, ghost_line


# ------------------------------------------------------------ P1-1 demo 崩溃

def test_demo_runs_without_attribute_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = cli.main(["demo"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "差距" in out, out[:400]
    assert "AttributeError" not in out
    conn = store.connect(tmp_path / "georadar.db")
    runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    answers = conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
    assert runs == 1 and answers > 0, (runs, answers)


def test_demo_leaves_no_partial_run_behind(tmp_path, monkeypatch):
    """崩在 save_run 之后的半截状态：渲染阶段失败时库里不能留下 run。"""
    monkeypatch.chdir(tmp_path)

    def boom(*_a, **_kw):
        raise RuntimeError("模拟渲染阶段失败")

    monkeypatch.setattr(report, "markdown_report", boom)
    try:
        cli.main(["demo"])
    except RuntimeError:
        pass
    conn = store.connect(tmp_path / "georadar.db")
    runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    assert runs == 0, "渲染失败却已落库，用户拿到一份打不开的报告"


# -------------------------------------------------- P2-2 provider 说法与实现对调

def test_cli_choices_include_every_documented_provider():
    """判据是「parser 里注册了哪些 choices」，不是「argparse 报错文案里有没有引号」。

    原来断言 `"'ollama'" in err`：argparse 在不同 Python 补丁版本里对 choices 的
    渲染不一样（3.12.3 带引号、3.12.16 不带），这条测试会在 CI 上按版本翻脸。
    """
    parser = cli.build_parser()
    run = dict(parser._subparsers._group_actions[0].choices)["run"]
    provider = next(a for a in run._actions if a.dest == "provider")
    assert provider.choices == ["mock", "ollama", "openai", "openai-compat",
                               "deepseek", "kimi", "vllm", "magpie"]
    assert "magpie" in provider.choices, "README 教用户写 --provider magpie，choices 里却没有它"


def test_invalid_provider_exits_2_regardless_of_message_wording(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--brand", "A", "--category", "C", "--provider", "bogus"])
    assert exc.value.code == 2
    assert "bogus" in capsys.readouterr().err


def test_readme_provider_table_matches_choices():
    from pathlib import Path

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "未接线" not in readme, "ollama 已接线，README 仍说没接线"
    assert "--provider magpie" in readme or "--provider=magpie" in readme
