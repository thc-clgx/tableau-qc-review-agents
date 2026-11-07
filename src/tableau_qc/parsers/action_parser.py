"""Dashboard action parsing."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional

from ..domain.models import DashboardAction
from .base import BaseParser

#: Legacy element tags Tableau used for the different action kinds.
ACTION_TAGS = {
    "filter-action": "FILTER",
    "highlight-action": "HIGHLIGHT",
    "url-action": "URL",
    "edit-parameter-action": "PARAMETER",
    "set-action": "SET",
    "go-to-sheet-action": "GO_TO_SHEET",
    "annotate-action": "ANNOTATE",
}

#: Modern Tableau writes a generic ``<action>`` whose ``<command command=...>``
#: child carries the real type.
COMMAND_TYPES = {
    "tsc:tsl-filter": "FILTER",
    "tsc:filter": "FILTER",
    "tsc:highlight": "HIGHLIGHT",
    "tsc:set": "SET",
    "tsc:parameter": "PARAMETER",
    "tsc:go-to-sheet": "GO_TO_SHEET",
    "tsc:annotate": "ANNOTATE",
}

#: Children of ``<actions>`` that are not actions. Tableau stores datasource
#: bookkeeping alongside the action list, which must not be counted.
NON_ACTION_TAGS = frozenset({"datasources", "datasource-dependencies"})


class ActionParser(BaseParser):
    """Parses ``/workbook/actions`` entries."""

    def parse_all(self, root: ET.Element) -> List[DashboardAction]:
        container = root.find("actions")
        if container is None:
            return []
        return [self.parse(el) for el in container if el.tag not in NON_ACTION_TAGS]

    def parse(self, element: ET.Element) -> DashboardAction:
        return DashboardAction(
            name=self.attr(element, "name") or "",
            caption=self.attr(element, "caption"),
            action_type=self._action_type(element),
            source_sheets=self._sheets(element, "source"),
            target_sheets=self._sheets(element, "target"),
            run_mode=self._run_mode(element),
            source=self.ref(element, "name"),
        )

    def _action_type(self, element: ET.Element) -> str:
        """Resolve the action kind from the tag, the command or the link."""
        legacy = ACTION_TAGS.get(element.tag)
        if legacy:
            return legacy

        for command in element.findall("command"):
            mapped = COMMAND_TYPES.get(command.get("command") or "")
            if mapped:
                return mapped

        if element.find("link") is not None:
            return "URL"

        if element.tag == "action":
            return "UNKNOWN"
        return element.tag.upper()

    def _sheets(self, element: ET.Element, side: str) -> List[str]:
        node = element.find(side)
        if node is None:
            return []
        sheets = [c.get("name", "") for c in node.findall("command") if c.get("name")]
        if node.get("worksheet"):
            sheets.append(node.get("worksheet", ""))
        if node.get("dashboard"):
            sheets.append(node.get("dashboard", ""))
        return [s for s in sheets if s]

    def _run_mode(self, element: ET.Element) -> Optional[str]:
        link = element.find("link")
        if link is not None and link.get("run-mode"):
            return link.get("run-mode")
        activation = element.find("activation")
        if activation is not None and activation.get("type"):
            return activation.get("type")
        return self.attr(element, "run-mode")
