"""Default paths and runtime settings.

Every path can be overridden by an environment variable so that no reviewer
standard is hard-coded into Python.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Repository root (``src/tableau_qc/settings.py`` -> ``<root>``).
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else default


DEFAULT_RULES_DIR: Path = _path_from_env("TABLEAU_QC_RULES_DIR", PROJECT_ROOT / "config" / "rules")
DEFAULT_CHECKLIST_DIR: Path = _path_from_env(
    "TABLEAU_QC_CHECKLIST_DIR", PROJECT_ROOT / "config" / "checklist"
)
DEFAULT_CHECKLIST_PATH: Path = _path_from_env("TABLEAU_QC_CHECKLIST", DEFAULT_CHECKLIST_DIR)
DEFAULT_STANDARDS_PATH: Path = _path_from_env(
    "TABLEAU_QC_STANDARDS", PROJECT_ROOT / "config" / "standards" / "content.yaml"
)
DEFAULT_EXCEL_TEMPLATE: Path = _path_from_env(
    "TABLEAU_QC_EXCEL_TEMPLATE",
    PROJECT_ROOT / "examples" / "standards" / "draft Tableau Dashboard Review - [Report Name].xlsx",
)
DEFAULT_OUTPUT_DIR: Path = _path_from_env("TABLEAU_QC_OUTPUT_DIR", PROJECT_ROOT / "output")

#: Optional LLM enrichment is opt-in and off by default.
LLM_ENABLED: bool = os.environ.get("TABLEAU_QC_LLM_ENABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}


def excel_template_or_none() -> Path | None:
    """Return the review template path if it exists, otherwise ``None``."""
    return DEFAULT_EXCEL_TEMPLATE if DEFAULT_EXCEL_TEMPLATE.is_file() else None
