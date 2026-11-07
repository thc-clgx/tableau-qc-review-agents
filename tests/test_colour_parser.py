"""Unit tests for the colour / mark-palette parser."""

from __future__ import annotations

import pytest

from conftest import parse_fixture
from tableau_qc.parsers.colour_parser import ColourParser, classify_hue
from tableau_qc.xmlio.loader import load_xml_bytes


def _parse(xml: bytes, *, owner="Sheet 1"):
    document = load_xml_bytes(xml)
    return ColourParser(document).parse_scope(
        document.root, owner_type="worksheet", owner_id=owner
    )


ENCODING = b"""<workbook>
  <datasource name='ds'>
    <style><style-rule element='mark'>
      <encoding attr='color' field='[Category]' palette='%s' type='palette'>
        %s
      </encoding>
    </style-rule></style>
  </datasource>
</workbook>"""


def _maps(*colours: str) -> bytes:
    return b"".join(
        f"<map to='{c}'><bucket>&quot;{i}&quot;</bucket></map>".encode()
        for i, c in enumerate(colours)
    )


def test_palette_name_and_colours_are_parsed():
    palettes = _parse(ENCODING % (b"Cotality-Extended", _maps("#FFCD2E", "#FF8E65")))
    assert len(palettes) == 1
    palette = palettes[0]
    assert palette.palette_name == "Cotality-Extended"
    assert palette.field_name == "[Category]"
    assert palette.colour_values == ["#ff8e65", "#ffcd2e"]
    assert palette.distinct_colour_count == 2


def test_colour_source_points_at_the_map_attribute():
    palette = _parse(ENCODING % (b"Cotality-Extended", _maps("#FFCD2E")))[0]
    assert palette.colours[0].source.attribute == "to"
    assert "map" in palette.colours[0].source.xpath


def test_non_colour_encodings_are_ignored():
    xml = b"""<workbook><datasource name='ds'><style><style-rule element='mark'>
      <encoding attr='size' field='[Sales]' palette='x' type='palette' />
    </style-rule></style></datasource></workbook>"""
    assert _parse(xml) == []


def test_encoding_without_palette_or_colours_is_skipped():
    xml = b"""<workbook><datasource name='ds'><style><style-rule element='mark'>
      <encoding attr='color' field='[Category]' type='quantitative' />
    </style-rule></style></datasource></workbook>"""
    assert _parse(xml) == []


def test_non_hex_colours_are_ignored():
    xml = ENCODING % (b"Cotality-Extended", b"<map to='red'/><map to='#FFCD2E'/>")
    assert _parse(xml)[0].colour_values == ["#ffcd2e"]


# -- hue classification ----------------------------------------------------
@pytest.mark.parametrize(
    "colour,family",
    [
        ("#d62728", "red"),
        ("#f1384f", "red"),
        ("#2ca02c", "green"),
        ("#339b62", "green"),
        ("#077982", None),   # teal
        ("#ffcd2e", None),   # yellow
        ("#a805fb", None),   # violet
        ("#bab0ac", None),   # grey - too desaturated
        ("#1e1405", None),   # near black - too dark
        ("#ffffff", None),   # white - too light
        ("not-a-colour", None),
    ],
)
def test_hue_classification(colour, family):
    assert classify_hue(colour) is family


def test_red_and_green_combination_detected():
    palette = _parse(ENCODING % (b"Cotality-Extended", _maps("#D62728", "#2CA02C")))[0]
    assert palette.hue_families == ["green", "red"]
    assert palette.combines_red_and_green is True


def test_brand_only_palette_has_no_conflict():
    palette = _parse(ENCODING % (b"Cotality-Extended", _maps("#FFCD2E", "#FF8E65")))[0]
    assert palette.combines_red_and_green is False


# -- built-in palette detection -------------------------------------------
@pytest.mark.parametrize(
    "name,built_in",
    [
        ("tableau20_10_0", True),
        ("Tableau 10", True),
        ("Classic Blue", True),
        ("Cotality-Extended", False),
        ("CotalitySecondary", False),
        (None, False),
    ],
)
def test_built_in_palette_detection(name, built_in):
    assert ColourParser.is_built_in_palette(name) is built_in


def test_custom_palettes_are_listed():
    xml = b"""<workbook><preferences>
      <color-palette name='Cotality-Extended' type='regular' />
      <color-palette name='CotalitySecondary' type='regular' />
    </preferences></workbook>"""
    document = load_xml_bytes(xml)
    parser = ColourParser(document)
    assert parser.parse_custom_palettes(document.root) == [
        "Cotality-Extended",
        "CotalitySecondary",
    ]


# -- against the real workbook --------------------------------------------
def test_real_workbook_colour_extraction(new_workbook_xml_path):
    workbook = parse_fixture(new_workbook_xml_path)
    assert "tableau20_10_0" in workbook.built_in_palettes_used
    assert len(workbook.mark_colours) > 20
    assert workbook.worksheets_combining_red_and_green
    assert workbook.custom_palettes == ["Cotality-Extended", "CotalitySecondary"]
