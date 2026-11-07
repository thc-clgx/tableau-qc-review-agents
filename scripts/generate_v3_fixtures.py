"""Generate pass/fail fixtures for the rules added in guide v3.0.

Each fixture is a minimal, fully-formed Tableau workbook that isolates one
rule, so a failure points at exactly one cause.

Run:  python scripts/generate_v3_fixtures.py
"""

from __future__ import annotations

from pathlib import Path

OUT = Path("tests/fixtures/rules")

HEADER = """<?xml version='1.0' encoding='utf-8' ?>
<!-- Fixture: {purpose} -->
<workbook original-version='18.1' source-build='2025.3.1' source-platform='win' version='18.1'>
  <repository-location id='{wb_id}' path='/t/cotalityanalytics/workbooks' site='cotalityanalytics' />
"""

WORKBOOK_STYLE = """  <style>
    <style-rule element='worksheet'>
      <format attr='font-family' value='{font}' />
    </style-rule>
    <style-rule element='worksheet-title'>
      <format attr='font-family' value='Arial Black' />
    </style-rule>
  </style>
"""


def datasource(palette: str | None, colours: list[str], extract: bool, custom_sql: bool) -> str:
    encoding = ""
    if palette or colours:
        maps = "\n".join(f"            <map to='{c}'><bucket>&quot;{i}&quot;</bucket></map>"
                         for i, c in enumerate(colours))
        palette_attr = f" palette='{palette}'" if palette else ""
        encoding = f"""      <style>
        <style-rule element='mark'>
          <encoding attr='color' field='[Category]'{palette_attr} type='palette'>
{maps}
          </encoding>
        </style-rule>
      </style>
"""
    relation = (
        "        <relation name='Custom SQL Query' type='text'>SELECT * FROM t</relation>\n"
        if custom_sql
        else "        <relation name='t' table='[dbo].[t]' type='table' />\n"
    )
    extract_el = "      <extract enabled='true' />\n" if extract else ""
    return f"""  <datasources>
    <datasource caption='Sales' inline='true' name='federated.sales' version='18.1'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='db' name='sqlserver.1'>
            <connection class='sqlserver' dbname='analytics' server='db.internal' />
          </named-connection>
        </named-connections>
{relation}      </connection>
{extract_el}{encoding}      <column caption='Sales' datatype='real' name='[Sales]' role='measure' type='quantitative' />
    </datasource>
  </datasources>
"""


def worksheet(name: str, *, grid_on=False, band=0, labels=False, axes=False, title_size="15") -> str:
    fmts = [f"            <format attr='line-visibility' value='{'on' if grid_on else 'off'}' />",
            f"            <format attr='band-size' value='{band}' />"]
    if labels:
        fmts.append("            <format attr='mark-labels-show' value='true' />")
    if axes:
        fmts.append("            <format attr='display-field-labels' value='true' />")
    fmt_xml = "\n".join(fmts)
    return f"""    <worksheet name='{name}'>
      <layout-options>
        <title>
          <formatted-text><run fontname='Arial Black' fontsize='{title_size}'>{name}</run></formatted-text>
        </title>
      </layout-options>
      <table>
        <view><datasource-dependencies datasource='federated.sales' /></view>
        <style>
          <style-rule element='mark'>
{fmt_xml}
          </style-rule>
        </style>
        <panes><pane><mark class='Bar' /></pane></panes>
        <rows /><cols />
      </table>
    </worksheet>
"""


def zone(zid: str, name: str, margin=20, padding=12) -> str:
    return f"""          <zone h='30000' id='{zid}' name='{name}' w='30000' x='0' y='0'>
            <zone-style>
              <format attr='margin' value='{margin}' />
              <format attr='padding' value='{padding}' />
            </zone-style>
          </zone>
"""


def filter_zone(zid: str, sheet: str, mode="checkdropdown", apply_btn=True, values="database") -> str:
    apply_attr = " show-apply='true'" if apply_btn else ""
    return f"""          <zone h='5000' id='{zid}' mode='{mode}' name='{sheet}' param='[federated.sales].[none:Category:nk]' type-v2='filter' values='{values}'{apply_attr} w='16000' x='84000' y='0'>
            <zone-style><format attr='margin' value='20' /><format attr='padding' value='12' /></zone-style>
          </zone>
"""


def logo_zone(file_name="cotality logomark.png", x=0, y=0) -> str:
    return f"""          <zone h='8000' id='90' type-v2='bitmap' w='12000' x='{x}' y='{y}'>
            <zone-style><format attr='margin' value='20' /><format attr='padding' value='12' /></zone-style>
            <bitmap param='/Template Files/Image/{file_name}' />
          </zone>
"""


def text_zone(zid: str, text: str, y: int) -> str:
    return f"""          <zone h='4000' id='{zid}' type-v2='text' w='100000' x='0' y='{y}'>
            <zone-style><format attr='margin' value='20' /><format attr='padding' value='12' /></zone-style>
            <formatted-text><run fontname='Arial' fontsize='11'>{text}</run></formatted-text>
          </zone>
"""


METADATA_TEXT = "Data Last Updated: 2026-10-29 | Dashboard Contact: A Shi | Data Owner: P Vijayakumar"
INSTRUCTION_TEXT = "Select a bar in the chart above to filter the detail table below."


def build(
    path: Path,
    *,
    purpose: str,
    wb_id: str = "V3Fixture",
    font: str = "Arial",
    sheets: list[str] | None = None,
    palette: str | None = None,
    colours: list[str] | None = None,
    extract: bool = True,
    custom_sql: bool = False,
    grid_on: bool = False,
    band: int = 0,
    labels: bool = False,
    axes: bool = False,
    title_size: str = "15",
    apply_btn: bool = True,
    filter_mode: str = "checkdropdown",
    filter_values: str = "database",
    logo: str | None = "cotality logomark.png",
    logo_pos: tuple = (0, 0),
    metadata: bool = True,
    instructions: bool = True,
    floating: bool = False,
    optimizer_ignored: list[str] | None = None,
    hide_sheets: bool = True,
    orphan_sheet: str | None = None,
) -> None:
    sheets = sheets or ["Sheet 1", "Sheet 2"]
    colours = colours or []
    parts = [HEADER.format(purpose=purpose, wb_id=wb_id), WORKBOOK_STYLE.format(font=font)]

    if optimizer_ignored:
        rules = "\n".join(f"    <rule ignored='true' ruleID='{r}' />" for r in optimizer_ignored)
        parts.append(f"  <optimizer-settings>\n{rules}\n  </optimizer-settings>\n")

    parts.append(datasource(palette, colours, extract, custom_sql))

    parts.append("  <worksheets>\n")
    for name in sheets:
        parts.append(worksheet(name, grid_on=grid_on, band=band, labels=labels,
                               axes=axes, title_size=title_size))
    if orphan_sheet:
        parts.append(worksheet(orphan_sheet))
    parts.append("  </worksheets>\n")

    parts.append("  <dashboards>\n    <dashboard name='Dashboard A'>\n      <style />\n")
    parts.append("      <size maxheight='900' maxwidth='1600' minheight='900' minwidth='1600' />\n")
    parts.append("      <zones>\n        <zone h='100000' id='1' type-v2='layout-flow' w='100000' x='0' y='0'>\n")
    for index, name in enumerate(sheets):
        parts.append(zone(str(10 + index), name))
    parts.append(filter_zone("50", sheets[0], mode=filter_mode,
                             apply_btn=apply_btn, values=filter_values))
    if logo:
        parts.append(logo_zone(logo, *logo_pos))
    if metadata:
        parts.append(text_zone("91", METADATA_TEXT, 92000))
    if instructions:
        parts.append(text_zone("92", INSTRUCTION_TEXT, 86000))
    parts.append("        </zone>\n")
    if floating:
        parts.append("        <zone h='3000' id='99' param='[Parameters].[P1]' type-v2='paramctrl' w='12000' x='85000' y='40000' />\n")
    parts.append("      </zones>\n      <devicelayouts />\n    </dashboard>\n  </dashboards>\n")

    parts.append("  <windows>\n    <window class='dashboard' maximized='true' name='Dashboard A' />\n")
    for name in sheets:
        hidden = " hidden='true'" if hide_sheets else ""
        parts.append(f"    <window class='worksheet'{hidden} name='{name}' />\n")
    if orphan_sheet:
        parts.append(f"    <window class='worksheet' hidden='true' name='{orphan_sheet}' />\n")
    parts.append("  </windows>\n</workbook>\n")

    path.write_text("".join(parts), encoding="utf-8")


BRAND = ["#ffcd2e", "#ff8e65", "#1e1405"]
RED_GREEN = ["#d62728", "#2ca02c", "#1e1405"]
MANY = ["#ffcd2e", "#ff8e65", "#ff6e80", "#dd37d2", "#a805fb", "#077982", "#1e1405", "#bab0ac"]

CASES = [
    ("CTL-COLOR-001_pass", dict(purpose="Cotality palette (PASS)", palette="Cotality-Extended", colours=BRAND)),
    ("CTL-COLOR-001_fail", dict(purpose="Tableau 20 palette (FAIL)", palette="tableau20_10_0", colours=BRAND)),
    ("CTL-COLOR-002_pass", dict(purpose="no red/green pairing (PASS)", palette="Cotality-Extended", colours=BRAND)),
    ("CTL-COLOR-002_fail", dict(purpose="red and green in one view (FAIL)", palette="Cotality-Extended", colours=RED_GREEN)),
    ("CTL-COLOR-003_pass", dict(purpose="three mark colours (PASS)", palette="Cotality-Extended", colours=BRAND)),
    ("CTL-COLOR-003_fail", dict(purpose="eight mark colours (FAIL/ADVISORY)", palette="Cotality-Extended", colours=MANY)),
    ("CTL-TYPO-002_pass", dict(purpose="approved text sizes (PASS)", title_size="15")),
    ("CTL-TYPO-002_fail", dict(purpose="9pt text size (FAIL)", title_size="9")),
    ("CTL-PERF-001_pass", dict(purpose="no optimizer rules ignored (PASS)")),
    ("CTL-PERF-001_fail", dict(purpose="optimizer rules ignored (FAIL)", optimizer_ignored=["8", "12"])),
    ("CTL-PERF-002_pass", dict(purpose="apply button enabled (PASS)", apply_btn=True)),
    ("CTL-PERF-002_fail", dict(purpose="apply button missing (FAIL)", apply_btn=False)),
    ("CTL-PERF-003_pass", dict(purpose="dropdown filter control (PASS)", filter_mode="checkdropdown")),
    ("CTL-PERF-003_fail", dict(purpose="enumerated checklist filter (ADVISORY)", filter_mode="checklist")),
    ("CTL-PERF-004_pass", dict(purpose="custom SQL inside an extract (PASS)", custom_sql=True, extract=True)),
    ("CTL-PERF-004_fail", dict(purpose="custom SQL on a live connection (FAIL)", custom_sql=True, extract=False)),
    ("CTL-HYG-001_pass", dict(purpose="all worksheets used (PASS)")),
    ("CTL-HYG-001_fail", dict(purpose="orphan worksheet present (FAIL)", orphan_sheet="Scratch Sheet")),
    ("CTL-HYG-002_pass", dict(purpose="used worksheets hidden (PASS)", hide_sheets=True)),
    ("CTL-HYG-002_fail", dict(purpose="used worksheets visible (FAIL)", hide_sheets=False)),
    ("CTL-STRUCT-001_pass", dict(purpose="all tiled (PASS)", floating=False)),
    ("CTL-STRUCT-001_fail", dict(purpose="floating parameter control (FAIL)", floating=True)),
    ("CTL-STRUCT-002_pass", dict(purpose="logo upper-left (PASS)", logo_pos=(0, 0))),
    ("CTL-STRUCT-002_fail", dict(purpose="no logo in upper-left (FAIL)", logo_pos=(60000, 60000))),
    ("CTL-STRUCT-003_pass", dict(purpose="named logo asset (PASS)", logo="cotality logomark.png")),
    ("CTL-STRUCT-003_fail", dict(purpose="placeholder image name (ADVISORY)", logo="Untitled.png")),
    ("CTL-CONTENT-001_pass", dict(purpose="metadata complete (PASS)", metadata=True)),
    ("CTL-CONTENT-001_fail", dict(purpose="metadata missing (FAIL)", metadata=False)),
    ("CTL-CONTENT-002_pass", dict(purpose="interactivity instructions (PASS)", instructions=True)),
    ("CTL-CONTENT-002_fail", dict(purpose="no instructions (ADVISORY)", instructions=False)),
    ("CTL-CONTENT-003_pass", dict(purpose="correct spelling (PASS)", sheets=["Total Models by Surveillance Type"])),
    ("CTL-CONTENT-003_fail", dict(purpose="misspelled sheet name (FAIL)", sheets=["Total Models by Surveilance Type"])),
    ("CTL-CONTENT-004_pass", dict(purpose="business friendly names (PASS)", sheets=["Sales by Region"])),
    ("CTL-CONTENT-004_fail", dict(purpose="duplicated '(copy)' name (ADVISORY)", sheets=["Sales by Region (copy)"])),
    ("CTL-CHART-001_pass", dict(purpose="gridlines off, no banding (PASS)", grid_on=False, band=0)),
    ("CTL-CHART-001_fail", dict(purpose="gridlines on and banding (ADVISORY)", grid_on=True, band=1)),
    ("CTL-CHART-002_pass", dict(purpose="labels only (PASS)", labels=True, axes=False)),
    ("CTL-CHART-002_fail", dict(purpose="labels and axes both shown (ADVISORY)", labels=True, axes=True)),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, kwargs in CASES:
        build(OUT / f"{name}.xml", wb_id=name.replace("-", ""), **kwargs)
    print(f"generated {len(CASES)} fixtures in {OUT}")


if __name__ == "__main__":
    main()
