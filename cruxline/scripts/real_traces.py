"""用真实 agent 轨迹跑编码 agent rubric，看规则到底抓到了什么。

    python scripts/export_dsh_traces.py --limit 40
    python scripts/real_traces.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cruxline.judge import Judge  # noqa: E402
from cruxline.rubrics import agent_rubric  # noqa: E402
from cruxline.trace import Trace  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    path = ROOT / "data/traces.jsonl"
    if not path.exists():
        print("先跑 scripts/export_dsh_traces.py")
        return 2
    traces = [Trace.from_dict(json.loads(l)) for l in path.read_text().splitlines() if l.strip()]
    judge = Judge(rubric=agent_rubric(), threshold=0.75)
    verdicts = judge.score_all(traces)

    fails = [v for v in verdicts if not v.passed]
    print(f"{len(verdicts)} 条真实轨迹：PASS {len(verdicts)-len(fails)} / FAIL {len(fails)}\n")

    rule_fail = Counter()
    for v in verdicts:
        for d in v.details:
            if d.score == 0.0:
                rule_fail[d.name] += 1
    print("各规则命中次数（0 分的规则才计入）：")
    for name, n in rule_fail.most_common():
        print(f"  {name:<26} {n:>3} 条  {n/len(verdicts):>5.0%}")
    if not rule_fail:
        print("  （一条都没有 —— 要么轨迹太干净，要么规则太松，得先证伪）")

    print("\n最差 5 条：")
    for v in sorted(verdicts, key=lambda v: v.score)[:5]:
        print(f"  {v.case_id:<26} score={v.score:.3f} {'PASS' if v.passed else 'FAIL'}"
              f"{'  [硬否决: ' + ','.join(v.vetoed) + ']' if v.vetoed else ''}")
        for d in v.details:
            if d.score == 0.0:
                print(f"      - {d.name}: {d.note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
