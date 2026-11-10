# Tableau QC Review Agents

> Deterministic, evidence-based QC review of **Tableau workbook XML** against the
> Cotality *Analytics Tableau Design & Performance Guide v3.0* and the
> *Tableau Dashboard Review* checklist.

[![tests](https://img.shields.io/badge/tests-445%20passing-brightgreen)]()
[![python](https://img.shields.io/badge/python-3.10%2B-blue)]()
[![rules](https://img.shields.io/badge/QC%20rules-19-orange)]()

Two agents replace a manual review checklist. Every automated answer cites the exact
XPath in the workbook that justifies it, and the agent **never guesses** — if a fact is
not in the XML it says so instead of passing the item.

| | Agent 1 — Pre-Review | Agent 2 — Post-Review |
|---|---|---|
| **When** | A dashboard is submitted for review | The developer returns a fixed workbook |
| **Input** | One workbook XML | Revised XML + Agent 1's audit JSON |
| **Answers** | "Does this meet our standards?" | "Were the cited issues fixed, and did the fix break anything?" |
| **Output** | Filled checklist + findings (XLSX / JSON / PDF) | Per-issue resolution + regression check |

**Scope:** the agent fills the **Agent Review** tab only — 19 questions, 19 rules, one
rule per question, every answer **Y or N**. All other tabs are preserved exactly as the
template defines them: the Peer Review and Tech Review tabs are the human review portions
and are handed back untouched.

---

## Contents

- [Quick start](#quick-start)
- [Installation](#installation)
- [Running Agent 1](#running-agent-1--pre-review)
- [Running Agent 2](#running-agent-2--post-review)
- [Understanding the output](#understanding-the-output)
- [Repository layout](#repository-layout)
- [Configuring the standards](#configuring-the-standards)
- [Development](#development)
- [Limitations](#limitations)

---

## Quick start

```bash
git clone https://github.com/thc-clgx/tableau-qc-review-agents.git
cd tableau-qc-review-agents

python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Review the bundled example workbook
.venv/bin/tableau-qc pre-review "examples/workbooks/Model Performance Dashboard.XML" --pdf
```

Reports land in `output/`.

---

## Installation

**Requires Python 3.10+.**

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"      # editable install + pytest
```

Or, without installing the package:

```bash
pip install -r requirements.txt
export PYTHONPATH=src                   # then use: python -m tableau_qc ...
```

Verify the install and cross-check the rules against the checklist:

```bash
.venv/bin/tableau-qc rules
```

```
Loaded 27 rules from config/rules
  CTL-CHART-001      [LOW     ] workbook   Unnecessary gridlines and banding must be removed (enabled)
  ...
Checklist cross-check against config/checklist
  every checklist_ref points at a real question
```

Add `--strict` to fail the command on a dangling reference (useful in CI).

> **Input is always XML.** The framework does not open `.twb`/`.twbx` archives, connect
> to Tableau Server/Cloud, or convert workbooks. Export the XML first.

---

## Running Agent 1 — Pre-Review

```bash
.venv/bin/tableau-qc pre-review <path/to/workbook.xml> [options]
```

**Example**

```bash
.venv/bin/tableau-qc pre-review "examples/workbooks/Model Performance Dashboard.XML" \
    --pdf \
    --basename MyDashboard_prereview_2026-11-07
```

**Options**

| Option | Purpose |
|---|---|
| `--pdf` | Also write a PDF (XLSX + JSON are written by default) |
| `--basename NAME` | Base name for the output files |
| `--output-dir DIR` | Output folder (default `output/`) |
| `--rule-id ID` | Run only this rule — repeatable |
| `--category NAME` | Run one category only (`Layout`, `Colour`, `Performance`, …) |
| `--tag NAME` | Run rules carrying this tag |
| `--no-excel` / `--no-json` | Skip a format |

**Exit codes:** `0` = PASS · `1` = FAIL · `2` = bad input.

### Output

| File | Audience |
|---|---|
| `<name>_pre_review.xlsx` | **The developer** — the full review template with the **Agent Review tab** filled in (`Pass (Y/N)` and `Recommended Changes`); every other tab is left blank for the human reviewer |
| `<name>_pre_review.json` | **Agent 2** — keep this, it is the baseline audit |
| `<name>_pre_review.pdf` | Stakeholders |

A sample of each is in [`docs/sample_output/`](docs/sample_output).

---

## Running Agent 2 — Post-Review

```bash
.venv/bin/tableau-qc post-review <revised.xml> --previous-audit <audit.json> [options]
```

**Example**

```bash
.venv/bin/tableau-qc post-review "examples/workbooks/Model Performance Dashboard_Remediated_v3.XML" \
    --previous-audit "output/MyDashboard_prereview_2026-11-07_pre_review.json" \
    --baseline-xml  "examples/workbooks/Model Performance Dashboard.XML" \
    --sme-feedback  "examples/reviews/sme_feedback_from_review_report.yaml" \
    --pdf --basename MyDashboard_postreview_2026-11-07
```

**Agent 2 needs at least one baseline:**

| Option | Notes |
|---|---|
| `--previous-audit <json>` | **Preferred** — the actual list of cited issues |
| `--baseline-xml <xml>` | The original workbook; used when no JSON exists |
| `--sme-feedback <yaml>` | Optional reviewer comments |

Supplying both the JSON and the baseline XML gives the richest before/after evidence.

**Exit codes:** `0` = sign-off ready · `1` = unresolved items or regressions remain.

### Verification outcomes

| Outcome | Meaning |
|---|---|
| `RESOLVED` | The cited issue no longer reproduces |
| `UNRESOLVED` | Still failing |
| `PARTIALLY_RESOLVED` | Some assertions fixed, others not |
| `CANNOT_VERIFY` | Object deleted, or the value is no longer declared |
| `NEW_FAILURE` | **Passed before, fails now — the change introduced a new defect** |
| `UNCHANGED_PASS` | Was fine, still fine |

### SME feedback format

```yaml
feedback:
  - rule_id: CTL-LAYOUT-004            # optional — ties the comment to a rule
    target_id: "Dashboard A:zone-20"   # optional — ties it to an object
    author: A. Reviewer
    raised_on: 2026-11-07
    comment: Increase the padding around the KPI tiles.

  - author: B. Reviewer
    comment: Confirm the logo is in the upper left corner.
```

Comments carrying a `rule_id` are verified automatically; the rest appear on an
**SME Feedback** tab as `CANNOT_VERIFY` for a human to confirm.

---

## Understanding the output

The **Pass (Y/N)** column carries a binary answer for every one of the 19 questions.

| Answer | Meaning |
|---|---|
| **Y** | The standard is met, evidenced from the XML |
| **N** | The standard is not met — the **Recommended Changes** column says what to fix |

Rules **fail closed**: when a required value is not declared in the workbook, compliance
has not been demonstrated, so the answer is `N` and the comment explains what to check.
A rule with nothing to assess (for example a colour rule on a workbook with no colour
encodings) cannot be violated and answers `Y`.

Every answer carries evidence behind it: the field checked, the operator, the expected
value, the observed value, and the source XPath — available in the JSON report.

---

## Repository layout

```
.
├── src/tableau_qc/
│   ├── xmlio/          Secure XML loader (no DTD, no entities, no network)
│   ├── parsers/        All XPath knowledge lives here
│   ├── domain/         Normalised model, findings, comparison types
│   ├── rules/          Schema, YAML loader, operators, selectors, engine, validation
│   ├── recommendations/ Deterministic advice + optional LLM hook
│   ├── reporting/      XLSX, PDF and JSON writers
│   ├── checklist.py    Checklist definition and population
│   ├── settings.py     Paths (all env-overridable)
│   └── cli.py          `tableau-qc` entry point
├── config/
│   ├── rules/          19 QC rules, one per Agent Review question
│   ├── checklist/      Question -> rule mapping (Agent Review)
│   └── standards/      Word lists, label phrases, tolerances
├── examples/
│   ├── workbooks/      Example workbook XML (original + remediated)
│   ├── standards/      Style guide and checklist template
│   └── reviews/        A human review report and SME feedback sample
├── tests/              445 tests incl. per-rule and security fixtures
├── scripts/            Fixture generation and remediation helpers
└── docs/
    ├── USER_GUIDE.md   Full operating guide
    └── sample_output/  Example generated reports
```

---

## Configuring the standards

**No review standard is hard-coded in Python.** Everything a reviewer may need to change
lives in `config/`:

| File | Controls |
|---|---|
| `config/rules/*.yaml` | The 19 QC rules — thresholds, severities, messages, remediation text |
| `config/checklist/*.yaml` | Which rules answer which checklist question |
| `config/standards/content.yaml` | Spelling word list, metadata label phrases, naming patterns, logo tolerance |

### Changing a threshold

```yaml
  - id: CTL-LAYOUT-003
    title: A dashboard must contain no more than 6 views
    scope: dashboard
    severity: HIGH
    standard_ref: "Design & Performance Guide v3.0, Dashboard Best Practices"
    checklist_ref: "Agent Review!B10"
    assertions:
      - field: view_count
        operator: less_than_or_equal
        value: 6                      # <- change the limit here
    recommendation: >
      Reduce the dashboard to at most 6 views.
```

### Rules are validated when they load

Mistakes fail immediately with a message naming the rule, rather than degrading to
`MANUAL_REVIEW` on a real workbook:

| Mistake | Message |
|---|---|
| `field: siz.widht` | `'siz' does not exist on Dashboard` |
| `operator: between` with one value | `requires a list of exactly two bounds` |
| `operator: in` with a scalar | `requires a list value` |
| Broken regex in `matches` | `invalid regular expression` |
| Two assertions on one field | `duplicate assertion on field …` |

Validate at any time with `tableau-qc rules --strict`.

### Adding a rule

1. Add the YAML entry to the relevant file in `config/rules/`.
2. Map it to a checklist question in `config/checklist/`.
3. Add `tests/fixtures/rules/<RULE_ID>_pass.xml` and `<RULE_ID>_fail.xml`.
4. Add the id to `RULE_IDS` in `tests/test_rule_fixtures.py`.
5. Run `pytest` — a rule without both fixtures fails the suite.

**Scopes:** `workbook`, `dashboard`, `dashboard_zone`, `dashboard_view_zone`,
`dashboard_filter_zone`, `multi_select_filter_zone`, `dashboard_image`, `mark_palette`,
`worksheet`, `used_worksheet`, `datasource`, `calculated_field`, `action`,
`worksheet_filter`.

**Operators:** `equals`, `not_equals`, `greater_than[_or_equal]`, `less_than[_or_equal]`,
`between`, `in`, `not_in`, `contains`, `all_in`, `any_in`, `none_in`, `matches`,
`is_true`, `is_false`, `is_empty`, `is_not_empty`, `length_*`, `starts_with`, `ends_with`.

---

## Development

```bash
.venv/bin/python -m pytest tests -q          # 445 tests
.venv/bin/python -m pytest tests -q --cov    # with coverage (if pytest-cov installed)
.venv/bin/tableau-qc rules --strict          # validate the rule repository
```

**Guarantees enforced by the test suite**

- Every rule has a **passing and a failing fixture**.
- Results are **deterministic** — identical input always produces identical output.
- Every automated PASS/FAIL **carries evidence** with a source XPath.
- The loader is hardened against **XXE, billion-laughs, external DTD** and malformed XML.
- Each of the 9 parsers has a **dedicated unit-test module**.

### Environment overrides

| Variable | Default |
|---|---|
| `TABLEAU_QC_RULES_DIR` | `config/rules` |
| `TABLEAU_QC_CHECKLIST` | `config/checklist` |
| `TABLEAU_QC_STANDARDS` | `config/standards/content.yaml` |
| `TABLEAU_QC_EXCEL_TEMPLATE` | `examples/standards/draft Tableau Dashboard Review - [Report Name].xlsx` |
| `TABLEAU_QC_OUTPUT_DIR` | `output` |
| `TABLEAU_QC_LLM_ENABLED` | `false` |

---

## Limitations

Every question on the **Agent Review** tab is answered automatically. Subjective items
were removed from that tab by the reviewers, so the agent does not need to abstain.

Some checks necessarily verify a *proxy* for the standard, because the XML does not carry
the underlying fact. These still answer Y/N, but a reviewer may wish to spot-check them:

| Check | What the agent verifies | What it cannot see |
|---|---|---|
| Logo in the upper left | Image zone position and asset filename | The image itself, or its contrast |
| Metadata complete | All three labels are present | Whether the date is current or the owner correct |
| Filter lists with many values | The filter control type | The number of distinct values (lives in the extract) |
| Views organised by importance | Zone geometry and size hierarchy | Business importance of each view |

The **Peer Review** and **Tech Review** tabs are deliberately out of scope. They remain in
the output workbook, blank, for the human reviewer to complete.

### Not implemented by design

- **Concrete LLM provider.** The hook, payload scrubbing and a `NullLLMProvider` exist
  and are tested. LLM enrichment is opt-in, can only add *advisory* text, and
  **never receives workbook XML**.
- **TWB/TWBX extraction, Tableau Server/Cloud download, workbook conversion.**

---

## Security

- Secrets are **never** committed — see [`.gitignore`](.gitignore).
- The XML loader rejects DOCTYPE/DTD declarations, entity declarations and external
  entity resolution, disables parameter-entity parsing, and bounds input size and
  nesting depth.
- No workbook XML is ever transmitted to a third-party service.

This repository is **private** and contains internal standards documents and example
workbooks. Do not make it public without a data review.

---

## Further reading

📘 **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)** — full operating guide: detailed
workflow, file conventions, checklist coverage table, and the complete rule reference.
