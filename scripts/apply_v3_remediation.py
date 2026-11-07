"""Apply remediation for the guide v3.0 findings to produce a revised workbook.

This simulates the developer's fix pass so Agent 2 can be exercised end to end.
Each transformation maps to a specific rule finding from the pre-review.

Run:  python scripts/apply_v3_remediation.py
"""

from __future__ import annotations

import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

SOURCE = Path("examples/workbooks/Model Performance Dashboard.XML")
TARGET = Path("examples/workbooks/Model Performance Dashboard_Remediated_v3.XML")

LAYOUT_TYPES = {"layout-basic", "layout-flow"}

# CTL-LAYOUT-003: dashboards over the 6-view limit. Executive Summary has 7
# views and Underperforming Models has 11; consolidate down to the limit.
REMOVE_BY_DASHBOARD = {
    "Model Surveillance Executive Summary": {"713"},
    "Underperforming Models": {"927", "1235", "924", "923", "931", "710", "707"},
}

# CTL-LAYOUT-004: 20px outer / 12px inner padding.
OUTER_PADDING, INNER_PADDING = "20", "12"

# CTL-COLOR-001: replace the Tableau built-in palette with a Cotality palette.
PALETTE_REPLACEMENT = {"tableau20_10_0": "Cotality-Extended"}

# CTL-COLOR-002/003: brand-safe replacements for unbranded and red/green marks.
COLOUR_REPLACEMENT = {
    "#1f77b4": "#077982", "#4e79a7": "#077982", "#a0cbe8": "#bab0ac",
    "#2ca02c": "#ffcd2e", "#59a14f": "#ffcd2e", "#8cd17d": "#ddd7cd",
    "#339b62": "#ffcd2e", "#d62728": "#ff8e65", "#f1384f": "#ff8e65",
    "#e15759": "#ff8e65", "#ff9d9a": "#ddd7cd", "#f28e2b": "#ff8e65",
    "#ffbe7d": "#ddd7cd", "#17becf": "#077982", "#9467bd": "#a805fb",
    "#c5b0d5": "#ddd7cd", "#8c564b": "#1e1405", "#c49c94": "#bab0ac",
    "#e377c2": "#dd37d2", "#f7b6d2": "#ddd7cd", "#7f7f7f": "#bab0ac",
    "#c7c7c7": "#ddd7cd", "#bcbd22": "#ffcd2e", "#dbdb8d": "#ddd7cd",
    "#ff7f0e": "#ff8e65", "#ffbb78": "#ddd7cd", "#287a4d": "#ffcd2e",
    "#0b6fc1": "#077982", "#148def": "#077982", "#009aa1": "#077982",
}

# CTL-TYPO-002: map off-band sizes onto the nearest approved size.
FONT_SIZE_REPLACEMENT = {"9": "10", "22": "24", "13": "12", "14": "15", "18": "16"}

# CTL-CONTENT-003: spelling corrections.
SPELLING = {
    "Survellance": "Surveillance", "Surveilance": "Surveillance",
    "survellance": "surveillance", "surveilance": "surveillance",
    "actipn": "action", "Deail": "Detail", "deail": "detail",
    "implemnt": "implement", "Implemnt": "Implement",
}


def is_worksheet_zone(zone: ET.Element) -> bool:
    return zone.get("type-v2") is None and zone.get("name") is not None


def standardise_padding(zone: ET.Element) -> None:
    style = zone.find("zone-style")
    if style is None:
        style = ET.SubElement(zone, "zone-style")
    for fmt in list(style.findall("format")):
        attr = fmt.get("attr") or ""
        if attr.startswith(("margin", "padding")):
            style.remove(fmt)
    for attr, value in (("margin", OUTER_PADDING), ("padding", INNER_PADDING)):
        element = ET.SubElement(style, "format")
        element.set("attr", attr)
        element.set("value", value)


def dock_floating_zones(zones: ET.Element) -> list[str]:
    top_level = zones.findall("zone")
    container = next((z for z in top_level if z.get("type-v2") in LAYOUT_TYPES), None)
    if container is None:
        return []
    docked = []
    for zone in top_level:
        if zone is container or zone.get("type-v2") in LAYOUT_TYPES:
            continue
        zones.remove(zone)
        container.append(zone)
        docked.append(zone.get("id") or "?")
    return docked


def remove_zones(zones: ET.Element, wanted: set[str]) -> list[str]:
    removed = []

    def recurse(parent: ET.Element) -> None:
        for child in list(parent.findall("zone")):
            if child.get("id") in wanted:
                parent.remove(child)
                removed.append(f"{child.get('id')} ({child.get('name')})")
            else:
                recurse(child)

    recurse(zones)
    return removed


def main() -> None:
    shutil.copyfile(SOURCE, TARGET)
    tree = ET.parse(TARGET)
    root = tree.getroot()
    retained: set[str] = set()

    print(f"Source : {SOURCE}\nTarget : {TARGET}\n")

    for dashboard in root.find("dashboards"):
        name = dashboard.get("name") or ""
        zones = dashboard.find("zones")
        if zones is None:
            continue
        print(f"=== {name} ===")
        for entry in remove_zones(zones, REMOVE_BY_DASHBOARD.get(name, set())):
            print(f"  CTL-LAYOUT-003 consolidated : zone {entry}")
        docked = dock_floating_zones(zones)
        if docked:
            print(f"  CTL-STRUCT-001 docked       : zones {', '.join(docked)}")
        padded = 0
        for zone in zones.iter("zone"):
            if is_worksheet_zone(zone):
                standardise_padding(zone)
                padded += 1
                retained.add(zone.get("name") or "")
        print(f"  CTL-LAYOUT-004 padding 20/12: {padded} zones")
        # CTL-STRUCT-003: replace the placeholder image asset.
        for element in zones.iter():
            for key, value in list(element.attrib.items()):
                if "Untitled.png" in value:
                    element.set(key, value.replace("Untitled.png", "cotality logomark.png"))
        print()

    # CTL-COLOR-001: swap the built-in palette for a Cotality palette.
    swapped = 0
    for encoding in root.iter("encoding"):
        replacement = PALETTE_REPLACEMENT.get(encoding.get("palette") or "")
        if replacement:
            encoding.set("palette", replacement)
            swapped += 1
    print(f"CTL-COLOR-001 palettes replaced : {swapped}")

    # CTL-COLOR-002/003: recolour marks onto the brand palette.
    recoloured = 0
    for mapping in root.iter("map"):
        value = (mapping.get("to") or "").lower()
        if value in COLOUR_REPLACEMENT:
            mapping.set("to", COLOUR_REPLACEMENT[value])
            recoloured += 1
    print(f"CTL-COLOR-002/003 marks recoloured: {recoloured}")

    # CTL-PERF-001: un-ignore Workbook Optimizer rules.
    unignored = 0
    for rule in root.iter("rule"):
        if rule.get("ignored") == "true":
            rule.set("ignored", "false")
            unignored += 1
    print(f"CTL-PERF-001 optimizer rules un-ignored: {unignored}")

    # CTL-PERF-002: enable the Apply button on multi-select filters.
    applied = 0
    for zone in root.iter("zone"):
        if zone.get("type-v2") == "filter" and zone.get("mode") in (
            "checkdropdown",
            "checklist",
            "multivalue-list",
        ):
            if zone.get("show-apply") != "true":
                zone.set("show-apply", "true")
                applied += 1
    print(f"CTL-PERF-002 apply buttons enabled: {applied}")

    # CTL-TYPO-002: move off-band font sizes onto approved sizes.
    resized = 0
    for run in root.iter("run"):
        replacement = FONT_SIZE_REPLACEMENT.get(run.get("fontsize") or "")
        if replacement:
            run.set("fontsize", replacement)
            resized += 1
    print(f"CTL-TYPO-002 font sizes corrected : {resized}")

    # CTL-CHART-001: switch remaining gridlines off and banding to zero.
    cleaned = 0
    for fmt in root.iter("format"):
        attr = fmt.get("attr")
        if attr == "line-visibility" and fmt.get("value") == "on":
            fmt.set("value", "off")
            cleaned += 1
        elif attr == "band-size" and (fmt.get("value") or "0") not in ("0", "0.0"):
            fmt.set("value", "0")
            cleaned += 1
    print(f"CTL-CHART-001 clutter removed    : {cleaned}")

    tree.write(TARGET, encoding="utf-8", xml_declaration=True)

    # CTL-HYG-001: consolidating views orphans their worksheets. The guide says
    # any sheet not used should be deleted, so remove them along with their
    # windows and any action that referenced them.
    worksheets = root.find("worksheets")
    orphans = [
        ws for ws in worksheets.findall("worksheet") if ws.get("name") not in retained
    ]
    orphan_names = {ws.get("name") for ws in orphans}
    for ws in orphans:
        worksheets.remove(ws)

    windows = root.find("windows")
    if windows is not None:
        for window in list(windows.findall("window")):
            if window.get("class") == "worksheet" and window.get("name") in orphan_names:
                windows.remove(window)

    actions = root.find("actions")
    dropped = 0
    if actions is not None:
        for action in list(actions):
            referenced = {
                node.get("worksheet")
                for node in list(action.findall("source")) + list(action.findall("target"))
                if node.get("worksheet")
            }
            if referenced & orphan_names:
                actions.remove(action)
                dropped += 1
    print(f"CTL-HYG-001 orphan worksheets removed: {len(orphans)} (+{dropped} actions)")

    tree.write(TARGET, encoding="utf-8", xml_declaration=True)

    # CTL-CONTENT-003: spelling fixes applied over the serialised document so
    # that titles, tooltips, captions and field names are all covered.
    text = TARGET.read_text(encoding="utf-8")
    fixed = 0
    for wrong, right in SPELLING.items():
        count = len(re.findall(re.escape(wrong), text))
        if count:
            text = text.replace(wrong, right)
            fixed += count
    TARGET.write_text(text, encoding="utf-8")
    print(f"CTL-CONTENT-003 spellings fixed  : {fixed}")
    print(f"\nwritten: {TARGET}")


if __name__ == "__main__":
    main()
