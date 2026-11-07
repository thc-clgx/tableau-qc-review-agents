"""Machine-readable JSON reporting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Union

from ..domain.comparison import VerificationReport
from ..domain.findings import ReviewReport

PathLike = Union[str, Path]


def report_to_dict(report: Union[ReviewReport, VerificationReport]) -> Dict[str, Any]:
    return report.as_dict()


def write_json_report(report: Union[ReviewReport, VerificationReport], path: PathLike) -> Path:
    """Write a report as deterministic, pretty-printed JSON."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report_to_dict(report), indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return out_path


def load_json_report(path: PathLike) -> Dict[str, Any]:
    """Load a previously generated audit JSON (used by Agent 2)."""
    in_path = Path(path)
    if not in_path.is_file():
        raise FileNotFoundError(f"Audit JSON not found: {in_path}")
    with in_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{in_path}: audit JSON must contain an object")
    return data
