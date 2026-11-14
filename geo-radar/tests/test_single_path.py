"""单一路径回归：`run`（内存）与 `report --run-id`（读库）必须共用同一个装配函数。

背景（2026-11-13）：store 主键补上 run_index、span 去重修完之后，两条路径的**结果**
对上了（72 条提及 / 34.7% / 1.52），但代码仍是两份各自拼 stats 的逻辑：

- `cli.cmd_run`  → `metrics.brand_stats(all_mentions, len(ps))` + 内存里的 answers；
- `cli.cmd_report` → `metrics.brand_stats(mentions, len(ids))` + 从 SQLite 读回的 answers。

两份逻辑今天恰好给出同一个数（分母碰巧相等），谁改一处忘另一处就静默分叉。
本文件把「同一批 answers/mentions 走两条路径得到同一份 markdown」钉成断言，
并要求只存在一个装载入口 `georadar.view.load_view(conn, run_id)`（内存侧对应
`georadar.view.assemble(run, mentions)`）。

等价边界（实测，不是假设）：markdown_report 里**没有** run_id / created_at 等
run 级标识，所以两条路径的 markdown 可以逐字节相等，不需要「去掉时间戳再比」。
run 级元数据只活在 SQLite 的 runs 表里 —— 这一条由
`test_markdown_has_no_run_level_identifiers` 反向钉住（换 run_id/时间戳，markdown 不变）。
"""
from __future__ import annotations

import inspect

from georadar import cli, store
from georadar.extract import find_mentions
from georadar.models import Run
from georadar.providers import MockProvider

BRANDS = ["Acme", "Traversal", "Rootly"]
COMPETITORS = ["Traversal", "Rootly"]


def _view():
    """实现前这里必然抛 ModuleNotFoundError —— 这就是红灯（统一装载入口还不存在）。"""
    import importlib
    return importlib.import_module("georadar.view")


def _build_run(run_id: str, created_at: str = "2026-11-14T00:00:00+00:00"):
    """真实抽取链路：MockProvider → find_mentions，6 条提示词 × 3 次采样。"""
    prov = MockProvider(BRANDS, seed=7)
    run = Run(run_id=run_id, brand="Acme", category="AI SRE",
              competitors=list(COMPETITORS), provider="mock", created_at=created_at)
    mentions = []
    for p in range(6):
        for i in range(3):
            a = prov.complete(f"best AI SRE in 2026 #{p}", run_index=i)
            a.prompt_id = f"p{p}"
            run.answers.append(a)
            mentions.extend(find_mentions(a, BRANDS))
    return run, mentions


def _first_diff(a: str, b: str) -> str:
    la, lb = a.splitlines(), b.splitlines()
    for i, (x, y) in enumerate(zip(la, lb)):
        if x != y:
            return f"第 {i + 1} 行不同：\n  内存: {x!r}\n  读库: {y!r}"
    return f"行数不同：内存 {len(la)} 行，读库 {len(lb)} 行"


def test_single_load_entrypoint_exists(tmp_path):
    """唯一装载入口：view.load_view(conn, run_id) 一次给出 run/stats/mentions/answers。"""
    conn = store.connect(tmp_path / "v.db")
    run, mentions = _build_run("run-a")
    store.save_run(conn, run, mentions)

    view = _view()
    assert hasattr(view, "load_view"), "缺少单一装载入口 georadar.view.load_view"
    got = view.load_view(conn, run.run_id)

    assert got.run.run_id == "run-a"
    assert got.run.created_at == run.created_at
    assert len(got.answers) == len(run.answers)
    assert len(got.mentions) == len(mentions)
    assert set(got.stats) == set(BRANDS)
    assert got.prompts_total == 6

    # 内存侧同一批数据走 assemble()，stats 必须与读库路径逐项相同
    mem = view.assemble(run, mentions)
    assert mem.prompts_total == got.prompts_total
    for name in BRANDS:
        assert mem.stats[name].mentions == got.stats[name].mentions
        assert mem.stats[name].prompts_seen == got.stats[name].prompts_seen
        assert mem.stats[name].share_of_voice == got.stats[name].share_of_voice
        assert mem.stats[name].avg_position == got.stats[name].avg_position
        assert mem.stats[name].sentiment == got.stats[name].sentiment


def test_memory_and_db_paths_render_identical_markdown(tmp_path):
    """核心不变量：内存渲染 == 写库再读回渲染（逐字节）。"""
    run, mentions = _build_run("run-mem")
    memory_md = _view().assemble(run, mentions).markdown

    conn = store.connect(tmp_path / "r.db")
    store.save_run(conn, run, mentions)
    db_md = _view().load_view(conn, run.run_id).markdown

    assert memory_md == db_md, _first_diff(memory_md, db_md)


def test_markdown_has_no_run_level_identifiers():
    """反向钉住等价边界：markdown 里没有 run 级标识，换 run_id/时间戳输出不变。"""
    run_a, ms_a = _build_run("run-a", "2026-11-14T00:00:00+00:00")
    run_b, ms_b = _build_run("run-b", "2027-01-01T12:34:56+00:00")
    md_a = _view().assemble(run_a, ms_a).markdown
    md_b = _view().assemble(run_b, ms_b).markdown
    assert md_a == md_b, _first_diff(md_a, md_b)
    assert "run-a" not in md_a and "run-b" not in md_b
    assert "2026-11-14" not in md_a and "2027-01-01" not in md_b


def test_both_cli_commands_route_through_single_loader():
    """结构性断言：两条命令的源码里都必须出现同一个装载入口。"""
    for fn in (cli.cmd_run, cli.cmd_report):
        src = inspect.getsource(fn)
        assert "load_view" in src, f"{fn.__name__} 没有走单一装载入口 load_view"


def test_cli_run_markdown_equals_report_run_id(tmp_path, capsys):
    """端到端：`run --out x.md` 落盘的 markdown == `report --run-id` 打印的 markdown。"""
    db = tmp_path / "cli.db"
    out = tmp_path / "r.md"
    rc = cli.main(["run", "--brand", "Acme", "--category", "AI SRE",
                   "--competitors", "Traversal,Rootly", "--provider", "mock",
                   "--repeat", "3", "--limit", "6", "--db", str(db), "--out", str(out)])
    assert rc == 0
    printed = capsys.readouterr().out
    run_id = next(line.split(":", 1)[1].strip()
                  for line in printed.splitlines() if line.startswith("run_id"))
    md_from_run = out.read_text(encoding="utf-8")

    rc = cli.main(["report", "--db", str(db), "--run-id", run_id])
    assert rc == 0
    md_from_report = capsys.readouterr().out

    # 逐字节相等（含行尾）：diff 不许只剩一个换行符的差异
    assert md_from_run == md_from_report, _first_diff(md_from_run, md_from_report)
