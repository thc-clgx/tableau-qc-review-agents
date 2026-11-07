"""Secure XML loading.

Hardening applied:

* DOCTYPE / DTD declarations are rejected (blocks billion-laughs style attacks).
* Entity declarations are rejected.
* External entity resolution is disabled (blocks XXE and SSRF).
* Parameter entity parsing is disabled.
* Input size and nesting depth are bounded.

The loader never resolves anything over the network and never touches the
filesystem beyond the single file it was asked to read.
"""

from __future__ import annotations

import hashlib
import io
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional, Union
from xml.parsers import expat

#: 64 MiB is far larger than any realistic Tableau workbook XML.
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_DEPTH = 120


class XMLSecurityError(Exception):
    """Raised when the XML input violates a security constraint."""


class XMLLoadError(Exception):
    """Raised when the XML input cannot be parsed."""


class _SecureExpatParser:
    """An expat parser with every unsafe feature switched off.

    ``xml.etree.ElementTree.XMLParser`` no longer exposes its underlying expat
    parser, so the handlers are installed on an expat parser driven directly
    into an ``ElementTree`` builder.
    """

    def __init__(self) -> None:
        self._builder = ET.TreeBuilder()
        parser = expat.ParserCreate()
        parser.buffer_text = True
        parser.StartDoctypeDeclHandler = self._reject_doctype
        parser.EntityDeclHandler = self._reject_entity
        parser.UnparsedEntityDeclHandler = self._reject_unparsed_entity
        parser.ExternalEntityRefHandler = self._reject_external_entity
        parser.NotationDeclHandler = self._reject_notation
        parser.StartElementHandler = self._start
        parser.EndElementHandler = self._end
        parser.CharacterDataHandler = self._data
        try:
            parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
        except (AttributeError, TypeError):  # pragma: no cover - platform specific
            pass
        self._parser = parser

    def parse(self, data: bytes) -> ET.Element:
        self._parser.Parse(data, True)
        return self._builder.close()

    def _start(self, tag: str, attrs: Dict[str, str]) -> None:
        self._builder.start(tag, dict(attrs))

    def _end(self, tag: str) -> None:
        self._builder.end(tag)

    def _data(self, data: str) -> None:
        self._builder.data(data)

    @staticmethod
    def _reject_doctype(name, sysid, pubid, has_internal_subset):  # noqa: ANN001
        raise XMLSecurityError(f"DOCTYPE declarations are forbidden (found '{name}')")

    @staticmethod
    def _reject_entity(*args):  # noqa: ANN002
        raise XMLSecurityError("Entity declarations are forbidden")

    @staticmethod
    def _reject_unparsed_entity(*args):  # noqa: ANN002
        raise XMLSecurityError("Unparsed entity declarations are forbidden")

    @staticmethod
    def _reject_notation(*args):  # noqa: ANN002
        raise XMLSecurityError("Notation declarations are forbidden")

    @staticmethod
    def _reject_external_entity(*args):  # noqa: ANN002
        raise XMLSecurityError("External entity resolution is disabled")


@dataclass
class ParsedDocument:
    """A safely parsed XML document plus XPath bookkeeping for evidence."""

    root: ET.Element
    source_path: Optional[str] = None
    sha256: Optional[str] = None
    byte_size: int = 0

    def __post_init__(self) -> None:
        self._paths: Dict[int, str] = {}
        self._parents: Dict[int, ET.Element] = {}
        self._index(self.root, f"/{self.root.tag}")

    def _index(self, element: ET.Element, path: str) -> None:
        self._paths[id(element)] = path
        counters: Dict[str, int] = {}
        for child in element:
            counters[child.tag] = counters.get(child.tag, 0) + 1
            self._parents[id(child)] = element
            self._index(child, f"{path}/{child.tag}[{counters[child.tag]}]")

    def xpath_of(self, element: ET.Element) -> str:
        """Absolute, index-qualified XPath of ``element``."""
        return self._paths.get(id(element), "")

    def parent_of(self, element: ET.Element) -> Optional[ET.Element]:
        return self._parents.get(id(element))

    @property
    def depth(self) -> int:
        return max((p.count("/") for p in self._paths.values()), default=0)


def _check_declaration_safety(data: bytes) -> None:
    head = data[:4096].lstrip()
    lowered = head.lower()
    if b"<!doctype" in lowered:
        raise XMLSecurityError("DOCTYPE declarations are forbidden")
    if b"<!entity" in lowered:
        raise XMLSecurityError("Entity declarations are forbidden")


def _find_tag_end(data: bytes, start: int) -> int:
    """Index of the ``>`` closing the tag at ``start``, ignoring quoted text.

    Attribute values may legitimately contain ``>`` (Tableau embeds formulas and
    captions in attributes), so quoted spans must be skipped.
    """
    i = start
    length = len(data)
    quote = b""
    while i < length:
        char = data[i : i + 1]
        if quote:
            if char == quote:
                quote = b""
        elif char in (b'"', b"'"):
            quote = char
        elif char == b">":
            return i
        i += 1
    return -1


def _max_depth(data: bytes) -> int:
    """Structural depth estimate used before building the tree.

    Comments, CDATA sections and processing instructions are skipped wholesale:
    Tableau stores SQL and formatted text inside CDATA, which routinely contains
    ``<`` characters that are not element starts.
    """
    depth = 0
    max_depth = 0
    i = 0
    length = len(data)
    while i < length:
        if data[i : i + 1] != b"<":
            i += 1
            continue

        if data.startswith(b"<![CDATA[", i):
            end = data.find(b"]]>", i)
            i = length if end == -1 else end + 3
            continue
        if data.startswith(b"<!--", i):
            end = data.find(b"-->", i)
            i = length if end == -1 else end + 3
            continue
        if data.startswith(b"<?", i):
            end = data.find(b"?>", i)
            i = length if end == -1 else end + 2
            continue
        if data.startswith(b"<!", i):
            end = _find_tag_end(data, i)
            i = length if end == -1 else end + 1
            continue

        nxt = data[i + 1 : i + 2]
        if nxt == b"/":
            depth -= 1
            end = _find_tag_end(data, i)
            i = length if end == -1 else end + 1
            continue

        if not (nxt.isalpha() or nxt == b"_"):
            # A bare '<' in character data is not an element start.
            i += 1
            continue

        end = _find_tag_end(data, i)
        if end == -1:
            break
        if data[end - 1 : end] != b"/":
            depth += 1
            max_depth = max(max_depth, depth)
        i = end + 1
    return max_depth


def load_xml_bytes(
    data: bytes,
    *,
    source_path: Optional[str] = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> ParsedDocument:
    """Parse XML bytes securely and return a :class:`ParsedDocument`."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("load_xml_bytes expects bytes")
    if len(data) == 0:
        raise XMLLoadError("XML input is empty")
    if len(data) > max_bytes:
        raise XMLSecurityError(f"XML input exceeds the {max_bytes} byte limit")

    data = bytes(data)
    _check_declaration_safety(data)
    estimated_depth = _max_depth(data)
    if estimated_depth > max_depth:
        raise XMLSecurityError(f"XML nesting depth {estimated_depth} exceeds the limit of {max_depth}")

    parser = _SecureExpatParser()
    try:
        root = parser.parse(data)
    except XMLSecurityError:
        raise
    except expat.ExpatError as exc:
        raise XMLLoadError(f"Malformed XML: {exc}") from exc
    except ET.ParseError as exc:
        raise XMLLoadError(f"Malformed XML: {exc}") from exc

    return ParsedDocument(
        root=root,
        source_path=source_path,
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
    )


def load_xml_file(
    path: Union[str, os.PathLike, Path],
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> ParsedDocument:
    """Read and securely parse a Tableau workbook XML file."""
    file_path = Path(path)
    if not file_path.is_file():
        raise XMLLoadError(f"XML file not found: {file_path}")
    size = file_path.stat().st_size
    if size > max_bytes:
        raise XMLSecurityError(f"XML file exceeds the {max_bytes} byte limit ({size} bytes)")
    data = file_path.read_bytes()
    return load_xml_bytes(
        data,
        source_path=str(file_path.resolve()),
        max_bytes=max_bytes,
        max_depth=max_depth,
    )


def load_xml_stream(
    stream: io.BufferedIOBase,
    *,
    source_path: Optional[str] = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> ParsedDocument:
    """Securely parse XML from an already-open binary stream."""
    data = stream.read(max_bytes + 1)
    return load_xml_bytes(data, source_path=source_path, max_bytes=max_bytes)


__all__: Iterable[str] = (
    "ParsedDocument",
    "XMLLoadError",
    "XMLSecurityError",
    "load_xml_bytes",
    "load_xml_file",
    "load_xml_stream",
)
