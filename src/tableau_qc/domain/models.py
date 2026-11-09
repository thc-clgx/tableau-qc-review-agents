"""Normalised, XML-independent representation of a Tableau workbook.

The rule engine only ever operates on the objects declared in this module.
No XPath or XML knowledge is allowed beyond the ``SourceRef`` evidence pointer
that parsers attach to every object.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence

#: Sentinel used by the rule engine when a value could not be observed.
MISSING = object()


@dataclass(frozen=True)
class SourceRef:
    """Pointer back into the source XML, used as evidence."""

    xpath: str
    attribute: Optional[str] = None

    def with_attribute(self, attribute: Optional[str]) -> "SourceRef":
        return SourceRef(xpath=self.xpath, attribute=attribute)

    def as_dict(self) -> Dict[str, Any]:
        return {"xpath": self.xpath, "attribute": self.attribute}

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.xpath}@{self.attribute}" if self.attribute else self.xpath


@dataclass(frozen=True)
class FormatDeclaration:
    """A single ``<format attr=... value=.../>`` declaration."""

    attr: str
    value: Optional[str]
    source: SourceRef
    element: Optional[str] = None
    owner_type: str = "workbook"
    owner_id: Optional[str] = None

    @property
    def numeric_value(self) -> Optional[float]:
        if self.value is None:
            return None
        try:
            return float(self.value)
        except (TypeError, ValueError):
            return None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "attr": self.attr,
            "value": self.value,
            "element": self.element,
            "owner_type": self.owner_type,
            "owner_id": self.owner_id,
            "source": self.source.as_dict(),
        }


@dataclass(frozen=True)
class Padding:
    """Padding/margin values in pixels, per side.

    ``None`` means *not declared in the XML*; it is never defaulted, because the
    framework must not infer unavailable information.
    """

    top: Optional[float] = None
    right: Optional[float] = None
    bottom: Optional[float] = None
    left: Optional[float] = None
    source: Optional[SourceRef] = None

    @property
    def values(self) -> List[float]:
        return [v for v in (self.top, self.right, self.bottom, self.left) if v is not None]

    @property
    def is_declared(self) -> bool:
        return bool(self.values)

    @property
    def minimum(self) -> Optional[float]:
        return min(self.values) if self.values else None

    @property
    def maximum(self) -> Optional[float]:
        return max(self.values) if self.values else None

    @property
    def declared_sides(self) -> List[str]:
        return [
            name
            for name, value in (
                ("top", self.top),
                ("right", self.right),
                ("bottom", self.bottom),
                ("left", self.left),
            )
            if value is not None
        ]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "left": self.left,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


@dataclass(frozen=True)
class DashboardSize:
    """Dashboard sizing information as declared by ``<size .../>``."""

    min_width: Optional[int] = None
    max_width: Optional[int] = None
    min_height: Optional[int] = None
    max_height: Optional[int] = None
    sizing_mode: Optional[str] = None
    source: Optional[SourceRef] = None

    @property
    def width(self) -> Optional[int]:
        if self.min_width is not None and self.min_width == self.max_width:
            return self.min_width
        return self.max_width if self.min_width is None else None

    @property
    def height(self) -> Optional[int]:
        if self.min_height is not None and self.min_height == self.max_height:
            return self.min_height
        return self.max_height if self.min_height is None else None

    @property
    def is_fixed(self) -> Optional[bool]:
        if self.sizing_mode is not None:
            return self.sizing_mode == "fixed"
        if None in (self.min_width, self.max_width, self.min_height, self.max_height):
            return None
        return self.min_width == self.max_width and self.min_height == self.max_height

    def as_dict(self) -> Dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "min_width": self.min_width,
            "max_width": self.max_width,
            "min_height": self.min_height,
            "max_height": self.max_height,
            "sizing_mode": self.sizing_mode,
            "is_fixed": self.is_fixed,
        }


#: Zone ``type-v2`` values that are structural containers rather than content.
LAYOUT_ZONE_TYPES = frozenset({"layout-basic", "layout-flow"})

#: Zone ``type-v2`` values that are dashboard objects but not worksheet views.
NON_VIEW_ZONE_TYPES = frozenset(
    {
        "filter",
        "paramctrl",
        "color",
        "size",
        "shape",
        "measure",
        "bitmap",
        "text",
        "web",
        "blank",
        "empty",
        "title",
        "legend",
        "page",
        "highlighter",
        "navigation",
        "download",
        "extension",
    }
)


@dataclass
class DashboardZone:
    """A single dashboard zone (container, view, filter, legend, text, ...)."""

    zone_id: str
    name: Optional[str]
    zone_type: Optional[str]
    x: Optional[int] = None
    y: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    is_floating: bool = False
    is_fixed_size: bool = False
    show_title: Optional[bool] = None
    param: Optional[str] = None
    filter_mode: Optional[str] = None
    show_apply: Optional[bool] = None
    filter_values_source: Optional[str] = None
    outer_padding: Padding = field(default_factory=Padding)
    inner_padding: Padding = field(default_factory=Padding)
    formats: List[FormatDeclaration] = field(default_factory=list)
    children: List["DashboardZone"] = field(default_factory=list)
    dashboard_name: Optional[str] = None
    references_worksheet: bool = False
    source: Optional[SourceRef] = None

    @property
    def is_layout_container(self) -> bool:
        return self.zone_type in LAYOUT_ZONE_TYPES

    @property
    def is_view(self) -> bool:
        """True when the zone embeds a worksheet view.

        Tableau omits ``type-v2`` for worksheet zones; every other named zone
        carries an explicit object type (filter, legend, text, image, ...).
        """
        if self.name is None:
            return False
        if self.zone_type is None:
            return True
        return self.zone_type not in LAYOUT_ZONE_TYPES and self.zone_type not in NON_VIEW_ZONE_TYPES

    @property
    def is_filter(self) -> bool:
        return self.zone_type == "filter"

    @property
    def is_multi_select_filter(self) -> bool:
        """Filter modes that let the user pick several values at once."""
        return self.is_filter and self.filter_mode in {
            "checkdropdown",
            "checklist",
            "multi-select",
            "multivalue-list",
        }

    @property
    def has_apply_button(self) -> Optional[bool]:
        if not self.is_multi_select_filter:
            return None
        return bool(self.show_apply)

    @property
    def is_high_cardinality_control(self) -> Optional[bool]:
        """Enumerated-list controls are the ones that render poorly at scale."""
        if not self.is_filter:
            return None
        return self.filter_mode in {"checkdropdown", "checklist", "multivalue-list"}

    @property
    def object_id(self) -> str:
        return f"{self.dashboard_name}:zone-{self.zone_id}"

    @property
    def display_name(self) -> str:
        return self.name or f"zone {self.zone_id} ({self.zone_type or 'view'})"

    def walk(self) -> Iterator["DashboardZone"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "name": self.name,
            "zone_type": self.zone_type,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "is_floating": self.is_floating,
            "is_view": self.is_view,
            "is_filter": self.is_filter,
            "references_worksheet": self.references_worksheet,
            "outer_padding": self.outer_padding.as_dict(),
            "inner_padding": self.inner_padding.as_dict(),
            "dashboard_name": self.dashboard_name,
            "source": self.source.as_dict() if self.source else None,
        }


@dataclass
class Dashboard:
    name: str
    size: DashboardSize = field(default_factory=DashboardSize)
    zones: List[DashboardZone] = field(default_factory=list)
    formats: List[FormatDeclaration] = field(default_factory=list)
    datasource_dependencies: List[str] = field(default_factory=list)
    has_device_layouts: bool = False
    images: List[ImageObject] = field(default_factory=list)
    texts: List[TextContent] = field(default_factory=list)
    source: Optional[SourceRef] = None

    @property
    def object_id(self) -> str:
        return self.name

    @property
    def all_zones(self) -> List[DashboardZone]:
        out: List[DashboardZone] = []
        for zone in self.zones:
            out.extend(zone.walk())
        return out

    @property
    def view_zones(self) -> List[DashboardZone]:
        return [z for z in self.all_zones if z.is_view]

    @property
    def view_count(self) -> int:
        return len(self.view_zones)

    @property
    def worksheet_names(self) -> List[str]:
        seen: List[str] = []
        for zone in self.view_zones:
            if zone.name and zone.name not in seen:
                seen.append(zone.name)
        return seen

    @property
    def distinct_view_count(self) -> int:
        return len(self.worksheet_names)

    @property
    def filter_zones(self) -> List[DashboardZone]:
        return [z for z in self.all_zones if z.is_filter]

    @property
    def filter_count(self) -> int:
        return len(self.filter_zones)

    @property
    def floating_zone_count(self) -> int:
        return len([z for z in self.all_zones if z.is_floating])

    @property
    def font_families(self) -> List[str]:
        return sorted({f.value for f in self.formats if f.attr == "font-family" and f.value})

    # -- structure --------------------------------------------------------
    @property
    def tiled_zone_count(self) -> int:
        return len([z for z in self.all_zones if not z.is_floating and not z.is_layout_container])

    @property
    def floating_ratio(self) -> Optional[float]:
        total = self.floating_zone_count + self.tiled_zone_count
        return self.floating_zone_count / total if total else None

    @property
    def multi_select_filters(self) -> List[DashboardZone]:
        return [z for z in self.all_zones if z.is_multi_select_filter]

    @property
    def filters_missing_apply_button(self) -> List[str]:
        return [z.display_name for z in self.multi_select_filters if not z.show_apply]

    @property
    def missing_apply_button_count(self) -> int:
        return len(self.filters_missing_apply_button)

    @property
    def image_file_names(self) -> List[str]:
        return [i.file_name for i in self.images if i.file_name]

    @property
    def has_upper_left_image(self) -> bool:
        return any(i.is_upper_left for i in self.images)

    @property
    def placeholder_image_names(self) -> List[str]:
        """Image assets still carrying a placeholder file name."""
        from ..standards import standards

        pattern = standards().placeholder_image_regex
        return [i.file_name for i in self.images if i.file_name and pattern.search(i.file_name)]

    @property
    def placeholder_image_count(self) -> int:
        return len(self.placeholder_image_names)

    @property
    def text_content(self) -> str:
        return " ".join(t.text for t in self.texts)

    # -- layout ordering (top-to-bottom, left-to-right) -------------------
    @property
    def views_in_reading_order(self) -> List[str]:
        ordered = sorted(
            (z for z in self.view_zones if z.x is not None and z.y is not None),
            key=lambda z: (z.y or 0, z.x or 0),
        )
        return [z.display_name for z in ordered]

    @property
    def largest_view_is_not_first(self) -> Optional[bool]:
        """Heuristic: the biggest view should not sit at the very top.

        Summary KPIs belong above granular detail; a dashboard whose largest
        zone is also its topmost one usually inverts that hierarchy. Returns
        ``None`` when every view is the same size, because then there is no
        hierarchy to judge.
        """
        sized = [z for z in self.view_zones if None not in (z.x, z.y, z.width, z.height)]
        if len(sized) < 2:
            return None
        areas = {(z.width or 0) * (z.height or 0) for z in sized}
        if len(areas) == 1:
            return None
        topmost = min(sized, key=lambda z: (z.y or 0, z.x or 0))
        largest = max(sized, key=lambda z: (z.width or 0) * (z.height or 0))
        return topmost is largest

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "size": self.size.as_dict(),
            "view_count": self.view_count,
            "distinct_view_count": self.distinct_view_count,
            "filter_count": self.filter_count,
            "floating_zone_count": self.floating_zone_count,
            "tiled_zone_count": self.tiled_zone_count,
            "missing_apply_button_count": self.missing_apply_button_count,
            "filters_missing_apply_button": self.filters_missing_apply_button,
            "worksheet_names": self.worksheet_names,
            "views_in_reading_order": self.views_in_reading_order,
            "image_file_names": self.image_file_names,
            "has_upper_left_image": self.has_upper_left_image,
            "zone_count": len(self.all_zones),
            "source": self.source.as_dict() if self.source else None,
        }


@dataclass
class Worksheet:
    name: str
    is_visible: Optional[bool] = None
    datasource_dependencies: List[str] = field(default_factory=list)
    mark_classes: List[str] = field(default_factory=list)
    filters: List["WorksheetFilter"] = field(default_factory=list)
    formats: List[FormatDeclaration] = field(default_factory=list)
    has_title: Optional[bool] = None
    used_in_dashboards: List[str] = field(default_factory=list)
    palettes: List[MarkPalette] = field(default_factory=list)
    texts: List[TextContent] = field(default_factory=list)
    source: Optional[SourceRef] = None

    @property
    def object_id(self) -> str:
        return self.name

    @property
    def is_used(self) -> bool:
        return bool(self.used_in_dashboards)

    @property
    def filter_count(self) -> int:
        return len(self.filters)

    @property
    def font_families(self) -> List[str]:
        return sorted({f.value for f in self.formats if f.attr == "font-family" and f.value})

    # -- colour -----------------------------------------------------------
    @property
    def built_in_palettes(self) -> List[str]:
        from ..parsers.colour_parser import ColourParser

        return sorted(
            {
                p.palette_name
                for p in self.palettes
                if p.palette_name and ColourParser.is_built_in_palette(p.palette_name)
            }
        )

    @property
    def uses_built_in_palette(self) -> bool:
        return bool(self.built_in_palettes)

    @property
    def mark_colours(self) -> List[str]:
        values: set = set()
        for palette in self.palettes:
            values.update(palette.colour_values)
        return sorted(values)

    @property
    def max_colours_in_a_view(self) -> int:
        return max((p.distinct_colour_count for p in self.palettes), default=0)

    @property
    def combines_red_and_green(self) -> bool:
        return any(p.combines_red_and_green for p in self.palettes)

    # -- text -------------------------------------------------------------
    @property
    def tooltip_texts(self) -> List[str]:
        return [t.text for t in self.texts if t.category == "tooltip"]

    @property
    def shows_mark_labels(self) -> bool:
        return any(
            f.attr == "mark-labels-show" and (f.value or "").lower() == "true"
            for f in self.formats
        )

    @property
    def shows_field_labels(self) -> bool:
        return any(
            f.attr == "display-field-labels" and (f.value or "").lower() == "true"
            for f in self.formats
        )

    @property
    def shows_labels_and_axes(self) -> bool:
        """True when a view both labels marks and displays axis field labels."""
        return self.shows_mark_labels and self.shows_field_labels

    @property
    def all_text(self) -> str:
        return " ".join(t.text for t in self.texts)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "is_visible": self.is_visible,
            "is_used": self.is_used,
            "used_in_dashboards": self.used_in_dashboards,
            "datasource_dependencies": self.datasource_dependencies,
            "mark_classes": self.mark_classes,
            "filter_count": self.filter_count,
            "font_families": self.font_families,
            "built_in_palettes": self.built_in_palettes,
            "mark_colours": self.mark_colours,
            "max_colours_in_a_view": self.max_colours_in_a_view,
            "combines_red_and_green": self.combines_red_and_green,
            "source": self.source.as_dict() if self.source else None,
        }


@dataclass
class WorksheetFilter:
    column: Optional[str]
    filter_class: Optional[str]
    worksheet_name: Optional[str] = None
    datasource: Optional[str] = None
    source: Optional[SourceRef] = None

    @property
    def object_id(self) -> str:
        return f"{self.worksheet_name}:{self.column}"

    @property
    def field_name(self) -> Optional[str]:
        """``[DS].[none:Model Name:nk]`` -> ``Model Name``."""
        if not self.column:
            return None
        tail = self.column.rsplit("].[", 1)[-1].rstrip("]")
        parts = tail.split(":")
        return parts[1] if len(parts) >= 3 else tail

    def as_dict(self) -> Dict[str, Any]:
        return {
            "column": self.column,
            "field_name": self.field_name,
            "filter_class": self.filter_class,
            "worksheet_name": self.worksheet_name,
            "datasource": self.datasource,
            "source": self.source.as_dict() if self.source else None,
        }


@dataclass
class CalculatedField:
    name: str
    caption: Optional[str]
    formula: Optional[str]
    datasource: Optional[str] = None
    datatype: Optional[str] = None
    role: Optional[str] = None
    is_parameter: bool = False
    source: Optional[SourceRef] = None

    @property
    def object_id(self) -> str:
        return f"{self.datasource}:{self.name}"

    @property
    def display_name(self) -> str:
        return self.caption or self.name

    @property
    def formula_length(self) -> int:
        return len(self.formula or "")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "caption": self.caption,
            "formula": self.formula,
            "datasource": self.datasource,
            "datatype": self.datatype,
            "role": self.role,
            "is_parameter": self.is_parameter,
            "source": self.source.as_dict() if self.source else None,
        }


@dataclass
class DataSourceConnection:
    connection_class: Optional[str]
    dbname: Optional[str] = None
    server: Optional[str] = None
    username: Optional[str] = None
    has_custom_sql: bool = False
    source: Optional[SourceRef] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "connection_class": self.connection_class,
            "dbname": self.dbname,
            "server": self.server,
            "username": self.username,
            "has_custom_sql": self.has_custom_sql,
            "source": self.source.as_dict() if self.source else None,
        }


@dataclass
class DataSource:
    name: str
    caption: Optional[str] = None
    is_inline: Optional[bool] = None
    has_connection: Optional[bool] = None
    is_parameters: bool = False
    has_extract: bool = False
    connections: List[DataSourceConnection] = field(default_factory=list)
    calculated_fields: List[CalculatedField] = field(default_factory=list)
    column_count: int = 0
    source: Optional[SourceRef] = None

    @property
    def object_id(self) -> str:
        return self.name

    @property
    def uses_custom_sql(self) -> bool:
        return any(c.has_custom_sql for c in self.connections)

    @property
    def connection_classes(self) -> List[str]:
        return sorted({c.connection_class for c in self.connections if c.connection_class})

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "caption": self.caption,
            "is_inline": self.is_inline,
            "has_connection": self.has_connection,
            "is_parameters": self.is_parameters,
            "has_extract": self.has_extract,
            "connection_classes": self.connection_classes,
            "uses_custom_sql": self.uses_custom_sql,
            "calculated_field_count": len(self.calculated_fields),
            "column_count": self.column_count,
            "source": self.source.as_dict() if self.source else None,
        }


@dataclass
class DashboardAction:
    name: str
    caption: Optional[str]
    action_type: str
    source_sheets: List[str] = field(default_factory=list)
    target_sheets: List[str] = field(default_factory=list)
    run_mode: Optional[str] = None
    source: Optional[SourceRef] = None

    @property
    def object_id(self) -> str:
        return self.name

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "caption": self.caption,
            "action_type": self.action_type,
            "source_sheets": self.source_sheets,
            "target_sheets": self.target_sheets,
            "run_mode": self.run_mode,
            "source": self.source.as_dict() if self.source else None,
        }


@dataclass(frozen=True)
class ColourUsage:
    """One explicit mark-colour assignment."""

    value: str
    member: Optional[str] = None
    worksheet_name: Optional[str] = None
    hue_family: Optional[str] = None
    source: Optional[SourceRef] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "member": self.member,
            "worksheet_name": self.worksheet_name,
            "hue_family": self.hue_family,
            "source": self.source.as_dict() if self.source else None,
        }


@dataclass
class MarkPalette:
    """A colour encoding applied to a worksheet's marks."""

    palette_name: Optional[str]
    field_name: Optional[str] = None
    encoding_type: Optional[str] = None
    worksheet_name: Optional[str] = None
    colours: List[ColourUsage] = field(default_factory=list)
    source: Optional[SourceRef] = None

    @property
    def object_id(self) -> str:
        return f"{self.worksheet_name}:{self.palette_name or self.field_name}"

    @property
    def colour_values(self) -> List[str]:
        return sorted({c.value for c in self.colours})

    @property
    def distinct_colour_count(self) -> int:
        return len(self.colour_values)

    @property
    def hue_families(self) -> List[str]:
        return sorted({c.hue_family for c in self.colours if c.hue_family})

    @property
    def combines_red_and_green(self) -> bool:
        families = set(self.hue_families)
        return {"red", "green"}.issubset(families)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "palette_name": self.palette_name,
            "field_name": self.field_name,
            "worksheet_name": self.worksheet_name,
            "distinct_colour_count": self.distinct_colour_count,
            "colour_values": self.colour_values,
            "hue_families": self.hue_families,
            "combines_red_and_green": self.combines_red_and_green,
            "source": self.source.as_dict() if self.source else None,
        }


@dataclass(frozen=True)
class TextContent:
    """Readable text extracted from titles, tooltips, labels and text objects."""

    text: str
    category: str
    owner_type: str = "worksheet"
    owner_id: Optional[str] = None
    source: Optional[SourceRef] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "category": self.category,
            "owner_type": self.owner_type,
            "owner_id": self.owner_id,
            "source": self.source.as_dict() if self.source else None,
        }


@dataclass
class ImageObject:
    """A dashboard image zone (logo, icon, decorative asset)."""

    zone_id: str
    dashboard_name: Optional[str] = None
    file_name: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    source: Optional[SourceRef] = None

    @property
    def object_id(self) -> str:
        return f"{self.dashboard_name}:image-{self.zone_id}"

    @property
    def is_upper_left(self) -> Optional[bool]:
        """True when the image sits within the configured upper-left tolerance."""
        if self.x is None or self.y is None:
            return None
        from ..standards import standards

        limits = standards()
        return self.x <= limits.logo_max_x and self.y <= limits.logo_max_y

    def as_dict(self) -> Dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "dashboard_name": self.dashboard_name,
            "file_name": self.file_name,
            "x": self.x,
            "y": self.y,
            "is_upper_left": self.is_upper_left,
            "source": self.source.as_dict() if self.source else None,
        }


@dataclass
class WorkbookStyle:
    """All style declarations observed anywhere in the workbook."""

    formats: List[FormatDeclaration] = field(default_factory=list)

    def by_attr(self, attr: str) -> List[FormatDeclaration]:
        return [f for f in self.formats if f.attr == attr]

    @property
    def font_families(self) -> List[str]:
        return sorted({f.value for f in self.by_attr("font-family") if f.value})

    @property
    def font_sizes(self) -> List[float]:
        return sorted({f.numeric_value for f in self.by_attr("font-size") if f.numeric_value is not None})

    @property
    def colors(self) -> List[str]:
        colour_attrs = ("color", "background-color", "border-color", "font-color", "mark-labels-color")
        values = {
            f.value.lower()
            for f in self.formats
            if f.attr in colour_attrs and f.value and f.value.startswith("#")
        }
        return sorted(values)

    @property
    def declared_attrs(self) -> List[str]:
        return sorted({f.attr for f in self.formats})

    # -- chart clutter -----------------------------------------------------
    @property
    def visible_gridline_count(self) -> int:
        """Gridline/rule declarations explicitly switched on."""
        return len(
            [
                f
                for f in self.by_attr("line-visibility")
                if (f.value or "").lower() == "on"
            ]
        )

    @property
    def active_banding_count(self) -> int:
        """Row/column banding left at a non-zero size."""
        return len(
            [
                f
                for f in self.by_attr("band-size")
                if f.numeric_value is not None and f.numeric_value > 0
            ]
        )

    @property
    def chart_clutter_count(self) -> int:
        return self.visible_gridline_count + self.active_banding_count

    # -- text-category analysis -------------------------------------------
    def sizes_for_category(self, category: str) -> List[float]:
        """Distinct font sizes declared for one text category."""
        return sorted(
            {
                f.numeric_value
                for f in self.formats
                if f.attr == "font-size"
                and f.element == category
                and f.numeric_value is not None
            }
        )

    @property
    def text_categories(self) -> List[str]:
        return sorted({f.element for f in self.by_attr("font-size") if f.element})

    @property
    def inconsistent_text_categories(self) -> List[str]:
        """Categories styled with more than one font size."""
        return [c for c in self.text_categories if len(self.sizes_for_category(c)) > 1]

    @property
    def max_sizes_in_one_category(self) -> int:
        counts = [len(self.sizes_for_category(c)) for c in self.text_categories]
        return max(counts) if counts else 0

    @property
    def font_size_category_count(self) -> int:
        """How many distinct sizes the workbook uses overall."""
        return len(self.font_sizes)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "font_families": self.font_families,
            "font_sizes": self.font_sizes,
            "colors": self.colors,
            "format_count": len(self.formats),
            "text_categories": self.text_categories,
            "inconsistent_text_categories": self.inconsistent_text_categories,
        }


@dataclass
class WindowRef:
    name: str
    window_class: Optional[str]
    is_hidden: bool = False
    source: Optional[SourceRef] = None


@dataclass
class OptimizerRule:
    """A Tableau Workbook Optimizer rule suppression."""

    rule_id: str
    is_ignored: bool = False
    source: Optional[SourceRef] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "is_ignored": self.is_ignored,
            "source": self.source.as_dict() if self.source else None,
        }


@dataclass
class Workbook:
    """Root of the normalised model."""

    name: Optional[str] = None
    version: Optional[str] = None
    original_version: Optional[str] = None
    source_build: Optional[str] = None
    source_platform: Optional[str] = None
    repository_location: Dict[str, str] = field(default_factory=dict)
    preferences: Dict[str, str] = field(default_factory=dict)
    datasources: List[DataSource] = field(default_factory=list)
    worksheets: List[Worksheet] = field(default_factory=list)
    dashboards: List[Dashboard] = field(default_factory=list)
    actions: List[DashboardAction] = field(default_factory=list)
    windows: List[WindowRef] = field(default_factory=list)
    style: WorkbookStyle = field(default_factory=WorkbookStyle)
    optimizer_rules: List[OptimizerRule] = field(default_factory=list)
    custom_palettes: List[str] = field(default_factory=list)
    datasource_palettes: List[MarkPalette] = field(default_factory=list)
    source_path: Optional[str] = None
    source_sha256: Optional[str] = None
    source: Optional[SourceRef] = None

    @property
    def object_id(self) -> str:
        return self.name or "workbook"

    @property
    def dashboard_count(self) -> int:
        return len(self.dashboards)

    @property
    def worksheet_count(self) -> int:
        return len(self.worksheets)

    @property
    def hidden_worksheet_count(self) -> int:
        return len([w for w in self.worksheets if w.is_visible is False])

    @property
    def unused_worksheet_count(self) -> int:
        return len([w for w in self.worksheets if not w.is_used])

    @property
    def visible_used_worksheets(self) -> List[str]:
        """Worksheets placed on a dashboard but left visible in the workbook."""
        return [w.name for w in self.worksheets if w.is_used and w.is_visible is not False]

    @property
    def visible_used_worksheet_count(self) -> int:
        return len(self.visible_used_worksheets)

    @property
    def sheet_hygiene_defect_count(self) -> int:
        """Unused sheets that should be deleted plus used sheets left visible."""
        return self.unused_worksheet_count + self.visible_used_worksheet_count

    @property
    def calculated_fields(self) -> List[CalculatedField]:
        out: List[CalculatedField] = []
        for ds in self.datasources:
            out.extend(ds.calculated_fields)
        return out

    @property
    def filters(self) -> List[WorksheetFilter]:
        out: List[WorksheetFilter] = []
        for ws in self.worksheets:
            out.extend(ws.filters)
        return out

    @property
    def all_zones(self) -> List[DashboardZone]:
        out: List[DashboardZone] = []
        for dash in self.dashboards:
            out.extend(dash.all_zones)
        return out

    # -- workbook optimizer ------------------------------------------------
    @property
    def ignored_optimizer_rules(self) -> List[str]:
        return [r.rule_id for r in self.optimizer_rules if r.is_ignored]

    @property
    def ignored_optimizer_rule_count(self) -> int:
        return len(self.ignored_optimizer_rules)

    # -- colour ------------------------------------------------------------
    @property
    def palettes(self) -> List[MarkPalette]:
        out: List[MarkPalette] = list(self.datasource_palettes)
        for worksheet in self.worksheets:
            out.extend(worksheet.palettes)
        return out

    @property
    def built_in_palettes_used(self) -> List[str]:
        from ..parsers.colour_parser import ColourParser

        return sorted(
            {
                p.palette_name
                for p in self.palettes
                if p.palette_name and ColourParser.is_built_in_palette(p.palette_name)
            }
        )

    @property
    def mark_colours(self) -> List[str]:
        values: set = set()
        for palette in self.palettes:
            values.update(palette.colour_values)
        return sorted(values)

    @property
    def max_colours_in_a_view(self) -> int:
        return max((p.distinct_colour_count for p in self.palettes), default=0)

    @property
    def worksheets_combining_red_and_green(self) -> List[str]:
        names = [w.name for w in self.worksheets if w.combines_red_and_green]
        names.extend(
            p.object_id for p in self.datasource_palettes if p.combines_red_and_green
        )
        return sorted(set(names))

    @property
    def red_green_conflict_count(self) -> int:
        return len(self.worksheets_combining_red_and_green)

    @property
    def placeholder_image_count(self) -> int:
        return sum(d.placeholder_image_count for d in self.dashboards)

    @property
    def dashboards_without_upper_left_logo(self) -> List[str]:
        return [d.name for d in self.dashboards if not d.has_upper_left_image]

    @property
    def logo_defect_count(self) -> int:
        """Dashboards missing a top-left logo plus placeholder image assets."""
        return len(self.dashboards_without_upper_left_logo) + self.placeholder_image_count

    @property
    def naming_defect_count(self) -> int:
        """Spelling errors, technical names and raw ids exposed to the user."""
        return (
            self.misspelled_word_count
            + self.poorly_named_object_count
            + self.raw_calculation_text_count
        )

    # -- text / naming -----------------------------------------------------
    @property
    def texts(self) -> List[TextContent]:
        out: List[TextContent] = []
        for worksheet in self.worksheets:
            out.extend(worksheet.texts)
        for dashboard in self.dashboards:
            out.extend(dashboard.texts)
        return out

    @property
    def all_text(self) -> str:
        return " ".join(t.text for t in self.texts)

    @property
    def searchable_text(self) -> str:
        """All user-visible words, including worksheet and zone names."""
        parts = [self.all_text]
        parts.extend(w.name for w in self.worksheets)
        for dashboard in self.dashboards:
            parts.extend(z.display_name for z in dashboard.all_zones if z.name)
        return " ".join(parts)

    @property
    def metadata_elements_present(self) -> List[str]:
        """Which required metadata labels appear anywhere in the workbook."""
        from ..standards import standards

        haystack = self.searchable_text.lower()
        return [
            label
            for label, needles in standards().metadata_elements.items()
            if any(needle.lower() in haystack for needle in needles)
        ]

    @property
    def missing_metadata_elements(self) -> List[str]:
        from ..standards import standards

        required = set(standards().required_metadata_elements)
        return sorted(required - set(self.metadata_elements_present))

    @property
    def has_interactivity_instructions(self) -> bool:
        """Instructional microcopy explaining actions or drill-downs."""
        from ..standards import standards

        haystack = self.searchable_text.lower()
        return any(phrase in haystack for phrase in standards().interactivity_phrases)

    @property
    def texts_with_raw_calculations(self) -> List[str]:
        from ..parsers.text_parser import contains_raw_calculation

        return [t.text[:120] for t in self.texts if contains_raw_calculation(t.text)]

    @property
    def raw_calculation_text_count(self) -> int:
        return len(self.texts_with_raw_calculations)

    @property
    def poorly_named_objects(self) -> List[str]:
        """Worksheet and field names that are not business friendly."""
        from ..standards import standards

        offenders: List[str] = []
        pattern = standards().naming_defect_regex
        for worksheet in self.worksheets:
            name = worksheet.name
            if pattern.search(name) or name != name.strip():
                offenders.append(f"worksheet:{name}")
        for calculation in self.calculated_fields:
            label = calculation.caption or calculation.name
            if pattern.search(label) or label != label.strip():
                offenders.append(f"field:{label}")
        return sorted(set(offenders))

    @property
    def poorly_named_object_count(self) -> int:
        return len(self.poorly_named_objects)

    @property
    def misspelled_words(self) -> List[str]:
        from ..parsers.text_parser import find_misspellings

        return find_misspellings(self.searchable_text)

    @property
    def misspelled_word_count(self) -> int:
        return len(self.misspelled_words)

    @property
    def filters_missing_apply_button(self) -> List[str]:
        out: List[str] = []
        for dashboard in self.dashboards:
            out.extend(dashboard.filters_missing_apply_button)
        return out

    @property
    def missing_apply_button_count(self) -> int:
        return len(self.filters_missing_apply_button)

    @property
    def uses_custom_sql(self) -> bool:
        return any(ds.uses_custom_sql for ds in self.datasources)

    @property
    def live_custom_sql_datasources(self) -> List[str]:
        """Custom SQL is only a performance problem on live connections."""
        return [
            ds.name
            for ds in self.datasources
            if ds.uses_custom_sql and not ds.has_extract
        ]

    def dashboard_by_name(self, name: str) -> Optional[Dashboard]:
        for dash in self.dashboards:
            if dash.name == name:
                return dash
        return None

    def worksheet_by_name(self, name: str) -> Optional[Worksheet]:
        for ws in self.worksheets:
            if ws.name == name:
                return ws
        return None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "original_version": self.original_version,
            "source_build": self.source_build,
            "source_platform": self.source_platform,
            "repository_location": self.repository_location,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "counts": {
                "dashboards": self.dashboard_count,
                "worksheets": self.worksheet_count,
                "hidden_worksheets": self.hidden_worksheet_count,
                "unused_worksheets": self.unused_worksheet_count,
                "datasources": len(self.datasources),
                "calculated_fields": len(self.calculated_fields),
                "actions": len(self.actions),
                "filters": len(self.filters),
            },
            "style": self.style.as_dict(),
            "dashboards": [d.as_dict() for d in self.dashboards],
            "worksheets": [w.as_dict() for w in self.worksheets],
            "datasources": [d.as_dict() for d in self.datasources],
            "actions": [a.as_dict() for a in self.actions],
        }


def flatten_zones(zones: Sequence[DashboardZone]) -> List[DashboardZone]:
    out: List[DashboardZone] = []
    for zone in zones:
        out.extend(zone.walk())
    return out
