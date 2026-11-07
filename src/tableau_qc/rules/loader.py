"""YAML rule repository loader."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

import yaml

from .schema import RuleDefinition, RuleSchemaError, parse_rule
from .validation import validate_repository

PathLike = Union[str, Path]


class RuleRepositoryError(Exception):
    """Raised when a rule repository cannot be loaded."""


@dataclass
class RuleRepository:
    """An immutable, validated collection of rules."""

    rules: List[RuleDefinition] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    versions: Dict[str, str] = field(default_factory=dict)
    checksum: Optional[str] = None

    def __post_init__(self) -> None:
        self._by_id = {rule.id: rule for rule in self.rules}

    def __len__(self) -> int:
        return len(self.rules)

    def __iter__(self):
        return iter(self.rules)

    @property
    def enabled_rules(self) -> List[RuleDefinition]:
        return [r for r in self.rules if r.enabled]

    @property
    def rule_ids(self) -> List[str]:
        return [r.id for r in self.rules]

    def by_id(self, rule_id: str) -> Optional[RuleDefinition]:
        return self._by_id.get(rule_id)

    def filtered(
        self,
        *,
        rule_ids: Optional[Sequence[str]] = None,
        categories: Optional[Sequence[str]] = None,
        tags: Optional[Sequence[str]] = None,
    ) -> "RuleRepository":
        rules = self.enabled_rules
        if rule_ids:
            wanted = set(rule_ids)
            rules = [r for r in rules if r.id in wanted]
        if categories:
            wanted = {c.lower() for c in categories}
            rules = [r for r in rules if r.category.lower() in wanted]
        if tags:
            wanted = {t.lower() for t in tags}
            rules = [r for r in rules if wanted & {t.lower() for t in r.tags}]
        return RuleRepository(
            rules=rules, sources=self.sources, versions=self.versions, checksum=self.checksum
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rule_count": len(self.rules),
            "rule_ids": self.rule_ids,
            "sources": self.sources,
            "versions": self.versions,
            "checksum": self.checksum,
        }


def _load_yaml(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise RuleRepositoryError(f"Invalid YAML in {path}: {exc}") from exc


def load_rule_file(path: PathLike) -> RuleRepository:
    """Load a single YAML rule file."""
    file_path = Path(path)
    if not file_path.is_file():
        raise RuleRepositoryError(f"Rule file not found: {file_path}")

    data = _load_yaml(file_path)
    if not isinstance(data, dict):
        raise RuleRepositoryError(f"{file_path}: top level must be a mapping")
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise RuleRepositoryError(f"{file_path}: 'rules' must be a non-empty list")

    rules: List[RuleDefinition] = []
    for entry in raw_rules:
        try:
            rules.append(parse_rule(entry, source_file=str(file_path)))
        except RuleSchemaError as exc:
            raise RuleRepositoryError(f"{file_path}: {exc}") from exc

    problems = validate_repository(rules)
    if problems:
        raise RuleRepositoryError(f"{file_path}: " + "; ".join(problems))

    version = str(data.get("version", "unversioned"))
    checksum = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return RuleRepository(
        rules=rules,
        sources=[str(file_path)],
        versions={file_path.name: version},
        checksum=checksum,
    )


def load_rule_directory(path: PathLike, *, pattern: str = "*.y*ml") -> RuleRepository:
    """Load and merge every YAML rule file in a directory (sorted by name)."""
    directory = Path(path)
    if not directory.is_dir():
        raise RuleRepositoryError(f"Rule directory not found: {directory}")

    files = sorted(p for p in directory.glob(pattern) if p.is_file())
    if not files:
        raise RuleRepositoryError(f"No rule files matching '{pattern}' in {directory}")

    rules: List[RuleDefinition] = []
    sources: List[str] = []
    versions: Dict[str, str] = {}
    digest = hashlib.sha256()
    seen: Dict[str, str] = {}

    for file_path in files:
        repo = load_rule_file(file_path)
        for rule in repo.rules:
            if rule.id in seen:
                raise RuleRepositoryError(
                    f"Duplicate rule id '{rule.id}' in {file_path} (already defined in {seen[rule.id]})"
                )
            seen[rule.id] = str(file_path)
        rules.extend(repo.rules)
        sources.extend(repo.sources)
        versions.update(repo.versions)
        digest.update(file_path.read_bytes())

    return RuleRepository(
        rules=rules, sources=sources, versions=versions, checksum=digest.hexdigest()
    )


def load_rules(path: PathLike) -> RuleRepository:
    """Load rules from either a YAML file or a directory of YAML files."""
    target = Path(path)
    if target.is_dir():
        return load_rule_directory(target)
    return load_rule_file(target)


__all__: Iterable[str] = (
    "RuleRepository",
    "RuleRepositoryError",
    "load_rule_directory",
    "load_rule_file",
    "load_rules",
)
