"""Mark colour encoding and palette extraction.

Tableau records chart mark colours separately from style formatting:

* ``<encoding attr='color' palette='...'>`` names the palette a field uses.
* ``<map to='#rrggbb'>`` assigns an explicit colour to a dimension member.
* ``<color-palette name='...'>`` declares a workbook custom palette.

Brand conformance, dominant-colour and red/green accessibility rules all read
from here rather than from ``<format>`` declarations.
"""

from __future__ import annotations

import colorsys
import xml.etree.ElementTree as ET
from typing import List, Optional

from ..domain.models import ColourUsage, MarkPalette
from .base import BaseParser

#: Palette names Tableau ships. Any of these means brand palettes were bypassed.
BUILT_IN_PALETTE_PREFIXES = (
    "tableau",
    "seattle",
    "miller",
    "blue",
    "red",
    "green",
    "orange",
    "purple",
    "gray",
    "grey",
    "cyclic",
    "traffic",
    "classic",
    "superfishel",
    "nuriel",
    "jewel",
    "summer",
    "winter",
    "hue",
    "color",
)


def _is_hex(value: Optional[str]) -> bool:
    return bool(value) and value.startswith("#") and len(value) in (7, 9)


def _rgb(value: str) -> tuple:
    value = value.lstrip("#")[:6]
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def classify_hue(value: str) -> Optional[str]:
    """Classify a hex colour as ``red``/``green`` for accessibility checks.

    Only reasonably saturated, mid-brightness colours are classified; greys and
    near-blacks are ignored because they are not what the guide warns about.
    """
    if not _is_hex(value):
        return None
    red, green, blue = _rgb(value)
    hue, lightness, saturation = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)
    if saturation < 0.25 or lightness < 0.15 or lightness > 0.9:
        return None
    degrees = hue * 360
    if degrees <= 20 or degrees >= 340:
        return "red"
    if 85 <= degrees <= 165:
        return "green"
    return None


class ColourParser(BaseParser):
    """Extracts mark colour palettes and explicit colour assignments."""

    def parse_scope(
        self, element: ET.Element, *, owner_type: str, owner_id: Optional[str]
    ) -> List[MarkPalette]:
        """Colour encodings declared anywhere below ``element``.

        Tableau records mark colours under ``<datasource>/<style>/<style-rule>``
        rather than on the worksheet, so both scopes are parsed the same way
        and attributed to their owner.
        """
        palettes: List[MarkPalette] = []
        for encoding in element.iter("encoding"):
            if encoding.get("attr") != "color":
                continue
            if not encoding.get("palette") and not any(
                m.get("to") for m in encoding.iter("map")
            ):
                continue
            palettes.append(
                MarkPalette(
                    palette_name=self.attr(encoding, "palette"),
                    field_name=self.attr(encoding, "field"),
                    encoding_type=self.attr(encoding, "type"),
                    worksheet_name=owner_id,
                    colours=self._explicit_colours(encoding, owner_id),
                    source=self.ref(encoding, "palette"),
                )
            )
        return palettes

    def parse_worksheet(self, element: ET.Element, worksheet_name: str) -> List[MarkPalette]:
        """Colour encodings declared by one worksheet."""
        return self.parse_scope(element, owner_type="worksheet", owner_id=worksheet_name)

    def _explicit_colours(
        self, encoding: ET.Element, worksheet_name: Optional[str]
    ) -> List[ColourUsage]:
        colours: List[ColourUsage] = []
        for mapping in encoding.iter("map"):
            value = mapping.get("to")
            if not _is_hex(value):
                continue
            colours.append(
                ColourUsage(
                    value=(value or "").lower(),
                    member=self.text_of(mapping) or self.attr(mapping, "key"),
                    worksheet_name=worksheet_name,
                    hue_family=classify_hue(value or ""),
                    source=self.ref(mapping, "to"),
                )
            )
        return colours

    def parse_custom_palettes(self, root: ET.Element) -> List[str]:
        """Names of custom palettes declared in the workbook preferences."""
        return sorted(
            {
                palette.get("name", "")
                for palette in root.iter("color-palette")
                if palette.get("name")
            }
        )

    @staticmethod
    def is_built_in_palette(name: Optional[str]) -> bool:
        if not name:
            return False
        lowered = name.lower()
        return any(lowered.startswith(prefix) for prefix in BUILT_IN_PALETTE_PREFIXES)
