"""Tests for the command line interface."""

from __future__ import annotations

import json

import pytest

from tableau_qc.cli import main


def test_rules_command_lists_rules(capsys, rules_dir):
    assert main(["rules", "--rules", str(rules_dir)]) == 0
    out = capsys.readouterr().out
    assert "rules from" in out
    assert "CTL-LAYOUT-003" in out


def test_pre_review_returns_nonzero_on_failure(capsys, tmp_path, sample_xml_path, rules_dir, checklist_path):
    code = main(
        [
            "pre-review",
            str(sample_xml_path),
            "--rules",
            str(rules_dir),
            "--checklist",
            str(checklist_path),
            "--output-dir",
            str(tmp_path),
            "--no-excel",
        ]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "Overall status : FAIL" in out
    assert (tmp_path / "sample_workbook_pre_review.json").is_file()


def test_pre_review_returns_zero_for_compliant_workbook(
    capsys, tmp_path, compliant_xml_path, rules_dir, checklist_path
):
    code = main(
        [
            "pre-review",
            str(compliant_xml_path),
            "--rules",
            str(rules_dir),
            "--checklist",
            str(checklist_path),
            "--output-dir",
            str(tmp_path),
            "--basename",
            "compliant",
        ]
    )
    assert code == 0
    assert "Overall status : PASS" in capsys.readouterr().out
    assert (tmp_path / "compliant_pre_review.xlsx").is_file()


def test_pre_review_rule_filter(capsys, tmp_path, sample_xml_path, rules_dir, checklist_path):
    main(
        [
            "pre-review",
            str(sample_xml_path),
            "--rules",
            str(rules_dir),
            "--checklist",
            str(checklist_path),
            "--output-dir",
            str(tmp_path),
            "--no-excel",
            "--rule-id",
            "CTL-LAYOUT-003",
        ]
    )
    data = json.loads((tmp_path / "sample_workbook_pre_review.json").read_text("utf-8"))
    assert {f["rule_id"] for f in data["findings"]} == {"CTL-LAYOUT-003"}


def test_post_review_reports_resolution(capsys, tmp_path, rule_fixtures_dir, rules_dir, checklist_path):
    code = main(
        [
            "post-review",
            str(rule_fixtures_dir / "CTL-LAYOUT-003_pass.xml"),
            "--baseline-xml",
            str(rule_fixtures_dir / "CTL-LAYOUT-003_fail.xml"),
            "--rules",
            str(rules_dir),
            "--checklist",
            str(checklist_path),
            "--output-dir",
            str(tmp_path),
            "--no-excel",
            "--rule-id",
            "CTL-LAYOUT-003",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "RESOLVED" in out
    assert "Sign-off ready : YES" in out


def test_post_review_requires_baseline(capsys, tmp_path, rule_fixtures_dir, rules_dir):
    code = main(
        [
            "post-review",
            str(rule_fixtures_dir / "CTL-LAYOUT-003_pass.xml"),
            "--rules",
            str(rules_dir),
            "--output-dir",
            str(tmp_path),
        ]
    )
    assert code == 2
    assert "error:" in capsys.readouterr().err


def test_unknown_command_exits(capsys):
    with pytest.raises(SystemExit):
        main(["not-a-command"])
