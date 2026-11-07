"""Tests for the YAML-configured content standards."""

from __future__ import annotations

import pytest

from tableau_qc.standards import StandardsError, load_standards, standards

MINIMAL = """
version: "9.9.9"
metadata_elements:
  data_update_date:
    - updated on
interactivity_phrases:
  - tap
logo:
  upper_left_max_x: 500
  upper_left_max_y: 600
naming_defect_patterns:
  - "TEMP_"
raw_calculation_pattern: "Gen_\\\\d{4,}"
misspellings:
  Wrng: wrong
"""


def _write(tmp_path, body: str):
    path = tmp_path / "content.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_shipped_standards_load():
    loaded = standards()
    assert loaded.version == "1.0.0"
    assert set(loaded.required_metadata_elements) == {
        "data_update_date",
        "dashboard_contact",
        "data_owner",
    }
    assert loaded.misspellings["survellance"] == "surveillance"
    assert loaded.logo_max_x == 12500


def test_values_are_read_from_the_file_not_hard_coded(tmp_path):
    loaded = load_standards(_write(tmp_path, MINIMAL))
    assert loaded.version == "9.9.9"
    assert loaded.required_metadata_elements == ("data_update_date",)
    assert loaded.interactivity_phrases == ("tap",)
    assert loaded.logo_max_x == 500
    assert loaded.logo_max_y == 600
    assert loaded.misspellings == {"wrng": "wrong"}


def test_misspelling_keys_are_lower_cased(tmp_path):
    loaded = load_standards(_write(tmp_path, MINIMAL))
    assert "wrng" in loaded.misspellings
    assert "Wrng" not in loaded.misspellings


def test_naming_regex_is_compiled_from_patterns(tmp_path):
    loaded = load_standards(_write(tmp_path, MINIMAL))
    assert loaded.naming_defect_regex.search("TEMP_sales")
    assert not loaded.naming_defect_regex.search("Sales by Region")


def test_empty_naming_patterns_match_nothing(tmp_path):
    body = MINIMAL.replace('naming_defect_patterns:\n  - "TEMP_"', "naming_defect_patterns: []")
    loaded = load_standards(_write(tmp_path, body))
    assert not loaded.naming_defect_regex.search("anything at all")


def test_raw_calculation_regex_is_configurable(tmp_path):
    loaded = load_standards(_write(tmp_path, MINIMAL))
    assert loaded.raw_calculation_regex.search("Gen_12345")
    assert not loaded.raw_calculation_regex.search("Calculation_12345678")


def test_missing_file_raises(tmp_path):
    with pytest.raises(StandardsError, match="not found"):
        load_standards(tmp_path / "absent.yaml")


def test_invalid_yaml_raises(tmp_path):
    with pytest.raises(StandardsError, match="Invalid YAML"):
        load_standards(_write(tmp_path, "metadata_elements: [: :"))


def test_non_mapping_top_level_raises(tmp_path):
    with pytest.raises(StandardsError, match="must be a mapping"):
        load_standards(_write(tmp_path, "- just\n- a list\n"))


def test_bad_metadata_shape_raises(tmp_path):
    with pytest.raises(StandardsError, match="metadata_elements"):
        load_standards(_write(tmp_path, "metadata_elements: not-a-mapping\n"))


def test_bad_phrase_list_raises(tmp_path):
    with pytest.raises(StandardsError, match="list of strings"):
        load_standards(_write(tmp_path, "interactivity_phrases: 5\n"))


def test_invalid_naming_regex_raises(tmp_path):
    with pytest.raises(StandardsError, match="invalid naming pattern"):
        load_standards(_write(tmp_path, 'naming_defect_patterns:\n  - "[unclosed"\n'))


def test_invalid_raw_calculation_regex_raises(tmp_path):
    with pytest.raises(StandardsError, match="raw_calculation_pattern"):
        load_standards(_write(tmp_path, 'raw_calculation_pattern: "[unclosed"\n'))


def test_standards_drive_behaviour_end_to_end(tmp_path, monkeypatch, compliant_xml_path):
    """Changing the YAML changes the verdict - nothing is hard-coded."""
    import tableau_qc.standards as standards_module
    from conftest import parse_fixture

    workbook = parse_fixture(compliant_xml_path)
    assert workbook.misspelled_words == []

    # Declare a word the fixture actually uses as a misspelling, then re-check.
    assert "sheet" in workbook.searchable_text.lower()
    body = MINIMAL.replace("  Wrng: wrong", "  sheet: worksheet")
    monkeypatch.setattr(standards_module, "DEFAULT_STANDARDS_PATH", _write(tmp_path, body))
    standards_module.reset_cache()
    try:
        found = parse_fixture(compliant_xml_path).misspelled_words
        assert found == ["Sheet -> worksheet"]
    finally:
        standards_module.reset_cache()
