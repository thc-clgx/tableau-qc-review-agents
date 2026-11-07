"""Dashboard, zone, size and layout parsing."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional

from ..domain.models import (
    Dashboard,
    DashboardSize,
    DashboardZone,
    FormatDeclaration,
    ImageObject,
)
from .base import BaseParser
from .style_parser import StyleParser
from .text_parser import TextParser


class DashboardParser(BaseParser):
    """Parses ``/workbook/dashboards/dashboard`` elements."""

    def __init__(self, document) -> None:
        super().__init__(document)
        self.style_parser = StyleParser(document)
        self.text_parser = TextParser(document)

    def parse_all(self, root: ET.Element) -> List[Dashboard]:
        container = root.find("dashboards")
        if container is None:
            return []
        return [self.parse(el) for el in container.findall("dashboard")]

    def parse(self, element: ET.Element) -> Dashboard:
        name = self.attr(element, "name") or ""
        dashboard = Dashboard(
            name=name,
            size=self._parse_size(element),
            source=self.ref(element, "name"),
        )
        dashboard.formats = self.style_parser.parse_formats(
            element.find("style"), owner_type="dashboard", owner_id=name
        )
        dashboard.datasource_dependencies = [
            dep.get("datasource", "")
            for dep in element.findall("datasource-dependencies")
            if dep.get("datasource")
        ]
        dashboard.has_device_layouts = element.find("devicelayouts") is not None

        zones_el = element.find("zones")
        if zones_el is not None:
            dashboard.zones = [self._parse_zone(z, name) for z in zones_el.findall("zone")]
            self._mark_floating(dashboard.zones)
            dashboard.images = self._parse_images(zones_el, name)

        dashboard.formats.extend(
            self.style_parser.parse_runs(element, owner_type="dashboard", owner_id=name)
        )
        dashboard.texts = self.text_parser.parse(
            element, owner_type="dashboard", owner_id=name
        )
        return dashboard

    def _parse_images(self, zones_el: ET.Element, dashboard_name: str) -> List[ImageObject]:
        """Image zones, with the asset filename when Tableau records one."""
        images: List[ImageObject] = []
        for zone in zones_el.iter("zone"):
            if zone.get("type-v2") != "bitmap":
                continue
            images.append(
                ImageObject(
                    zone_id=self.attr(zone, "id") or "",
                    dashboard_name=dashboard_name,
                    file_name=self._image_file_name(zone),
                    x=self.int_attr(zone, "x"),
                    y=self.int_attr(zone, "y"),
                    width=self.int_attr(zone, "w"),
                    height=self.int_attr(zone, "h"),
                    source=self.ref(zone, "id"),
                )
            )
        return images

    def _image_file_name(self, zone: ET.Element) -> Optional[str]:
        """Pull the asset name out of whichever attribute Tableau used."""
        for element in zone.iter():
            for key in ("param", "file", "filename", "image", "src"):
                value = element.get(key)
                if value and "." in value:
                    return value.replace("\\", "/").rsplit("/", 1)[-1]
        return None

    def _mark_floating(self, top_level: List[DashboardZone]) -> None:
        """Flag floating objects among the dashboard's top-level zones.

        Tiled content lives inside a root layout container. Any sibling
        top-level zone that is not itself a layout container is positioned
        absolutely over the dashboard, i.e. floating. Older Tableau builds also
        set ``floating='true'`` explicitly, which ``_parse_zone`` already honours.
        """
        for zone in top_level:
            if zone.is_layout_container:
                continue
            for descendant in zone.walk():
                descendant.is_floating = True

    # -- size -------------------------------------------------------------
    def _parse_size(self, element: ET.Element) -> DashboardSize:
        size_el = element.find("size")
        if size_el is None:
            return DashboardSize()
        return DashboardSize(
            min_width=self.int_attr(size_el, "minwidth"),
            max_width=self.int_attr(size_el, "maxwidth"),
            min_height=self.int_attr(size_el, "minheight"),
            max_height=self.int_attr(size_el, "maxheight"),
            sizing_mode=self.attr(size_el, "sizing-mode"),
            source=self.ref(size_el),
        )

    # -- zones ------------------------------------------------------------
    def _parse_zone(self, element: ET.Element, dashboard_name: str) -> DashboardZone:
        zone_style = element.find("zone-style")
        formats: List[FormatDeclaration] = self.style_parser.parse_formats(
            zone_style,
            owner_type="zone",
            owner_id=f"{dashboard_name}:{element.get('id')}",
            recursive=False,
        )
        zone = DashboardZone(
            zone_id=self.attr(element, "id") or "",
            name=self.attr(element, "name"),
            zone_type=self.attr(element, "type-v2") or self.attr(element, "type"),
            x=self.int_attr(element, "x"),
            y=self.int_attr(element, "y"),
            width=self.int_attr(element, "w"),
            height=self.int_attr(element, "h"),
            is_floating=self.bool_attr(element, "floating") is True,
            is_fixed_size=self.bool_attr(element, "is-fixed") is True,
            show_title=self.bool_attr(element, "show-title"),
            param=self.attr(element, "param"),
            filter_mode=self.attr(element, "mode"),
            show_apply=self.bool_attr(element, "show-apply"),
            filter_values_source=self.attr(element, "values"),
            formats=formats,
            outer_padding=self.style_parser.parse_padding(formats, "margin"),
            inner_padding=self.style_parser.parse_padding(formats, "padding"),
            dashboard_name=dashboard_name,
            source=self.ref(element, "id"),
        )
        zone.children = [self._parse_zone(child, dashboard_name) for child in element.findall("zone")]
        return zone
