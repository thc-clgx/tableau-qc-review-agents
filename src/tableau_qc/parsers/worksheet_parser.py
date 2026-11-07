"""Worksheet, mark and worksheet-filter parsing."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List

from ..domain.models import Worksheet, WorksheetFilter
from .base import BaseParser
from .colour_parser import ColourParser
from .style_parser import StyleParser
from .text_parser import TextParser


class WorksheetParser(BaseParser):
    """Parses ``/workbook/worksheets/worksheet`` elements."""

    def __init__(self, document) -> None:
        super().__init__(document)
        self.style_parser = StyleParser(document)
        self.colour_parser = ColourParser(document)
        self.text_parser = TextParser(document)

    def parse_all(self, root: ET.Element) -> List[Worksheet]:
        container = root.find("worksheets")
        if container is None:
            return []
        return [self.parse(el) for el in container.findall("worksheet")]

    def parse(self, element: ET.Element) -> Worksheet:
        name = self.attr(element, "name") or ""
        worksheet = Worksheet(name=name, source=self.ref(element, "name"))

        table = element.find("table")
        view = table.find("view") if table is not None else None

        if table is not None:
            worksheet.formats = self.style_parser.parse_formats(
                table.find("style"), owner_type="worksheet", owner_id=name
            )

        # Fonts declared through formatted text (titles, tooltips, labels).
        worksheet.formats.extend(
            self.style_parser.parse_runs(element, owner_type="worksheet", owner_id=name)
        )
        worksheet.texts = self.text_parser.parse(
            element, owner_type="worksheet", owner_id=name
        )
        worksheet.palettes = self.colour_parser.parse_worksheet(element, name)

        if view is not None:
            worksheet.datasource_dependencies = [
                dep.get("datasource", "")
                for dep in view.findall("datasource-dependencies")
                if dep.get("datasource")
            ]
            worksheet.filters = self._parse_filters(view, name)

        worksheet.mark_classes = sorted(
            {
                mark.get("class")
                for mark in element.iter("mark")
                if mark.get("class")
            }
        )
        worksheet.has_title = self._has_title(element)
        return worksheet

    def _parse_filters(self, view: ET.Element, worksheet_name: str) -> List[WorksheetFilter]:
        filters: List[WorksheetFilter] = []
        for filter_el in view.findall("filter"):
            column = self.attr(filter_el, "column")
            filters.append(
                WorksheetFilter(
                    column=column,
                    filter_class=self.attr(filter_el, "class"),
                    worksheet_name=worksheet_name,
                    datasource=self._datasource_of(column),
                    source=self.ref(filter_el, "column"),
                )
            )
        return filters

    @staticmethod
    def _datasource_of(column: str | None) -> str | None:
        """``[Sample - Superstore].[none:Category:nk]`` -> ``Sample - Superstore``."""
        if not column or not column.startswith("["):
            return None
        end = column.find("]")
        return column[1:end] if end > 1 else None

    def _has_title(self, element: ET.Element) -> bool:
        layout = element.find("layout-options")
        if layout is None:
            return False
        title = layout.find("title")
        if title is None:
            return False
        return self.text_of(title) is not None


class VisibilityParser(BaseParser):
    """Worksheet visibility is declared in ``/workbook/windows``."""

    def hidden_worksheet_names(self, root: ET.Element) -> List[str]:
        container = root.find("windows")
        if container is None:
            return []
        return [
            window.get("name", "")
            for window in container.findall("window")
            if window.get("class") == "worksheet" and self.bool_attr(window, "hidden") is True
        ]
