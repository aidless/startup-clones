from georadar import cli, store
from georadar.extract import find_mentions
from georadar.models import Run
from georadar.providers import MockProvider

BRANDS = ["Acme", "Traversal"]


def test_sqlite_roundtrip(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    prov = MockProvider(BRANDS, seed=2)
    run = Run(run_id="r1", brand="Acme", category="AI SRE",
              competitors=["Traversal"], provider="mock", created_at="2026-11-12T00:00:00Z")
    ms = []
    for i in range(4):
        a = prov.complete(f"q{i}", run_index=0)
        a.prompt_id = f"p{i}"
        run.answers.append(a)
        ms.extend(find_mentions(a, BRANDS))
    store.save_run(conn, run, ms)
    loaded, loaded_ms = store.load_run(conn, "r1")
    assert loaded.brand == "Acme"
    assert len(loaded.answers) == 4
    assert len(loaded_ms) == len(ms)


def test_cli_run_and_report(tmp_path, capsys):
    db = tmp_path / "x.db"
    out = tmp_path / "r.md"
    rc = cli.main(["run", "--brand", "Acme", "--category", "AI SRE",
                   "--competitors", "Traversal,Rootly", "--provider", "mock",
                   "--repeat", "2", "--limit", "8", "--db", str(db), "--out", str(out)])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "AI 可见性周报" in text
    assert "声量份额" in text
