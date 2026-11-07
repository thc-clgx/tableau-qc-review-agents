"""Style, font, colour and padding extraction from Tableau XML."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional

from ..domain.models import FormatDeclaration, Padding
from .base import BaseParser

#: ``<format attr='...'>`` names that carry colour values.
COLOUR_ATTRS = (
    "color",
    "background-color",
    "border-color",
    "font-color",
    "mark-labels-color",
    "header-color",
    "title-color",
)

FONT_ATTRS = ("font-family", "font-size", "font-weight", "font-style", "fontname", "fontsize")

#: Side suffixes recognised for margin/padding declarations.
SIDES = ("top", "right", "bottom", "left")

#: ``<run>`` attribute -> canonical ``FormatDeclaration`` attr name.
RUN_ATTR_MAP = {
    "fontname": "font-family",
    "fontsize": "font-size",
    "fontcolor": "color",
    "bold": "font-weight",
    "italic": "font-style",
}

#: Parent element tag -> the text category a ``<run>`` belongs to.
#: Tableau nests formatted text differently depending on what it styles.
TEXT_CATEGORY_BY_PARENT = {
    "customized-tooltip": "tooltip",
    "customized-label": "label",
    "title": "worksheet-title",
    "caption": "caption",
    "format": "style-rule",
}

#: Zone ``type-v2`` values whose formatted text is a dashboard text object.
ZONE_TEXT_CATEGORY = "dashboard-text"


class StyleParser(BaseParser):
    """Extracts ``<format>`` declarations and padding from style elements."""

    def parse_formats(
        self,
        element: Optional[ET.Element],
        *,
        owner_type: str,
        owner_id: Optional[str],
        recursive: bool = True,
    ) -> List[FormatDeclaration]:
        """Collect ``<format>`` declarations below ``element``.

        ``recursive=False`` only looks at direct ``<format>`` children, which is
        what zone styles require so that nested zones are not double counted.
        """
        if element is None:
            return []
        declarations: List[FormatDeclaration] = []
        if recursive:
            self._collect(element, None, owner_type, owner_id, declarations)
        else:
            for child in element:
                if child.tag == "format":
                    declarations.append(self._declaration(child, None, owner_type, owner_id))
        return declarations

    def _collect(
        self,
        element: ET.Element,
        style_rule_element: Optional[str],
        owner_type: str,
        owner_id: Optional[str],
        out: List[FormatDeclaration],
    ) -> None:
        for child in element:
            if child.tag == "format":
                out.append(self._declaration(child, style_rule_element, owner_type, owner_id))
            elif child.tag == "style-rule":
                self._collect(child, child.get("element"), owner_type, owner_id, out)
            elif child.tag in ("zone", "zones"):
                # Nested zones own their declarations; skip them here.
                continue
            else:
                self._collect(child, style_rule_element, owner_type, owner_id, out)

    def _declaration(
        self,
        element: ET.Element,
        style_rule_element: Optional[str],
        owner_type: str,
        owner_id: Optional[str],
    ) -> FormatDeclaration:
        return FormatDeclaration(
            attr=element.get("attr", ""),
            value=element.get("value"),
            source=self.ref(element, "value"),
            element=style_rule_element,
            owner_type=owner_type,
            owner_id=owner_id,
        )

    # -- padding ----------------------------------------------------------
    def parse_padding(self, formats: List[FormatDeclaration], prefix: str) -> Padding:
        """Build a :class:`Padding` from ``margin``/``padding`` declarations.

        The shorthand (``margin``) seeds all four sides; side-specific
        declarations (``margin-left``) override it. Undeclared sides stay
        ``None`` - the framework never assumes a Tableau default.
        """
        base: Optional[float] = None
        base_source = None
        sides: dict = {side: None for side in SIDES}
        side_sources: dict = {side: None for side in SIDES}

        for declaration in formats:
            if declaration.attr == prefix:
                value = declaration.numeric_value
                if value is not None:
                    base = value
                    base_source = declaration.source
            elif declaration.attr.startswith(f"{prefix}-"):
                side = declaration.attr[len(prefix) + 1 :]
                if side in sides:
                    value = declaration.numeric_value
                    if value is not None:
                        sides[side] = value
                        side_sources[side] = declaration.source

        if base is None and all(v is None for v in sides.values()):
            return Padding()

        resolved = {side: (sides[side] if sides[side] is not None else base) for side in SIDES}
        source = next((s for s in side_sources.values() if s is not None), None) or base_source
        return Padding(
            top=resolved["top"],
            right=resolved["right"],
            bottom=resolved["bottom"],
            left=resolved["left"],
            source=source,
        )

    # -- formatted text (<run>) -------------------------------------------
    def parse_runs(
        self,
        element: ET.Element,
        *,
        owner_type: str,
        owner_id: Optional[str],
    ) -> List[FormatDeclaration]:
        """Harvest font declarations from ``<run>`` elements below ``element``.

        Tableau records fonts in two unrelated places: ``<format attr=
        'font-family'>`` for workbook/worksheet formatting, and ``<run
        fontname=... fontsize=...>`` inside ``<formatted-text>`` for titles,
        tooltips, labels and text objects. Both must be collected or a workbook
        that styles everything through titles looks like it declares no fonts.

        The emitted ``element`` field carries the *text category* (tooltip,
        worksheet-title, label, ...) so rules can check per-category
        consistency.
        """
        declarations: List[FormatDeclaration] = []
        for parent, category in self._formatted_text_blocks(element):
            for run in parent.iter("run"):
                for raw_attr, canonical in RUN_ATTR_MAP.items():
                    value = run.get(raw_attr)
                    if value is None:
                        continue
                    declarations.append(
                        FormatDeclaration(
                            attr=canonical,
                            value=value,
                            source=self.ref(run, raw_attr),
                            element=category,
                            owner_type=owner_type,
                            owner_id=owner_id,
                        )
                    )
        return declarations

    def _formatted_text_blocks(self, element: ET.Element):
        """Yield ``(formatted-text element, text category)`` pairs."""
        for block in element.iter("formatted-text"):
            yield block, self._category_for(block)

    def _category_for(self, block: ET.Element) -> str:
        parent = self.document.parent_of(block)
        if parent is None:
            return "unknown"
        category = TEXT_CATEGORY_BY_PARENT.get(parent.tag)
        if category is not None:
            return category
        if parent.tag == "zone":
            return ZONE_TEXT_CATEGORY
        return parent.tag

    # -- convenience ------------------------------------------------------
    @staticmethod
    def font_declarations(formats: List[FormatDeclaration]) -> List[FormatDeclaration]:
        return [f for f in formats if f.attr in FONT_ATTRS]

    @staticmethod
    def colour_declarations(formats: List[FormatDeclaration]) -> List[FormatDeclaration]:
        return [f for f in formats if f.attr in COLOUR_ATTRS]
