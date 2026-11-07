"""Shared parser helpers.

All XPath/attribute knowledge of the Tableau XML dialect lives in the
``tableau_qc.parsers`` package. Nothing outside this package may touch
``xml.etree`` elements.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from ..domain.models import SourceRef
from ..xmlio.loader import ParsedDocument

#: ``xml:base`` may be reported either raw or namespace-expanded.
XML_BASE_KEYS = ("xml:base", "{http://www.w3.org/XML/1998/namespace}base")

TRUE_VALUES = {"true", "yes", "1"}
FALSE_VALUES = {"false", "no", "0"}


class BaseParser:
    """Common behaviour for element parsers."""

    def __init__(self, document: ParsedDocument) -> None:
        self.document = document

    # -- evidence helpers -------------------------------------------------
    def ref(self, element: ET.Element, attribute: Optional[str] = None) -> SourceRef:
        return SourceRef(xpath=self.document.xpath_of(element), attribute=attribute)

    # -- attribute helpers ------------------------------------------------
    @staticmethod
    def attr(element: ET.Element, name: str, default: Optional[str] = None) -> Optional[str]:
        value = element.get(name)
        return default if value is None else value

    @staticmethod
    def int_attr(element: ET.Element, name: str) -> Optional[int]:
        raw = element.get(name)
        if raw is None:
            return None
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def float_attr(element: ET.Element, name: str) -> Optional[float]:
        raw = element.get(name)
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def bool_attr(element: ET.Element, name: str) -> Optional[bool]:
        raw = element.get(name)
        if raw is None:
            return None
        lowered = raw.strip().lower()
        if lowered in TRUE_VALUES:
            return True
        if lowered in FALSE_VALUES:
            return False
        return None

    @staticmethod
    def xml_base(element: ET.Element) -> Optional[str]:
        for key in XML_BASE_KEYS:
            if key in element.attrib:
                return element.attrib[key]
        return None

    @staticmethod
    def text_of(element: Optional[ET.Element]) -> Optional[str]:
        if element is None:
            return None
        text = "".join(element.itertext()).strip()
        return text or None

    @staticmethod
    def attrib_dict(element: ET.Element, keys: Optional[List[str]] = None) -> Dict[str, str]:
        if keys is None:
            return dict(element.attrib)
        return {k: element.attrib[k] for k in keys if k in element.attrib}
