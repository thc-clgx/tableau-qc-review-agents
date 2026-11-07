"""Unit tests for the dashboard action parser."""

from __future__ import annotations

import pytest

from tableau_qc.parsers.action_parser import ACTION_TAGS, ActionParser
from tableau_qc.xmlio.loader import load_xml_bytes


def _parse(xml: bytes):
    document = load_xml_bytes(xml)
    return ActionParser(document).parse_all(document.root)


def test_filter_action_with_source_and_target():
    xml = b"""<workbook><actions>
      <filter-action caption='Drill to detail' name='[Action1]'>
        <source worksheet='Summary' />
        <target worksheet='Detail' />
        <link run-mode='on-select' />
      </filter-action>
    </actions></workbook>"""
    action = _parse(xml)[0]
    assert action.action_type == "FILTER"
    assert action.caption == "Drill to detail"
    assert action.name == "[Action1]"
    assert action.source_sheets == ["Summary"]
    assert action.target_sheets == ["Detail"]
    assert action.run_mode == "on-select"


@pytest.mark.parametrize(
    "tag,expected",
    [
        (b"filter-action", "FILTER"),
        (b"highlight-action", "HIGHLIGHT"),
        (b"url-action", "URL"),
        (b"edit-parameter-action", "PARAMETER"),
        (b"set-action", "SET"),
        (b"go-to-sheet-action", "GO_TO_SHEET"),
    ],
)
def test_every_known_action_type(tag, expected):
    xml = b"<workbook><actions><" + tag + b" name='[A]' /></actions></workbook>"
    assert _parse(xml)[0].action_type == expected


def test_unknown_action_tag_falls_back_to_upper_case():
    xml = b"<workbook><actions><custom-action name='[A]' /></actions></workbook>"
    assert _parse(xml)[0].action_type == "CUSTOM-ACTION"


def test_generic_action_type_comes_from_the_command():
    xml = b"""<workbook><actions><action caption='Filter 7' name='[A]'>
      <activation auto-clear='true' type='on-select' />
      <source dashboard='D' worksheet='W' />
      <command command='tsc:tsl-filter' />
    </action></actions></workbook>"""
    action = _parse(xml)[0]
    assert action.action_type == "FILTER"
    assert action.run_mode == "on-select"
    assert set(action.source_sheets) == {"D", "W"}


def test_generic_action_with_a_link_is_a_url_action():
    xml = b"""<workbook><actions><action name='[A]'>
      <source worksheet='W' /><link url='https://example.com' />
    </action></actions></workbook>"""
    assert _parse(xml)[0].action_type == "URL"


def test_non_action_children_are_skipped():
    """Tableau stores datasource bookkeeping inside <actions>."""
    xml = b"""<workbook><actions>
      <action name='[A]'><command command='tsc:tsl-filter' /></action>
      <datasources><datasource name='ds' /></datasources>
      <datasource-dependencies datasource='ds' />
    </actions></workbook>"""
    actions = _parse(xml)
    assert len(actions) == 1
    assert actions[0].action_type == "FILTER"


def test_dashboard_scoped_source_is_captured():
    xml = b"""<workbook><actions><filter-action name='[A]'>
      <source dashboard='Exec Summary' />
    </filter-action></actions></workbook>"""
    assert _parse(xml)[0].source_sheets == ["Exec Summary"]


def test_command_entries_are_captured():
    xml = b"""<workbook><actions><filter-action name='[A]'>
      <source><command name='Sheet 1' /><command name='Sheet 2' /></source>
    </filter-action></actions></workbook>"""
    assert _parse(xml)[0].source_sheets == ["Sheet 1", "Sheet 2"]


def test_run_mode_from_attribute():
    xml = b"<workbook><actions><filter-action name='[A]' run-mode='on-hover' /></actions></workbook>"
    assert _parse(xml)[0].run_mode == "on-hover"


def test_missing_run_mode_is_none():
    xml = b"<workbook><actions><filter-action name='[A]' /></actions></workbook>"
    assert _parse(xml)[0].run_mode is None


def test_action_carries_a_source_reference():
    xml = b"<workbook><actions><filter-action name='[A]' /></actions></workbook>"
    action = _parse(xml)[0]
    assert action.source.attribute == "name"
    assert "filter-action" in action.source.xpath


def test_missing_actions_section_returns_empty():
    assert _parse(b"<workbook />") == []


def test_action_tag_registry_is_complete():
    assert ACTION_TAGS["filter-action"] == "FILTER"
    assert all(v.isupper() for v in ACTION_TAGS.values())


def test_real_workbook_actions(new_workbook_xml_path):
    from conftest import parse_fixture

    workbook = parse_fixture(new_workbook_xml_path)
    # <actions> also holds <datasources> bookkeeping, which is not an action.
    assert len(workbook.actions) == 12
    assert {a.action_type for a in workbook.actions} == {"FILTER", "URL"}
