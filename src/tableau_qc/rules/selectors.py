"""Scope selectors and field resolution over the normalised model.

A *selector* maps a workbook to the list of objects a rule applies to. Field
paths are resolved generically, so new rules usually need no Python change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional

from ..domain.models import SourceRef, Workbook

#: Marker for "this value could not be observed in the XML".
UNRESOLVED = object()


@dataclass(frozen=True)
class Target:
    """An object a rule is evaluated against."""

    object_type: str
    object_id: str
    name: Optional[str]
    obj: Any


@dataclass(frozen=True)
class Resolution:
    """Outcome of resolving a dotted field path on a target object."""

    present: bool
    value: Any = None
    source: Optional[SourceRef] = None
    error: Optional[str] = None


def resolve_field(obj: Any, path: str) -> Resolution:
    """Resolve a dotted ``path`` (e.g. ``size.width``) on ``obj``.

    The most specific ``SourceRef`` found along the path is returned so that
    every piece of evidence points at the exact XML location.
    """
    current = obj
    source = _source_of(obj)
    for part in path.split("."):
        if current is None:
            return Resolution(present=False, value=None, source=source)
        try:
            if isinstance(current, Mapping):
                if part not in current:
                    return Resolution(present=False, source=source, error=f"no key '{part}'")
                current = current[part]
            elif hasattr(current, part):
                current = getattr(current, part)
            else:
                return Resolution(present=False, source=source, error=f"no attribute '{part}'")
        except Exception as exc:  # pragma: no cover - defensive
            return Resolution(present=False, source=source, error=str(exc))
        found = _source_of(current)
        if found is not None:
            source = found
    return Resolution(present=current is not None, value=current, source=source)


def _source_of(obj: Any) -> Optional[SourceRef]:
    source = getattr(obj, "source", None)
    return source if isinstance(source, SourceRef) else None


# -- selectors -------------------------------------------------------------
def _workbook(workbook: Workbook) -> List[Target]:
    return [Target("workbook", workbook.object_id, workbook.name, workbook)]


def _dashboards(workbook: Workbook) -> List[Target]:
    return [Target("dashboard", d.object_id, d.name, d) for d in workbook.dashboards]


def _dashboard_zones(workbook: Workbook) -> List[Target]:
    return [
        Target("dashboard_zone", z.object_id, z.display_name, z) for z in workbook.all_zones
    ]


def _dashboard_view_zones(workbook: Workbook) -> List[Target]:
    return [
        Target("dashboard_view_zone", z.object_id, z.display_name, z)
        for z in workbook.all_zones
        if z.is_view
    ]


def _dashboard_filter_zones(workbook: Workbook) -> List[Target]:
    return [
        Target("dashboard_filter_zone", z.object_id, z.display_name, z)
        for z in workbook.all_zones
        if z.is_filter
    ]


def _worksheets(workbook: Workbook) -> List[Target]:
    return [Target("worksheet", w.object_id, w.name, w) for w in workbook.worksheets]


def _used_worksheets(workbook: Workbook) -> List[Target]:
    return [Target("worksheet", w.object_id, w.name, w) for w in workbook.worksheets if w.is_used]


def _datasources(workbook: Workbook) -> List[Target]:
    return [Target("datasource", d.object_id, d.name, d) for d in workbook.datasources]


def _calculated_fields(workbook: Workbook) -> List[Target]:
    return [
        Target("calculated_field", c.object_id, c.display_name, c)
        for c in workbook.calculated_fields
        if not c.is_parameter
    ]


def _actions(workbook: Workbook) -> List[Target]:
    return [Target("action", a.object_id, a.caption or a.name, a) for a in workbook.actions]


def _worksheet_filters(workbook: Workbook) -> List[Target]:
    return [Target("worksheet_filter", f.object_id, f.column, f) for f in workbook.filters]


def _mark_palettes(workbook: Workbook) -> List[Target]:
    return [
        Target("mark_palette", p.object_id, p.palette_name or p.field_name, p)
        for p in workbook.palettes
    ]


def _dashboard_images(workbook: Workbook) -> List[Target]:
    targets: List[Target] = []
    for dashboard in workbook.dashboards:
        for image in dashboard.images:
            targets.append(Target("dashboard_image", image.object_id, image.file_name, image))
    return targets


def _multi_select_filter_zones(workbook: Workbook) -> List[Target]:
    return [
        Target("multi_select_filter_zone", z.object_id, z.display_name, z)
        for z in workbook.all_zones
        if z.is_multi_select_filter
    ]


SELECTORS: Dict[str, Callable[[Workbook], List[Target]]] = {
    "workbook": _workbook,
    "dashboard": _dashboards,
    "dashboard_zone": _dashboard_zones,
    "dashboard_view_zone": _dashboard_view_zones,
    "dashboard_filter_zone": _dashboard_filter_zones,
    "multi_select_filter_zone": _multi_select_filter_zones,
    "dashboard_image": _dashboard_images,
    "mark_palette": _mark_palettes,
    "worksheet": _worksheets,
    "used_worksheet": _used_worksheets,
    "datasource": _datasources,
    "calculated_field": _calculated_fields,
    "action": _actions,
    "worksheet_filter": _worksheet_filters,
}


def selector_names() -> List[str]:
    return sorted(SELECTORS)


def get_selector(scope: str) -> Callable[[Workbook], List[Target]]:
    try:
        return SELECTORS[scope]
    except KeyError as exc:
        raise KeyError(
            f"Unknown rule scope '{scope}'. Available: {', '.join(selector_names())}"
        ) from exc
