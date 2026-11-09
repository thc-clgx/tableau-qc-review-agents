"""Loader for the YAML-configured Cotality content standards.

Values that encode a *review standard* (required metadata labels, approved
spellings, naming conventions, logo placement tolerance) must never be
hard-coded in Python. They are declared in ``config/standards/content.yaml``
and read through this module.

Tableau *facts* - such as which ``type-v2`` values denote a layout container -
remain in code, because they describe the file format rather than a Cotality
decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Pattern, Sequence, Tuple, Union

import yaml

from .settings import DEFAULT_STANDARDS_PATH

PathLike = Union[str, Path]


class StandardsError(Exception):
    """Raised when the standards file is missing or malformed."""


@dataclass(frozen=True)
class ContentStandards:
    """Validated view of ``config/standards/content.yaml``."""

    metadata_elements: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
    interactivity_phrases: Tuple[str, ...] = ()
    logo_max_x: int = 12500
    logo_max_y: int = 12500
    placeholder_image_pattern: str = r"(?i)^(untitled|image|new|copy|screenshot)"
    naming_defect_patterns: Tuple[str, ...] = ()
    raw_calculation_pattern: str = r"Calculation_\d{6,}"
    misspellings: Mapping[str, str] = field(default_factory=dict)
    version: str = "unversioned"
    source_path: Optional[str] = None

    @property
    def required_metadata_elements(self) -> Tuple[str, ...]:
        return tuple(self.metadata_elements)

    @property
    def placeholder_image_regex(self) -> Pattern[str]:
        return re.compile(self.placeholder_image_pattern)

    @property
    def naming_defect_regex(self) -> Pattern[str]:
        if not self.naming_defect_patterns:
            return re.compile(r"(?!x)x")  # matches nothing
        return re.compile("|".join(self.naming_defect_patterns), re.IGNORECASE)

    @property
    def raw_calculation_regex(self) -> Pattern[str]:
        return re.compile(self.raw_calculation_pattern)

    def as_dict(self) -> Dict[str, object]:
        return {
            "version": self.version,
            "source": self.source_path,
            "metadata_elements": list(self.metadata_elements),
            "interactivity_phrase_count": len(self.interactivity_phrases),
            "naming_defect_pattern_count": len(self.naming_defect_patterns),
            "misspelling_count": len(self.misspellings),
            "logo_upper_left": [self.logo_max_x, self.logo_max_y],
        }


def _require_mapping(data: object, path: Path) -> dict:
    if not isinstance(data, dict):
        raise StandardsError(f"{path}: top level must be a mapping")
    return data


def _string_sequence(value: object, key: str, path: Path) -> Tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise StandardsError(f"{path}: '{key}' must be a list of strings")
    return tuple(value)


def load_standards(path: PathLike = DEFAULT_STANDARDS_PATH) -> ContentStandards:
    """Load and validate the content standards file."""
    file_path = Path(path)
    if not file_path.is_file():
        raise StandardsError(f"Standards file not found: {file_path}")
    try:
        data = _require_mapping(yaml.safe_load(file_path.read_text(encoding="utf-8")), file_path)
    except yaml.YAMLError as exc:
        raise StandardsError(f"Invalid YAML in {file_path}: {exc}") from exc

    raw_metadata = data.get("metadata_elements") or {}
    if not isinstance(raw_metadata, dict):
        raise StandardsError(f"{file_path}: 'metadata_elements' must be a mapping")
    metadata = {
        str(name): _string_sequence(phrases, f"metadata_elements.{name}", file_path)
        for name, phrases in raw_metadata.items()
    }

    raw_misspellings = data.get("misspellings") or {}
    if not isinstance(raw_misspellings, dict):
        raise StandardsError(f"{file_path}: 'misspellings' must be a mapping")
    misspellings = {str(k).lower(): str(v) for k, v in raw_misspellings.items()}

    logo = data.get("logo") or {}
    if not isinstance(logo, dict):
        raise StandardsError(f"{file_path}: 'logo' must be a mapping")

    patterns = _string_sequence(
        data.get("naming_defect_patterns"), "naming_defect_patterns", file_path
    )
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise StandardsError(f"{file_path}: invalid naming pattern {pattern!r}: {exc}") from exc

    raw_calculation = str(data.get("raw_calculation_pattern", r"Calculation_\d{6,}"))
    try:
        re.compile(raw_calculation)
    except re.error as exc:
        raise StandardsError(f"{file_path}: invalid raw_calculation_pattern: {exc}") from exc

    return ContentStandards(
        metadata_elements=metadata,
        interactivity_phrases=tuple(
            p.lower()
            for p in _string_sequence(
                data.get("interactivity_phrases"), "interactivity_phrases", file_path
            )
        ),
        logo_max_x=int(logo.get("upper_left_max_x", 12500)),
        logo_max_y=int(logo.get("upper_left_max_y", 12500)),
        placeholder_image_pattern=str(
            logo.get("placeholder_name_pattern", r"(?i)^(untitled|image|new|copy|screenshot)")
        ),
        naming_defect_patterns=patterns,
        raw_calculation_pattern=raw_calculation,
        misspellings=misspellings,
        version=str(data.get("version", "unversioned")),
        source_path=str(file_path),
    )


@lru_cache(maxsize=4)
def _cached(path: str) -> ContentStandards:
    return load_standards(path)


def standards() -> ContentStandards:
    """Process-wide standards, loaded once and cached."""
    return _cached(str(DEFAULT_STANDARDS_PATH))


def reset_cache() -> None:
    """Clear the cache - used by tests that point at a temporary file."""
    _cached.cache_clear()
