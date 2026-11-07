"""Unit tests for the shared parser helpers."""

from __future__ import annotations

import pytest

from tableau_qc.parsers.base import BaseParser
from tableau_qc.xmlio.loader import load_xml_bytes

XML = b"""<workbook xml:base='http://example.com' version='18.1'>
  <dashboard count='7' ratio='1.5' flag='true' off='no' bad='abc' name='D'>
    <title>  Sales   by Region  </title>
  </dashboard>
</workbook>"""


@pytest.fixture()
def parser_and_root():
    document = load_xml_bytes(XML)
    return BaseParser(document), document.root


def test_attr_and_default(parser_and_root):
    parser, root = parser_and_root
    dashboard = root.find("dashboard")
    assert parser.attr(dashboard, "name") == "D"
    assert parser.attr(dashboard, "absent") is None
    assert parser.attr(dashboard, "absent", "fallback") == "fallback"


def test_int_attr(parser_and_root):
    parser, root = parser_and_root
    dashboard = root.find("dashboard")
    assert parser.int_attr(dashboard, "count") == 7
    assert parser.int_attr(dashboard, "ratio") == 1       # truncates via float
    assert parser.int_attr(dashboard, "bad") is None      # never raises
    assert parser.int_attr(dashboard, "absent") is None


def test_float_attr(parser_and_root):
    parser, root = parser_and_root
    dashboard = root.find("dashboard")
    assert parser.float_attr(dashboard, "ratio") == 1.5
    assert parser.float_attr(dashboard, "bad") is None


@pytest.mark.parametrize(
    "attribute,expected",
    [("flag", True), ("off", False), ("bad", None), ("absent", None)],
)
def test_bool_attr(parser_and_root, attribute, expected):
    parser, root = parser_and_root
    assert parser.bool_attr(root.find("dashboard"), attribute) is expected


def test_bool_attr_accepts_tableau_spellings():
    document = load_xml_bytes(b"<e a='yes' b='1' c='TRUE' d='no' e='0' />")
    parser = BaseParser(document)
    root = document.root
    assert [parser.bool_attr(root, k) for k in "abc"] == [True, True, True]
    assert [parser.bool_attr(root, k) for k in "de"] == [False, False]


def test_xml_base_is_namespace_aware(parser_and_root):
    parser, root = parser_and_root
    assert parser.xml_base(root) == "http://example.com"
    assert parser.xml_base(root.find("dashboard")) is None


def test_text_of_collapses_whitespace(parser_and_root):
    parser, root = parser_and_root
    assert parser.text_of(root.find("dashboard/title")) == "Sales   by Region"
    assert parser.text_of(None) is None


def test_text_of_empty_element_is_none():
    document = load_xml_bytes(b"<e><child>   </child></e>")
    parser = BaseParser(document)
    assert parser.text_of(document.root.find("child")) is None


def test_attrib_dict_filters_keys(parser_and_root):
    parser, root = parser_and_root
    dashboard = root.find("dashboard")
    assert parser.attrib_dict(dashboard, ["name", "count"]) == {"name": "D", "count": "7"}
    assert "absent" not in parser.attrib_dict(dashboard, ["absent"])
    assert parser.attrib_dict(dashboard)["ratio"] == "1.5"


def test_ref_builds_evidence_pointer(parser_and_root):
    parser, root = parser_and_root
    ref = parser.ref(root.find("dashboard"), "name")
    assert ref.xpath == "/workbook/dashboard[1]"
    assert ref.attribute == "name"
    assert str(ref) == "/workbook/dashboard[1]@name"
