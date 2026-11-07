"""Every shipped rule must have a passing and a failing fixture."""

from __future__ import annotations

import pytest

from conftest import parse_fixture
from tableau_qc.domain.findings import Status, aggregate_status
from tableau_qc.rules.engine import RuleEngine

RULE_IDS = [
    "CTL-LAYOUT-001",
    "CTL-LAYOUT-002",
    "CTL-LAYOUT-003",
    "CTL-LAYOUT-004",
    "CTL-TYPO-001",
    "CTL-TYPO-002",
    "CTL-COLOR-001",
    "CTL-COLOR-002",
    "CTL-COLOR-003",
    "CTL-PERF-001",
    "CTL-PERF-002",
    "CTL-PERF-003",
    "CTL-PERF-004",
    "CTL-HYG-001",
    "CTL-HYG-002",
    "CTL-STRUCT-001",
    "CTL-STRUCT-002",
    "CTL-STRUCT-003",
    "CTL-STRUCT-004",
    "CTL-CONTENT-001",
    "CTL-CONTENT-002",
    "CTL-CONTENT-003",
    "CTL-CONTENT-004",
    "CTL-CHART-001",
    "CTL-CHART-002",
    "CTL-CONTENT-005",
    "CTL-TYPO-003",
]

#: Rules whose violation is a heuristic or opinion rather than hard evidence.
ADVISORY_RULE_IDS = {
    "CTL-COLOR-003",
    "CTL-PERF-003",
    "CTL-STRUCT-003",
    "CTL-STRUCT-004",
    "CTL-CONTENT-002",
    "CTL-CONTENT-004",
    "CTL-CONTENT-005",
    "CTL-CHART-001",
    "CTL-CHART-002",
    "CTL-TYPO-003",
}


def _status_for(repository, rule_id, path) -> Status:
    rule = repository.by_id(rule_id)
    assert rule is not None, f"rule {rule_id} is missing from the repository"
    findings = RuleEngine(repository.filtered(rule_ids=[rule_id])).execute(parse_fixture(path))
    assert findings, f"{rule_id} produced no findings for {path.name}"
    return aggregate_status([f.status for f in findings])


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_passing_fixture_passes(rule_id, repository, rule_fixtures_dir):
    path = rule_fixtures_dir / f"{rule_id}_pass.xml"
    assert path.is_file(), f"missing passing fixture for {rule_id}"
    assert _status_for(repository, rule_id, path) is Status.PASS


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_failing_fixture_fails(rule_id, repository, rule_fixtures_dir):
    path = rule_fixtures_dir / f"{rule_id}_fail.xml"
    assert path.is_file(), f"missing failing fixture for {rule_id}"
    expected = Status.ADVISORY if rule_id in ADVISORY_RULE_IDS else Status.FAIL
    assert _status_for(repository, rule_id, path) is expected


def test_every_rule_has_both_fixtures(repository, rule_fixtures_dir):
    """No rule may ship without a passing and a failing fixture."""
    for rule in repository:
        for kind in ("pass", "fail"):
            path = rule_fixtures_dir / f"{rule.id}_{kind}.xml"
            assert path.is_file(), f"{rule.id} is missing its {kind} fixture"


def test_advisory_rules_never_report_fail(repository, rule_fixtures_dir):
    """Heuristic rules must stay ADVISORY so they are not read as evidence."""
    for rule_id in sorted(ADVISORY_RULE_IDS):
        rule = repository.by_id(rule_id)
        if rule is None:
            continue
        assert rule.on_violation is Status.ADVISORY, f"{rule_id} should be advisory"


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_failing_fixture_produces_actionable_evidence(rule_id, repository, rule_fixtures_dir):
    workbook = parse_fixture(rule_fixtures_dir / f"{rule_id}_fail.xml")
    findings = RuleEngine(repository.filtered(rule_ids=[rule_id])).execute(workbook)
    failed = [f for f in findings if f.status in (Status.FAIL, Status.ADVISORY)]
    assert failed
    for finding in failed:
        assertion_evidence = [e for e in finding.evidence if e.note != "context"]
        assert assertion_evidence
        assert all(e.source is not None and e.source.xpath for e in assertion_evidence)
        assert finding.recommendation
        assert finding.standard_ref


def test_checklist_refs_point_at_real_questions(repository, checklist_definition):
    """A rule must never cite a checklist cell that does not exist."""
    from tableau_qc.rules.validation import validate_checklist_references

    cells = [f"{item.sheet}!{item.cell}" for item in checklist_definition.items]
    assert validate_checklist_references(repository, cells) == []


def test_unmapped_rules_are_known_and_intentional(repository, checklist_definition):
    """Rules with no checklist row are still enforced; keep the list explicit."""
    from tableau_qc.rules.validation import unmapped_rule_ids

    mapped = {rid for item in checklist_definition.items for rid in item.rule_ids}
    # The redesigned checklist has no dashboard-size question, so the two size
    # rules are enforced via QC Findings only.
    assert unmapped_rule_ids(repository, mapped) == ["CTL-LAYOUT-001", "CTL-LAYOUT-002"]


def test_checklist_never_references_an_unknown_rule(repository, checklist_definition):
    for item in checklist_definition.items:
        for rule_id in item.rule_ids:
            assert repository.by_id(rule_id) is not None, (
                f"{item.item_id} references unknown rule {rule_id}"
            )


def test_padding_manual_fixture_is_manual_review(repository, rule_fixtures_dir):
    status = _status_for(repository, "CTL-LAYOUT-004", rule_fixtures_dir / "CTL-LAYOUT-004_manual.xml")
    assert status is Status.MANUAL_REVIEW


def test_padding_partial_fixture_fails_on_inner_padding_only(repository, rule_fixtures_dir):
    workbook = parse_fixture(rule_fixtures_dir / "CTL-LAYOUT-004_partial.xml")
    finding = RuleEngine(repository.filtered(rule_ids=["CTL-LAYOUT-004"])).execute(workbook)[0]
    assert finding.status is Status.FAIL
    failed_fields = {
        e.field_path
        for e in finding.evidence
        if e.note != "context" and e.observed is not None and e.observed < 10
    }
    assert failed_fields == {"inner_padding.minimum"}


def test_font_manual_fixture_is_manual_review(repository, rule_fixtures_dir):
    status = _status_for(repository, "CTL-TYPO-001", rule_fixtures_dir / "CTL-TYPO-001_manual.xml")
    assert status is Status.MANUAL_REVIEW


def test_sample_workbook_reproduces_known_defects(repository, sample_xml_path):
    workbook = parse_fixture(sample_xml_path)
    findings = RuleEngine(repository).execute(workbook)
    by_rule = {}
    for finding in findings:
        by_rule.setdefault(finding.rule_id, []).append(finding.status)

    assert aggregate_status(by_rule["CTL-LAYOUT-001"]) is Status.FAIL  # 1000 px wide
    assert aggregate_status(by_rule["CTL-LAYOUT-002"]) is Status.FAIL  # 800 px high
    assert aggregate_status(by_rule["CTL-LAYOUT-003"]) is Status.FAIL  # 9 views
    assert aggregate_status(by_rule["CTL-LAYOUT-004"]) is Status.FAIL  # 4 px padding
    # <run fontname='Tableau Medium'> is now harvested, so this is evidenced.
    assert aggregate_status(by_rule["CTL-TYPO-001"]) is Status.FAIL  # Tableau Medium
