"""Unit tests for the dashboard/zone parser."""

from __future__ import annotations

from conftest import parse_fixture
from tableau_qc.parsers.dashboard_parser import DashboardParser
from tableau_qc.xmlio.loader import load_xml_bytes


def test_dashboard_size(sample_workbook):
    dashboard = sample_workbook.dashboards[0]
    assert dashboard.name == "Interactive Dashboard"
    assert dashboard.size.width == 1000
    assert dashboard.size.height == 800
    assert dashboard.size.is_fixed is True
    assert dashboard.size.source.xpath.endswith("/size[1]")


def test_zone_hierarchy_is_preserved(sample_workbook):
    dashboard = sample_workbook.dashboards[0]
    assert len(dashboard.zones) == 1
    assert len(dashboard.all_zones) > len(dashboard.zones)
    root_zone = dashboard.zones[0]
    assert root_zone.is_layout_container is True
    assert any(child.is_layout_container for child in root_zone.children)


def test_view_zones_are_identified(sample_workbook):
    dashboard = sample_workbook.dashboards[0]
    assert dashboard.view_count == 9
    assert "sales by category" in dashboard.worksheet_names
    assert all(zone.references_worksheet for zone in dashboard.view_zones)


def test_filter_zones_are_identified(sample_workbook):
    dashboard = sample_workbook.dashboards[0]
    assert dashboard.filter_count == 3
    assert all(zone.zone_type == "filter" for zone in dashboard.filter_zones)
    assert all(not zone.is_view for zone in dashboard.filter_zones)


def test_zone_padding_parsed_from_zone_style(sample_workbook):
    zone = sample_workbook.dashboards[0].view_zones[0]
    assert zone.outer_padding.minimum == 4
    assert zone.outer_padding.declared_sides == ["top", "right", "bottom", "left"]
    assert zone.inner_padding.is_declared is False
    assert zone.inner_padding.minimum is None


def test_zone_evidence_points_at_the_zone(sample_workbook):
    zone = sample_workbook.dashboards[0].view_zones[0]
    assert zone.source.xpath.startswith("/workbook/dashboards[1]/dashboard[1]/zones[1]")
    assert zone.source.attribute == "id"


def test_zone_geometry(sample_workbook):
    zone = sample_workbook.dashboards[0].zones[0]
    assert (zone.x, zone.y, zone.width, zone.height) == (0, 0, 100000, 100000)


def test_fixture_padding_values(rule_fixtures_dir):
    workbook = parse_fixture(rule_fixtures_dir / "CTL-LAYOUT-004_pass.xml")
    zone = workbook.dashboards[0].view_zones[0]
    assert zone.outer_padding.minimum == 20
    assert zone.inner_padding.minimum == 12


def test_floating_zone_detection():
    xml = b"""<workbook version='18.1'>
      <worksheets><worksheet name='S1'><table /></worksheet></worksheets>
      <dashboards>
        <dashboard name='D'>
          <size maxheight='900' maxwidth='1600' minheight='900' minwidth='1600' />
          <zones>
            <zone h='100000' id='1' type-v2='layout-basic' w='100000' x='0' y='0'>
              <zone floating='true' h='100' id='2' name='S1' w='100' x='0' y='0' />
            </zone>
          </zones>
        </dashboard>
      </dashboards>
    </workbook>"""
    document = load_xml_bytes(xml)
    dashboard = DashboardParser(document).parse_all(document.root)[0]
    assert dashboard.floating_zone_count == 1
    assert dashboard.view_zones[0].is_floating is True


def test_top_level_non_layout_zones_are_floating():
    """Modern Tableau omits floating='true'; floating objects sit beside the root container."""
    xml = b"""<workbook version='18.1'>
      <worksheets><worksheet name='S1'><table /></worksheet></worksheets>
      <dashboards>
        <dashboard name='D'>
          <size maxheight='900' maxwidth='1600' minheight='900' minwidth='1600' />
          <zones>
            <zone h='100000' id='1' type-v2='layout-flow' w='100000' x='0' y='0'>
              <zone h='50000' id='2' name='S1' w='50000' x='0' y='0' />
            </zone>
            <zone h='2556' id='440' param='[Parameters].[P1]' type-v2='paramctrl' w='14438' x='83313' y='40111' />
            <zone h='1889' id='637' type-v2='text' w='84500' x='13750' y='97556' />
          </zones>
        </dashboard>
      </dashboards>
    </workbook>"""
    document = load_xml_bytes(xml)
    dashboard = DashboardParser(document).parse_all(document.root)[0]
    assert dashboard.floating_zone_count == 2
    assert {z.zone_id for z in dashboard.all_zones if z.is_floating} == {"440", "637"}
    # The tiled worksheet inside the layout container stays tiled.
    assert dashboard.view_zones[0].is_floating is False


def test_single_layout_container_has_no_floating_zones(sample_workbook):
    assert sample_workbook.dashboards[0].floating_zone_count == 0


def test_automatic_sizing_reports_unknown_dimensions():
    xml = b"""<workbook version='18.1'>
      <dashboards>
        <dashboard name='D'>
          <size maxheight='2000' maxwidth='2000' minheight='400' minwidth='400' sizing-mode='automatic' />
          <zones />
        </dashboard>
      </dashboards>
    </workbook>"""
    document = load_xml_bytes(xml)
    dashboard = DashboardParser(document).parse_all(document.root)[0]
    assert dashboard.size.width is None
    assert dashboard.size.is_fixed is False


def test_missing_size_element_yields_unknown():
    xml = b"<workbook version='18.1'><dashboards><dashboard name='D'><zones /></dashboard></dashboards></workbook>"
    document = load_xml_bytes(xml)
    dashboard = DashboardParser(document).parse_all(document.root)[0]
    assert dashboard.size.width is None
    assert dashboard.size.height is None
    assert dashboard.size.is_fixed is None
