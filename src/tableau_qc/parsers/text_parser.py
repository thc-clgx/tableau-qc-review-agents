"""Readable-text extraction from titles, tooltips, labels and text objects.

Rules about metadata completeness, interactivity instructions, naming quality
and spelling all operate on the *visible words* of a workbook rather than on
its structure, so those words are collected here as :class:`TextContent`.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import List, Optional

from ..domain.models import TextContent
from .base import BaseParser
from .style_parser import TEXT_CATEGORY_BY_PARENT, ZONE_TEXT_CATEGORY

#: Tableau field references inside formatted text, e.g. ``<[sum:Sales:qk]>``.
FIELD_REFERENCE = re.compile(r"<\[[^\]]*\]>|<[A-Za-z ]+>")

def _raw_calculation_regex():
    """Generated calculation identifiers that should never reach a user."""
    from ..standards import standards

    return standards().raw_calculation_regex


class TextParser(BaseParser):
    """Collects human-readable strings and their text category."""

    def parse(
        self, element: ET.Element, *, owner_type: str, owner_id: Optional[str]
    ) -> List[TextContent]:
        texts: List[TextContent] = []
        for block in element.iter("formatted-text"):
            raw = "".join(run.text or "" for run in block.iter("run")).strip()
            if not raw:
                continue
            texts.append(
                TextContent(
                    text=raw,
                    category=self._category_for(block),
                    owner_type=owner_type,
                    owner_id=owner_id,
                    source=self.ref(block),
                )
            )
        return texts

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


def visible_words(text: str) -> List[str]:
    """Words a user actually reads, with field references stripped out."""
    cleaned = FIELD_REFERENCE.sub(" ", text)
    cleaned = _raw_calculation_regex().sub(" ", cleaned)
    return re.findall(r"[A-Za-z][A-Za-z'’]+", cleaned)


def contains_raw_calculation(text: str) -> bool:
    return bool(_raw_calculation_regex().search(text))


def find_misspellings(text: str) -> List[str]:
    """Return ``misspelled -> correct`` notes for known domain misspellings.

    The word list is a Cotality standard, so it lives in
    ``config/standards/content.yaml`` rather than in code. Deliberately
    conservative: only listed words are reported, so product names,
    abbreviations and business jargon are never false-flagged.
    """
    from ..standards import standards

    known = standards().misspellings
    found: dict = {}
    for word in visible_words(text):
        lowered = word.lower().strip("'’")
        correction = known.get(lowered)
        if correction:
            found[lowered] = f"{word} -> {correction}"
    return [found[key] for key in sorted(found)]
