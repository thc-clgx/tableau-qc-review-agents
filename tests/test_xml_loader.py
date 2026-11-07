"""Security and correctness tests for the XML loader."""

from __future__ import annotations

import pytest

from tableau_qc.xmlio.loader import (
    DEFAULT_MAX_DEPTH,
    XMLLoadError,
    XMLSecurityError,
    load_xml_bytes,
    load_xml_file,
)


def test_loads_valid_workbook(sample_xml_path):
    document = load_xml_file(sample_xml_path)
    assert document.root.tag == "workbook"
    assert document.root.get("version") == "18.1"
    assert document.byte_size > 0
    assert len(document.sha256) == 64


def test_sha256_is_stable(sample_xml_path):
    assert load_xml_file(sample_xml_path).sha256 == load_xml_file(sample_xml_path).sha256


def test_xpath_is_index_qualified(sample_document):
    zone = sample_document.root.find("dashboards/dashboard/zones/zone")
    assert sample_document.xpath_of(zone) == "/workbook/dashboards[1]/dashboard[1]/zones[1]/zone[1]"


def test_parent_lookup(sample_document):
    dashboards = sample_document.root.find("dashboards")
    dashboard = dashboards.find("dashboard")
    assert sample_document.parent_of(dashboard) is dashboards


def test_xxe_is_blocked(security_fixtures_dir):
    with pytest.raises(XMLSecurityError):
        load_xml_file(security_fixtures_dir / "xxe.xml")


def test_billion_laughs_is_blocked(security_fixtures_dir):
    with pytest.raises(XMLSecurityError):
        load_xml_file(security_fixtures_dir / "billion_laughs.xml")


def test_external_dtd_is_blocked(security_fixtures_dir):
    with pytest.raises(XMLSecurityError):
        load_xml_file(security_fixtures_dir / "external_dtd.xml")


def test_doctype_detected_after_whitespace():
    payload = b"\n\n   <!DOCTYPE workbook><workbook/>"
    with pytest.raises(XMLSecurityError):
        load_xml_bytes(payload)


def test_malformed_xml_raises_load_error(security_fixtures_dir):
    with pytest.raises(XMLLoadError):
        load_xml_file(security_fixtures_dir / "malformed.xml")


def test_empty_input_raises():
    with pytest.raises(XMLLoadError):
        load_xml_bytes(b"")


def test_missing_file_raises(tmp_path):
    with pytest.raises(XMLLoadError):
        load_xml_file(tmp_path / "absent.xml")


def test_size_limit_enforced():
    with pytest.raises(XMLSecurityError):
        load_xml_bytes(b"<workbook/>", max_bytes=5)


def test_file_size_limit_enforced(sample_xml_path):
    with pytest.raises(XMLSecurityError):
        load_xml_file(sample_xml_path, max_bytes=10)


def test_depth_limit_enforced():
    depth = DEFAULT_MAX_DEPTH + 10
    payload = b"<a>" * depth + b"x" + b"</a>" * depth
    with pytest.raises(XMLSecurityError):
        load_xml_bytes(payload)


def test_nested_depth_within_limit_is_accepted():
    payload = b"<a>" * 10 + b"x" + b"</a>" * 10
    document = load_xml_bytes(payload)
    assert document.root.tag == "a"


def test_cdata_content_does_not_inflate_depth():
    """Tableau stores SQL inside CDATA; '<' there is not an element start."""
    sql = b"<![CDATA[" + b"SELECT * FROM t WHERE a < 1 AND b <> 2 " * 200 + b"]]>"
    payload = b"<workbook><datasources>" + sql + b"</datasources></workbook>"
    document = load_xml_bytes(payload)
    assert document.root.tag == "workbook"


def test_comments_do_not_inflate_depth():
    payload = b"<workbook><!-- <a><b><c> note --><dashboards /></workbook>"
    assert load_xml_bytes(payload).root.tag == "workbook"


def test_angle_brackets_in_attributes_are_ignored():
    payload = (
        b"<workbook><calculation formula='IF [a] &gt; 1 THEN \"&lt;x&gt;\" END' />"
        b"</workbook>"
    )
    assert load_xml_bytes(payload).root.tag == "workbook"


def test_real_world_workbook_with_cdata_loads(new_workbook_xml_path):
    document = load_xml_file(new_workbook_xml_path)
    assert document.root.tag == "workbook"
    assert document.depth < DEFAULT_MAX_DEPTH


def test_non_bytes_input_rejected():
    with pytest.raises(TypeError):
        load_xml_bytes("<workbook/>")  # type: ignore[arg-type]
