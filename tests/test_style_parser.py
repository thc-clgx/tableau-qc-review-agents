"""Unit tests for the style/font/colour/padding parser."""

from __future__ import annotations

from tableau_qc.parsers.style_parser import StyleParser
from tableau_qc.xmlio.loader import load_xml_bytes


def _parser(xml: bytes):
    document = load_xml_bytes(xml)
    return StyleParser(document), document


def test_formats_capture_style_rule_element():
    parser, document = _parser(
        b"""<workbook>
            <style>
              <style-rule element='worksheet'>
                <format attr='font-family' value='Arial' />
                <format attr='font-size' value='11' />
              </style-rule>
            </style>
        </workbook>"""
    )
    formats = parser.parse_formats(
        document.root.find("style"), owner_type="workbook", owner_id="wb"
    )
    assert [f.attr for f in formats] == ["font-family", "font-size"]
    assert all(f.element == "worksheet" for f in formats)
    assert formats[0].owner_type == "workbook"
    assert formats[1].numeric_value == 11.0


def test_non_recursive_parse_ignores_nested_zones():
    parser, document = _parser(
        b"""<workbook>
            <zone-style>
              <format attr='margin' value='20' />
              <zone><zone-style><format attr='margin' value='2' /></zone-style></zone>
            </zone-style>
        </workbook>"""
    )
    formats = parser.parse_formats(
        document.root.find("zone-style"), owner_type="zone", owner_id="z", recursive=False
    )
    assert [f.value for f in formats] == ["20"]


def test_padding_shorthand_applies_to_all_sides():
    parser, document = _parser(
        b"<workbook><zone-style><format attr='margin' value='20' /></zone-style></workbook>"
    )
    formats = parser.parse_formats(
        document.root.find("zone-style"), owner_type="zone", owner_id="z", recursive=False
    )
    padding = parser.parse_padding(formats, "margin")
    assert padding.values == [20, 20, 20, 20]
    assert padding.minimum == 20
    assert padding.maximum == 20


def test_side_specific_padding_overrides_shorthand():
    parser, document = _parser(
        b"""<workbook><zone-style>
              <format attr='margin' value='20' />
              <format attr='margin-left' value='0' />
            </zone-style></workbook>"""
    )
    formats = parser.parse_formats(
        document.root.find("zone-style"), owner_type="zone", owner_id="z", recursive=False
    )
    padding = parser.parse_padding(formats, "margin")
    assert padding.left == 0
    assert padding.top == 20
    assert padding.minimum == 0


def test_undeclared_padding_is_not_defaulted():
    parser, document = _parser(
        b"<workbook><zone-style><format attr='border-width' value='0' /></zone-style></workbook>"
    )
    formats = parser.parse_formats(
        document.root.find("zone-style"), owner_type="zone", owner_id="z", recursive=False
    )
    padding = parser.parse_padding(formats, "padding")
    assert padding.is_declared is False
    assert padding.minimum is None
    assert padding.declared_sides == []


def test_non_numeric_padding_is_ignored():
    parser, document = _parser(
        b"<workbook><zone-style><format attr='margin' value='auto' /></zone-style></workbook>"
    )
    formats = parser.parse_formats(
        document.root.find("zone-style"), owner_type="zone", owner_id="z", recursive=False
    )
    assert parser.parse_padding(formats, "margin").is_declared is False


def test_font_and_colour_helpers():
    parser, document = _parser(
        b"""<workbook><style><style-rule element='worksheet'>
              <format attr='font-family' value='Arial' />
              <format attr='background-color' value='#F7EFE2' />
              <format attr='border-width' value='0' />
            </style-rule></style></workbook>"""
    )
    formats = parser.parse_formats(
        document.root.find("style"), owner_type="workbook", owner_id="wb"
    )
    assert [f.attr for f in StyleParser.font_declarations(formats)] == ["font-family"]
    assert [f.attr for f in StyleParser.colour_declarations(formats)] == ["background-color"]


def test_format_source_points_at_value_attribute():
    parser, document = _parser(
        b"<workbook><style><format attr='font-family' value='Arial' /></style></workbook>"
    )
    formats = parser.parse_formats(
        document.root.find("style"), owner_type="workbook", owner_id="wb"
    )
    assert formats[0].source.attribute == "value"
    assert formats[0].source.xpath == "/workbook/style[1]/format[1]"


def test_parse_formats_handles_missing_element():
    parser, _ = _parser(b"<workbook />")
    assert parser.parse_formats(None, owner_type="workbook", owner_id=None) == []
