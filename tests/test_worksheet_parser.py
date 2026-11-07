"""Unit tests for the worksheet parser and visibility resolution."""

from __future__ import annotations

from tableau_qc.parsers.worksheet_parser import VisibilityParser, WorksheetParser
from tableau_qc.xmlio.loader import load_xml_bytes


def test_all_worksheets_are_parsed(sample_workbook):
    names = [w.name for w in sample_workbook.worksheets]
    assert "DONUT" in names
    assert len(names) == len(set(names)) == 10


def test_worksheet_datasource_dependencies(sample_workbook):
    sheet = sample_workbook.worksheet_by_name("sales by category")
    assert "Sample - Superstore" in sheet.datasource_dependencies


def test_worksheet_filters_are_parsed(sample_workbook):
    sheet = sample_workbook.worksheet_by_name("sales by sub category")
    assert sheet.filter_count >= 1
    first = sheet.filters[0]
    assert first.datasource == "Sample - Superstore"
    assert first.filter_class == "categorical"
    assert first.source.xpath.startswith("/workbook/worksheets[1]")


def test_mark_classes_are_collected(sample_workbook):
    sheet = sample_workbook.worksheet_by_name("sales by category")
    assert sheet.mark_classes
    assert all(isinstance(m, str) for m in sheet.mark_classes)


def test_worksheet_formats_are_scoped(sample_workbook):
    sheet = sample_workbook.worksheet_by_name("DONUT")
    assert all(f.owner_type == "worksheet" for f in sheet.formats)
    assert all(f.owner_id == "DONUT" for f in sheet.formats)


def test_visibility_parser_reads_hidden_windows(sample_document):
    hidden = VisibilityParser(sample_document).hidden_worksheet_names(sample_document.root)
    assert "PROFIT" in hidden
    assert "DONUT" not in hidden


def test_visibility_is_unknown_when_not_declared():
    xml = b"""<workbook version='18.1'>
      <worksheets><worksheet name='Orphan'><table /></worksheet></worksheets>
    </workbook>"""
    from tableau_qc.parsers.workbook_parser import WorkbookParser

    workbook = WorkbookParser(load_xml_bytes(xml)).parse()
    assert workbook.worksheet_by_name("Orphan").is_visible is None


def test_worksheet_title_detection():
    xml = b"""<workbook version='18.1'>
      <worksheets>
        <worksheet name='Titled'>
          <layout-options><title><formatted-text><run>Sales by region</run></formatted-text></title></layout-options>
          <table />
        </worksheet>
        <worksheet name='Untitled'><table /></worksheet>
      </worksheets>
    </workbook>"""
    document = load_xml_bytes(xml)
    sheets = {w.name: w for w in WorksheetParser(document).parse_all(document.root)}
    assert sheets["Titled"].has_title is True
    assert sheets["Untitled"].has_title is False


def test_filter_datasource_extraction_handles_unqualified_columns():
    assert WorksheetParser._datasource_of("[DS].[none:Category:nk]") == "DS"
    assert WorksheetParser._datasource_of("Category") is None
    assert WorksheetParser._datasource_of(None) is None
