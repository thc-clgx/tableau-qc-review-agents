"""Secure XML input handling."""

from .loader import ParsedDocument, XMLLoadError, XMLSecurityError, load_xml_bytes, load_xml_file

__all__ = [
    "ParsedDocument",
    "XMLLoadError",
    "XMLSecurityError",
    "load_xml_bytes",
    "load_xml_file",
]
