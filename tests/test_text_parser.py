"""Unit tests for the readable-text parser and its spelling/naming helpers."""

from __future__ import annotations

import pytest

from conftest import parse_fixture
from tableau_qc.parsers.text_parser import (
    TextParser,
    contains_raw_calculation,
    find_misspellings,
    visible_words,
)
from tableau_qc.xmlio.loader import load_xml_bytes


def _parse(xml: bytes):
    document = load_xml_bytes(xml)
    return TextParser(document).parse(
        document.root, owner_type="worksheet", owner_id="Sheet 1"
    )


def test_title_text_and_category():
    xml = b"""<workbook><worksheet name='S1'><layout-options><title>
      <formatted-text><run fontname='Arial' fontsize='15'>Sales by Region</run></formatted-text>
    </title></layout-options></worksheet></workbook>"""
    texts = _parse(xml)
    assert len(texts) == 1
    assert texts[0].text == "Sales by Region"
    assert texts[0].category == "worksheet-title"
    assert texts[0].owner_id == "Sheet 1"


def test_tooltip_and_label_categories():
    xml = b"""<workbook><pane>
      <customized-tooltip><formatted-text><run>Total Sales</run></formatted-text></customized-tooltip>
      <customized-label><formatted-text><run>Label text</run></formatted-text></customized-label>
    </pane></workbook>"""
    categories = {t.category: t.text for t in _parse(xml)}
    assert categories == {"tooltip": "Total Sales", "label": "Label text"}


def test_dashboard_text_object_category():
    xml = b"""<workbook><zones><zone id='1' type-v2='text'>
      <formatted-text><run>Select a bar to filter</run></formatted-text>
    </zone></zones></workbook>"""
    texts = _parse(xml)
    assert texts[0].category == "dashboard-text"


def test_runs_are_concatenated():
    xml = b"""<workbook><pane><customized-tooltip><formatted-text>
      <run>Total: </run><run>1,234</run>
    </formatted-text></customized-tooltip></pane></workbook>"""
    assert _parse(xml)[0].text == "Total: 1,234"


def test_empty_text_blocks_are_skipped():
    xml = b"""<workbook><pane><customized-tooltip><formatted-text>
      <run>   </run>
    </formatted-text></customized-tooltip></pane></workbook>"""
    assert _parse(xml) == []


def test_text_carries_a_source_reference():
    xml = b"""<workbook><pane><customized-tooltip><formatted-text>
      <run>Total</run></formatted-text></customized-tooltip></pane></workbook>"""
    assert _parse(xml)[0].source.xpath.endswith("formatted-text[1]")


# -- visible_words ---------------------------------------------------------
def test_field_references_are_stripped():
    assert visible_words("Total Sales: <[sum:Sales:qk]>") == ["Total", "Sales"]


def test_raw_calculation_ids_are_stripped():
    assert visible_words("Value <[Calculation_2211830417016991744]>") == ["Value"]


def test_numbers_and_punctuation_are_ignored():
    assert visible_words("Q1 2026 -- 45.6%") == []


# -- raw calculation detection --------------------------------------------
def test_raw_calculation_detection():
    assert contains_raw_calculation("x <[Calculation_2211830417016991744]>") is True
    assert contains_raw_calculation("Total Sales") is False
    # A short numeric suffix is a legitimate name, not a generated id.
    assert contains_raw_calculation("Calculation_12") is False


# -- spelling --------------------------------------------------------------
def test_known_misspellings_are_reported_with_corrections():
    found = find_misspellings("Total Models by Surveilance Type and Model actipn plan")
    assert "Surveilance -> surveillance" in found
    assert "actipn -> action" in found


def test_spelling_is_case_insensitive_but_preserves_the_original():
    assert find_misspellings("Survellance") == ["Survellance -> surveillance"]


def test_correct_spelling_is_not_flagged():
    assert find_misspellings("Total Models by Surveillance Type") == []


def test_business_vocabulary_is_never_false_flagged():
    """A curated list is used precisely so jargon is not reported."""
    text = "amp'd Cotality KPI QoQ BigQuery Hyper EDGOpsStg logomark"
    assert find_misspellings(text) == []


def test_duplicate_misspellings_are_reported_once():
    assert find_misspellings("Surveilance Surveilance Surveilance") == [
        "Surveilance -> surveillance"
    ]


def test_results_are_sorted_for_determinism():
    """Ordering is by the misspelled word, so repeated runs match exactly."""
    first = find_misspellings("Surveilance actipn implemnt")
    second = find_misspellings("implemnt Surveilance actipn")
    assert first == second
    assert first == [
        "actipn -> action",
        "implemnt -> implement",
        "Surveilance -> surveillance",
    ]


# -- against the real workbook --------------------------------------------
def test_real_workbook_text_extraction(new_workbook_xml_path):
    workbook = parse_fixture(new_workbook_xml_path)
    assert len(workbook.texts) > 100
    assert workbook.raw_calculation_text_count > 0
    assert workbook.misspelled_words == [
        "actipn -> action",
        "Deail -> detail",
        "implemnt -> implement",
        "Surveilance -> surveillance",
        "Survellance -> surveillance",
    ]
