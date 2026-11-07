"""Workbook-level parsing and normalisation.

``WorkbookParser`` is the single entry point used by both agents: it turns a
securely parsed XML document into the normalised :class:`Workbook` model that
the rule engine consumes.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional

from ..domain.models import OptimizerRule, Workbook, WorkbookStyle, WindowRef
from ..xmlio.loader import ParsedDocument, load_xml_bytes, load_xml_file
from .action_parser import ActionParser
from .base import BaseParser
from .colour_parser import ColourParser
from .dashboard_parser import DashboardParser
from .datasource_parser import DataSourceParser
from .style_parser import StyleParser
from .worksheet_parser import VisibilityParser, WorksheetParser


class WorkbookParseError(Exception):
    """Raised when the XML is not a Tableau workbook document."""


class WorkbookParser(BaseParser):
    """Parses the full workbook and normalises cross-references."""

    def __init__(self, document: ParsedDocument) -> None:
        super().__init__(document)
        self.style_parser = StyleParser(document)
        self.datasource_parser = DataSourceParser(document)
        self.worksheet_parser = WorksheetParser(document)
        self.dashboard_parser = DashboardParser(document)
        self.action_parser = ActionParser(document)
        self.visibility_parser = VisibilityParser(document)
        self.colour_parser = ColourParser(document)

    def parse(self) -> Workbook:
        root = self.document.root
        if root.tag != "workbook":
            raise WorkbookParseError(
                f"Expected a Tableau <workbook> root element, found <{root.tag}>"
            )

        workbook = Workbook(
            name=self._workbook_name(root),
            version=self.attr(root, "version"),
            original_version=self.attr(root, "original-version"),
            source_build=self.attr(root, "source-build"),
            source_platform=self.attr(root, "source-platform"),
            repository_location=self._repository_location(root),
            preferences=self._preferences(root),
            source_path=self.document.source_path,
            source_sha256=self.document.sha256,
            source=self.ref(root),
        )

        workbook.datasources = self.datasource_parser.parse_all(root)
        workbook.worksheets = self.worksheet_parser.parse_all(root)
        workbook.dashboards = self.dashboard_parser.parse_all(root)
        workbook.actions = self.action_parser.parse_all(root)
        workbook.windows = self._parse_windows(root)
        workbook.optimizer_rules = self._parse_optimizer_rules(root)
        workbook.custom_palettes = self.colour_parser.parse_custom_palettes(root)
        workbook.datasource_palettes = self._parse_datasource_palettes(root)
        workbook.style = self._build_style(root, workbook)

        self._normalise(workbook)
        return workbook

    def _parse_datasource_palettes(self, root: ET.Element) -> list:
        """Mark colour encodings, which Tableau stores on the datasource."""
        container = root.find("datasources")
        if container is None:
            return []
        palettes = []
        for datasource in container.findall("datasource"):
            palettes.extend(
                self.colour_parser.parse_scope(
                    datasource,
                    owner_type="datasource",
                    owner_id=datasource.get("name"),
                )
            )
        return palettes

    def _parse_optimizer_rules(self, root: ET.Element) -> list:
        """Workbook Optimizer rule suppressions (``<rule ignored='true'/>``)."""
        rules = []
        for element in root.iter("rule"):
            rule_id = element.get("ruleID") or element.get("ruleid")
            if rule_id is None:
                continue
            rules.append(
                OptimizerRule(
                    rule_id=rule_id,
                    is_ignored=self.bool_attr(element, "ignored") is True,
                    source=self.ref(element, "ignored"),
                )
            )
        return rules

    # -- workbook metadata -------------------------------------------------
    def _workbook_name(self, root: ET.Element) -> Optional[str]:
        repository = root.find("repository-location")
        if repository is not None and repository.get("id"):
            return repository.get("id")
        if self.document.source_path:
            return Path(self.document.source_path).stem
        return None

    def _repository_location(self, root: ET.Element) -> Dict[str, str]:
        repository = root.find("repository-location")
        if repository is None:
            return {}
        return self.attrib_dict(repository, ["id", "path", "site", "revision", "derived-from"])

    def _preferences(self, root: ET.Element) -> Dict[str, str]:
        container = root.find("preferences")
        if container is None:
            return {}
        return {
            pref.get("name", ""): pref.get("value", "")
            for pref in container.findall("preference")
            if pref.get("name")
        }

    def _parse_windows(self, root: ET.Element) -> list:
        container = root.find("windows")
        if container is None:
            return []
        windows = []
        for window in container.findall("window"):
            windows.append(
                WindowRef(
                    name=self.attr(window, "name") or "",
                    window_class=self.attr(window, "class"),
                    is_hidden=self.bool_attr(window, "hidden") is True,
                    source=self.ref(window, "hidden"),
                )
            )
        return windows

    # -- style aggregation -------------------------------------------------
    def _build_style(self, root: ET.Element, workbook: Workbook) -> WorkbookStyle:
        formats = self.style_parser.parse_formats(
            root.find("style"), owner_type="workbook", owner_id=workbook.name
        )
        for worksheet in workbook.worksheets:
            formats.extend(worksheet.formats)
        for dashboard in workbook.dashboards:
            formats.extend(dashboard.formats)
            for zone in dashboard.all_zones:
                formats.extend(zone.formats)
        return WorkbookStyle(formats=formats)

    # -- normalisation -----------------------------------------------------
    def _normalise(self, workbook: Workbook) -> None:
        """Resolve cross-object references that no single parser owns."""
        hidden = {w.name for w in workbook.windows if w.window_class == "worksheet" and w.is_hidden}
        declared = {w.name for w in workbook.windows if w.window_class == "worksheet"}
        worksheet_names = {ws.name for ws in workbook.worksheets}

        for worksheet in workbook.worksheets:
            if worksheet.name in hidden:
                worksheet.is_visible = False
            elif worksheet.name in declared:
                worksheet.is_visible = True
            else:
                worksheet.is_visible = None

        for dashboard in workbook.dashboards:
            for zone in dashboard.all_zones:
                zone.dashboard_name = dashboard.name
                zone.references_worksheet = bool(zone.name) and zone.name in worksheet_names
                if zone.is_view and zone.references_worksheet:
                    worksheet = workbook.worksheet_by_name(zone.name or "")
                    if worksheet is not None and dashboard.name not in worksheet.used_in_dashboards:
                        worksheet.used_in_dashboards.append(dashboard.name)


def parse_workbook_file(path) -> Workbook:
    """Securely load and parse a Tableau workbook XML file."""
    return WorkbookParser(load_xml_file(path)).parse()


def parse_workbook_bytes(data: bytes, *, source_path: Optional[str] = None) -> Workbook:
    """Securely load and parse Tableau workbook XML from memory."""
    return WorkbookParser(load_xml_bytes(data, source_path=source_path)).parse()
