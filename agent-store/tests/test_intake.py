"""入市审查的三类断言：推断对不对、判定准不准、干净清单必须放行。"""

from agentstore.intake import audit, from_manifest, infer_permissions, review


def facts(**kw):
    base = {"repo": "acme/tool", "package_json": {"name": "acme-tool", "version": "1.2.3",
                                                  "description": "Reads local files"},
            "readme": "A tool that reads files from disk."}
    base.update(kw)
    return from_manifest(base)


def rules(findings):
    return [f.rule for f in findings]


def test_env_var_is_hard_evidence_for_secrets():
    f = facts(package_json={"name": "x", "version": "1.0.0",
                            "description": "search", "dependencies": {"@acme/sdk": "^1"}},
              readme="Set ACME_API_TOKEN before running. It calls the ACME API over https.")
    need = infer_permissions(f)
    assert "secrets.read" in need
    assert any("ACME_API_TOKEN" in e for e in need["secrets.read"])
    assert "net.outbound" in need


def test_read_only_tool_does_not_ask_for_payment():
    """回归：把 "charge"/"invoice" 当付款证据会产生假阳性。"""
    f = facts(readme="The agent will charge through its plan and print an invoice summary.")
    assert "payment.charge" not in infer_permissions(f)


def test_missing_declaration_is_medium_structural():
    """「不声明」在真实生态里是普遍状态（16/16），定 high 会让审查失去区分度。"""
    f = facts(readme="Reads files and writes reports to disk using WRITE_TOKEN.")
    got = audit(f)
    assert "no_permission_declaration" in rules(got)
    assert [x.severity for x in got if x.rule == "no_permission_declaration"] == ["medium"]
    assert "undeclared_sensitive_permission" in rules(got)


def test_hard_evidence_upgrades_sensitive_permission_to_high():
    """README 里出现具体环境变量名 = 硬证据，upgrade 到 high。"""
    f = facts(readme="Export ACME_API_KEY before use. Reads files.")
    got = [x for x in audit(f) if x.rule == "undeclared_sensitive_permission"]
    assert [x.severity for x in got] == ["high"]
    assert "硬证据" in got[0].detail


def test_soft_keyword_only_stays_medium():
    f = facts(readme="Handles bearer token rotation descriptions for documentation purposes.")
    got = [x for x in audit(f) if x.rule == "undeclared_sensitive_permission"]
    assert [x.severity for x in got] == ["medium"]
    assert "仅关键词推断" in got[0].detail


def test_word_boundaries_kill_substring_false_positives():
    """回归：substring 匹配把 credits→edit、capital→api、checkout→收款 全判成权限。"""
    f = facts(readme="Adds credits to your balance. Covers capital markets data. "
                     "CI uses actions/checkout step.")
    need = infer_permissions(f)
    assert "fs.write" not in need
    assert "net.outbound" not in need
    assert "payment.charge" not in need


def test_over_requested_permission_flagged():
    f = facts(package_json={"name": "x", "version": "1.0.0",
                            "description": "Searches the web",
                            "permissions": ["net.outbound", "payment.charge"]},
              readme="It searches the web over https.")
    got = audit(f)
    assert "over_requested_permission" in rules(got)
    detail = [x.detail for x in got if x.rule == "over_requested_permission"][0]
    assert "payment.charge" in detail


def test_unpinned_and_missing_docs():
    f = from_manifest({"repo": "acme/ghost", "package_json": {}, "readme": ""})
    assert {"unpinned_version", "no_documentation"} <= set(rules(audit(f)))
    assert "high" not in [x.severity for x in audit(f) if x.rule == "unpinned_version"]


def test_clean_listing_passes():
    """GREEN：声明齐全、版本固定、文档在，必须零发现。"""
    f = facts(package_json={"name": "acme-reader", "version": "2.0.0",
                            "description": "Reads local files",
                            "permissions": ["fs.read"]},
              readme="Reads files from a local directory and prints them. No network access.")
    got = audit(f)
    assert rules(got) == [], [x.detail for x in got]


def test_review_worst_severity_rollup():
    payload = {"repo": "acme/x", "package_json": {"name": "x", "version": "0.1.0",
                                                  "description": "calls api with API_KEY"},
               "readme": "Needs API_KEY."}
    r = review(payload)
    assert r["worst"] == "high"
    assert "secrets.read" in r["inferred"]
    assert r["declared"] == []
