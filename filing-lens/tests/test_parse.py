from filinglens import edgar, fixtures


def parse():
    return edgar.parse(fixtures.FAKE_10K_HTML, doc="ACME")


def test_split_sections_finds_items():
    sections, _, _ = parse()
    items = [s.item for s in sections]
    assert items == ["1", "1a", "7", "8"]
    titles = {s.item: s.title for s in sections}
    assert titles["1a"] == "Risk Factors"


def test_chunks_have_locatable_refs():
    _, chunks, _ = parse()
    assert chunks
    for c in chunks:
        assert c.ref.startswith("ACME#Item ")
        assert "¶" in c.ref
    # 每个 ref 唯一
    assert len({c.ref for c in chunks}) == len(chunks)


def test_table_extracted():
    _, _, tables = parse()
    assert tables
    t = tables[-1]
    assert t.header[0].lower().startswith("year ended")
    assert any("Revenue" in row[0] for row in t.rows)
