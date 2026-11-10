"""Review checklist definition and population.

The checklist template is described in YAML (sheet, cell, question, rule ids).
Questions without rules are reported as MANUAL_REVIEW - the framework never
guesses an answer it cannot evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

import yaml

from .domain.findings import ChecklistResult, Finding, Status, aggregate_status

PathLike = Union[str, Path]

#: Evidence lines are truncated so the Excel cell stays readable.
MAX_EVIDENCE_LINES = 6
MAX_CELL_LENGTH = 1500

#: Affected objects listed in full before the remainder is summarised.
MAX_LOCATIONS = 12


class ChecklistError(Exception):
    """Raised when a checklist definition cannot be loaded."""


@dataclass(frozen=True)
class ChecklistItem:
    item_id: str
    sheet: str
    cell: str
    question: str
    section: Optional[str] = None
    rule_ids: List[str] = field(default_factory=list)
    manual_reason: str = ""
    residual: str = ""

    @property
    def row(self) -> int:
        digits = "".join(ch for ch in self.cell if ch.isdigit())
        if not digits:
            raise ChecklistError(f"Checklist item {self.item_id} has an invalid cell '{self.cell}'")
        return int(digits)


@dataclass
class ChecklistDefinition:
    name: str
    items: List[ChecklistItem] = field(default_factory=list)
    answer_column: str = "C"
    comment_column: str = "D"
    version: str = "unversioned"
    source_path: Optional[str] = None

    @property
    def rule_ids(self) -> List[str]:
        out: List[str] = []
        for item in self.items:
            for rule_id in item.rule_ids:
                if rule_id not in out:
                    out.append(rule_id)
        return out

    def sheets(self) -> List[str]:
        seen: List[str] = []
        for item in self.items:
            if item.sheet not in seen:
                seen.append(item.sheet)
        return seen


def load_checklist(path: PathLike) -> ChecklistDefinition:
    """Load a checklist definition from a YAML file or a directory of them."""
    target = Path(path)
    if target.is_dir():
        return load_checklist_directory(target)
    return load_checklist_file(target)


def load_checklist_directory(path: PathLike, *, pattern: str = "*.y*ml") -> ChecklistDefinition:
    """Load and merge every checklist YAML in a directory (sorted by name)."""
    directory = Path(path)
    files = sorted(p for p in directory.glob(pattern) if p.is_file())
    if not files:
        raise ChecklistError(f"No checklist files matching '{pattern}' in {directory}")

    merged: List[ChecklistItem] = []
    names: List[str] = []
    seen: Dict[str, str] = {}
    first: Optional[ChecklistDefinition] = None

    for file_path in files:
        definition = load_checklist_file(file_path)
        first = first or definition
        for item in definition.items:
            if item.item_id in seen:
                raise ChecklistError(
                    f"Duplicate checklist item id '{item.item_id}' in {file_path} "
                    f"(already defined in {seen[item.item_id]})"
                )
            seen[item.item_id] = str(file_path)
        merged.extend(definition.items)
        names.append(definition.name)

    return ChecklistDefinition(
        name=" + ".join(names),
        items=merged,
        answer_column=first.answer_column if first else "C",
        comment_column=first.comment_column if first else "D",
        version=first.version if first else "unversioned",
        source_path=str(directory),
    )


def load_checklist_file(path: PathLike) -> ChecklistDefinition:
    """Load a checklist definition from one YAML file."""
    file_path = Path(path)
    if not file_path.is_file():
        raise ChecklistError(f"Checklist definition not found: {file_path}")
    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ChecklistError(f"Invalid YAML in {file_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ChecklistError(f"{file_path}: top level must be a mapping")

    sheets = data.get("sheets")
    if not isinstance(sheets, list) or not sheets:
        raise ChecklistError(f"{file_path}: 'sheets' must be a non-empty list")

    items: List[ChecklistItem] = []
    seen_ids: set = set()
    for sheet_entry in sheets:
        if not isinstance(sheet_entry, dict):
            raise ChecklistError(f"{file_path}: each sheet entry must be a mapping")
        sheet_name = sheet_entry.get("sheet")
        if not sheet_name:
            raise ChecklistError(f"{file_path}: each sheet entry requires a 'sheet' name")
        for raw in sheet_entry.get("items") or []:
            if not isinstance(raw, dict):
                raise ChecklistError(f"{file_path}: each checklist item must be a mapping")
            item_id = raw.get("id")
            question = raw.get("question")
            cell = raw.get("cell")
            if not item_id or not question or not cell:
                raise ChecklistError(
                    f"{file_path}: checklist items require 'id', 'question' and 'cell'"
                )
            if item_id in seen_ids:
                raise ChecklistError(f"{file_path}: duplicate checklist item id '{item_id}'")
            seen_ids.add(item_id)
            rule_ids = raw.get("rules") or []
            if not isinstance(rule_ids, list):
                raise ChecklistError(f"{file_path}: '{item_id}' rules must be a list")
            items.append(
                ChecklistItem(
                    item_id=str(item_id),
                    sheet=str(sheet_name),
                    cell=str(cell),
                    question=str(question),
                    section=raw.get("section"),
                    rule_ids=[str(r) for r in rule_ids],
                    manual_reason=str(raw.get("manual_reason", "") or ""),
                    residual=" ".join(str(raw.get("residual", "") or "").split()),
                )
            )

    return ChecklistDefinition(
        name=str(data.get("name", file_path.stem)),
        items=items,
        answer_column=str(data.get("answer_column", "C")),
        comment_column=str(data.get("comment_column", "D")),
        version=str(data.get("version", "unversioned")),
        source_path=str(file_path),
    )


def _truncate(text: str, limit: int = MAX_CELL_LENGTH) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _format_recommendation(failing: Sequence[Finding], residual: str = "") -> str:
    """Advice stated once, followed by the objects it applies to.

    A reviewer needs to know *where* to act. Findings are grouped by the advice
    they share, and each group lists the affected objects qualified by the
    dashboard that owns them, so a question answered N on a multi-dashboard
    workbook points at the exact place to fix.
    """
    grouped: Dict[str, List[str]] = {}
    for finding in failing:
        advice = " ".join((finding.recommendation or finding.title).split())
        where = finding.where
        locations = grouped.setdefault(advice, [])
        if where not in locations:
            locations.append(where)

    blocks: List[str] = []
    for advice, locations in grouped.items():
        shown = locations[:MAX_LOCATIONS]
        listed = "; ".join(shown)
        if len(locations) > MAX_LOCATIONS:
            listed += f"; and {len(locations) - MAX_LOCATIONS} more"
        blocks.append(f"{advice}\nAffected ({len(locations)}): {listed}")

    if residual:
        blocks.append(f"Residual manual check: {residual}")
    return "\n\n".join(blocks)


def build_checklist_results(
    definition: ChecklistDefinition,
    findings: Sequence[Finding],
    *,
    evaluated_rule_ids: Optional[Iterable[str]] = None,
) -> List[ChecklistResult]:
    """Answer every checklist question from the automated findings."""
    by_rule: Dict[str, List[Finding]] = {}
    for finding in findings:
        by_rule.setdefault(finding.rule_id, []).append(finding)
    evaluated = set(evaluated_rule_ids) if evaluated_rule_ids is not None else set(by_rule)

    results: List[ChecklistResult] = []
    for item in definition.items:
        related: List[Finding] = []
        missing_rules: List[str] = []
        for rule_id in item.rule_ids:
            if rule_id in by_rule:
                related.extend(by_rule[rule_id])
            elif rule_id not in evaluated:
                missing_rules.append(rule_id)

        if not item.rule_ids:
            results.append(
                ChecklistResult(
                    item_id=item.item_id,
                    section=item.section,
                    question=item.question,
                    status=Status.MANUAL_REVIEW,
                    sheet=item.sheet,
                    cell=item.cell,
                    rule_ids=[],
                    recommendation=item.manual_reason
                    or "No automated rule covers this question; manual review required.",
                    evidence_summary="Not machine-verifiable from workbook XML.",
                    automated=False,
                )
            )
            continue

        if missing_rules or not related:
            results.append(
                ChecklistResult(
                    item_id=item.item_id,
                    section=item.section,
                    question=item.question,
                    status=Status.MANUAL_REVIEW,
                    sheet=item.sheet,
                    cell=item.cell,
                    rule_ids=item.rule_ids,
                    recommendation=(
                        "Rules "
                        + ", ".join(missing_rules or item.rule_ids)
                        + " were not evaluated in this run; manual review required."
                    ),
                    evidence_summary="No automated findings available.",
                    automated=False,
                )
            )
            continue

        status = aggregate_status([f.status for f in related])
        failing = [f for f in related if f.status in (Status.FAIL, Status.MANUAL_REVIEW)]
        evidence_lines: List[str] = []
        for finding in failing[:MAX_EVIDENCE_LINES]:
            for evidence in finding.evidence:
                if evidence.note == "context":
                    continue
                evidence_lines.append(
                    f"[{finding.rule_id}] {finding.target_name or finding.target_id}: "
                    f"{evidence.summary()} ({evidence.source.xpath if evidence.source else 'n/a'})"
                )
                break
        recommendation = _format_recommendation(failing, item.residual)

        results.append(
            ChecklistResult(
                item_id=item.item_id,
                section=item.section,
                question=item.question,
                status=status,
                sheet=item.sheet,
                cell=item.cell,
                rule_ids=item.rule_ids,
                recommendation=_truncate(recommendation),
                evidence_summary=_truncate("\n".join(evidence_lines)),
                automated=True,
            )
        )
    return results


def checklist_metadata(definition: ChecklistDefinition) -> Dict[str, Any]:
    return {
        "name": definition.name,
        "version": definition.version,
        "source": definition.source_path,
        "item_count": len(definition.items),
        "automated_item_count": len([i for i in definition.items if i.rule_ids]),
    }
