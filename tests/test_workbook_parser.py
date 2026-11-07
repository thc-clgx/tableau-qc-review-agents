"""Unit tests for the workbook parser and normalisation step."""

from __future__ import annotations

import pytest

from conftest import parse_fixture
from tableau_qc.parsers.workbook_parser import WorkbookParseError, WorkbookParser, parse_workbook_bytes
from tableau_qc.xmlio.loader import load_xml_file


def test_workbook_metadata(sample_workbook):
    assert sample_workbook.name == "TestAIBIDashboards"
    assert sample_workbook.version == "18.1"
    assert sample_workbook.original_version == "18.1"
    assert sample_workbook.source_platform == "win"
    assert sample_workbook.repository_location["site"] == "cotalityanalytics"
    assert sample_workbook.preferences["ui.shelf.height"] == "26"


def test_source_provenance_is_recorded(sample_workbook, sample_xml_path):
    assert sample_workbook.source_path.endswith("sample_workbook.xml")
    assert len(sample_workbook.source_sha256) == 64
    assert sample_workbook.source.xpath == "/workbook"


def test_counts(sample_workbook):
    counts = sample_workbook.as_dict()["counts"]
    assert counts["dashboards"] == 1
    assert counts["worksheets"] == 10
    assert counts["datasources"] == 2
    assert counts["actions"] == 2


def test_datasources_and_calculated_fields(sample_workbook):
    names = [ds.name for ds in sample_workbook.datasources]
    assert "Sample - Superstore" in names
    assert "Parameters" in names

    calculations = {c.caption: c.formula for c in sample_workbook.calculated_fields}
    assert calculations["Profit Ratio"] == "SUM([Profit])/SUM([Sales])"

    parameters = [c for c in sample_workbook.calculated_fields if c.is_parameter]
    assert any(c.caption == "Top Customers" for c in parameters)


def test_actions_are_parsed(sample_workbook):
    captions = {a.caption: a.action_type for a in sample_workbook.actions}
    assert captions == {"SALES BU": "PARAMETER", "Profit BU": "PARAMETER"}


def test_worksheet_visibility_from_windows(sample_workbook):
    donut = sample_workbook.worksheet_by_name("DONUT")
    hidden = sample_workbook.worksheet_by_name("PROFIT")
    assert donut.is_visible is True
    assert hidden.is_visible is False
    assert sample_workbook.hidden_worksheet_count == 9


def test_normalisation_links_worksheets_to_dashboards(sample_workbook):
    sheet = sample_workbook.worksheet_by_name("sales by category")
    assert sheet.used_in_dashboards == ["Interactive Dashboard"]
    assert sample_workbook.worksheet_by_name("DONUT").used_in_dashboards == []


def test_style_aggregation_includes_zone_formats(sample_workbook):
    attrs = sample_workbook.style.declared_attrs
    assert "margin" in attrs
    assert "border-style" in attrs
    assert "#000000" in sample_workbook.style.colors


def test_compliant_fixture_fonts(compliant_xml_path):
    workbook = parse_fixture(compliant_xml_path)
    assert workbook.style.font_families == ["Arial", "Arial Black"]


def test_non_workbook_root_raises(security_fixtures_dir):
    document = load_xml_file(security_fixtures_dir / "not_a_workbook.xml")
    with pytest.raises(WorkbookParseError):
        WorkbookParser(document).parse()


def test_parse_workbook_bytes_roundtrip(compliant_xml_path):
    workbook = parse_workbook_bytes(compliant_xml_path.read_bytes(), source_path="memory.xml")
    assert workbook.dashboard_count == 1
    assert workbook.source_path == "memory.xml"


def test_missing_sections_do_not_crash():
    workbook = parse_workbook_bytes(b"<workbook version='18.1' />")
    assert workbook.dashboards == []
    assert workbook.worksheets == []
    assert workbook.datasources == []
    assert workbook.style.font_families == []
