# Tableau XML Dashboard Review Agent — User Guide

**Version 2.0 · 9 November 2026**
Automated QC review of Tableau workbooks against the Cotality *Analytics Tableau Design &
Performance Guide v3.0* and the *Tableau Dashboard Review* checklist.

---

## 1. Executive summary

This framework replaces the manual Tableau review checklist with a deterministic agent
that reads a workbook's **XML** and answers the review questions automatically, citing
the exact location in the file that justifies each answer.

There are two agents that share one parser and one rule engine:

| | Agent 1 — Pre-Review | Agent 2 — Post-Review |
|---|---|---|
| **When** | Developer submits a dashboard for review | Developer returns a fixed workbook |
| **Input** | One workbook XML | Revised XML + the Agent 1 audit JSON |
| **Question it answers** | "Does this meet our standards?" | "Were the cited issues actually fixed, and did the fix break anything?" |
| **Output** | Filled checklist + findings (JSON / Excel / PDF) | Resolution status per issue + regression check |

**Scope:** the agent fills the **Agent Review** tab only — 19 questions answered by 19
rules, one rule per question, every answer **Y or N**. All other tabs are preserved
exactly as the template defines them; the Peer Review and Tech Review tabs are the human
review portions and are handed back blank for a reviewer to complete.

> **The input is always XML.** The framework does not open `.twb`/`.twbx` archives,
> connect to Tableau Server or Cloud, or convert workbooks. Export the XML first.

---

## 2. How a review flows

```
 ┌─────────────────────┐
 │ Developer exports   │
 │ workbook XML        │
 └──────────┬──────────┘
            │
            ▼
 ┌─────────────────────────────────────────┐
 │ AGENT 1 — PRE-REVIEW                    │
 │ tableau-qc pre-review <file.xml> --pdf  │
 └──────────┬──────────────────────────────┘
            │  produces
            ▼
   output/<name>_pre_review.json   ◄── keep this, Agent 2 needs it
   output/<name>_pre_review.xlsx   ◄── send this to the developer
   output/<name>_pre_review.pdf
            │
            ▼
 ┌─────────────────────┐
 │ Developer fixes the │
 │ dashboard, exports  │
 │ a NEW XML           │
 └──────────┬──────────┘
            │
            ▼
 ┌──────────────────────────────────────────────────────┐
 │ AGENT 2 — POST-REVIEW                                │
 │ tableau-qc post-review <revised.xml>                 │
 │     --previous-audit output/<name>_pre_review.json   │
 └──────────┬───────────────────────────────────────────┘
            │  produces
            ▼
   output/<name>_post_review.{json,xlsx,pdf}
            │
            ▼
      Sign-off: YES / NO
```

---

## 3. One-time setup

```bash
cd /Users/thc/Documents/BI_review_agent
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Verify the install, list every rule, and cross-check the rules against the checklist:

```bash
.venv/bin/tableau-qc rules
```

Expected output ends with:

```
Loaded 27 rules from .../config/rules
...
Checklist cross-check against .../config/checklist
  every checklist_ref points at a real question
  NOTE  enforced but not on the checklist: CTL-LAYOUT-001, CTL-LAYOUT-002
```

Add `--strict` to make a dangling reference fail the command — useful in CI.

> If `tableau-qc` is not on your PATH, every command also works as
> `PYTHONPATH=src .venv/bin/python -m tableau_qc …`

---

## 4. Agent 1 — Pre-Review

### 4.1 What it does

1. **Loads the XML securely** — DTDs, entity declarations and external entity
   resolution are rejected, so a malicious or malformed file cannot read your disk or
   call out to the network. File size and nesting depth are bounded.
2. **Parses the workbook** into a normalised model: dashboards, zones, worksheets,
   datasources, calculated fields, filters, actions, styles, fonts, colours, images and
   visible text.
3. **Runs 27 QC rules** defined in YAML — not in code — so standards can change without
   a developer.
4. **Records evidence for every single answer**: the field checked, the expected value,
   the observed value, and the exact XPath in the file.
5. **Fills the review checklist** (both the Agent Review and Tech Review tabs) and
   writes JSON, Excel and PDF reports.

### 4.2 Where to put the input file

**Anywhere.** The path is an argument — the file is read, never moved or modified.
A practical convention:

```
BI_review_agent/
├── incoming/                      ← drop workbooks here for review
│   └── MyDashboard.xml
└── output/                        ← reports appear here automatically
```

### 4.3 The command

```bash
.venv/bin/tableau-qc pre-review "incoming/MyDashboard.xml" --pdf
```

With an explicit output name and folder:

```bash
.venv/bin/tableau-qc pre-review "incoming/MyDashboard.xml" \
    --pdf \
    --output-dir output \
    --basename MyDashboard_prereview_2026-11-07
```

**Useful options**

| Option | Purpose |
|---|---|
| `--pdf` | Also write the PDF (JSON and Excel are written by default) |
| `--basename NAME` | Controls the output file names |
| `--output-dir DIR` | Where reports are written (default `output/`) |
| `--rule-id CTL-LAYOUT-003` | Run a single rule — repeatable |
| `--category Layout` | Run one category only |
| `--no-excel` / `--no-json` | Skip a format |

**Exit codes:** `0` = overall PASS, `1` = overall FAIL, `2` = bad input.

### 4.4 What you get

| File | Audience | Contents |
|---|---|---|
| `<name>_pre_review.xlsx` | **The developer** | Your review template, unchanged except for the **Agent Review** tab, where `Pass (Y/N)` and `Recommended Changes` are filled in. The workbook opens on that tab |
| `<name>_pre_review.json` | **Agent 2** | Machine-readable audit — keep it, Agent 2 matches against it |
| `<name>_pre_review.pdf` | Stakeholders | Printable summary |

### 4.5 Reading the result — the four verdicts

| Answer | Meaning |
|---|---|
| **Y** | The standard is met, evidenced from the workbook XML |
| **N** | The standard is not met — the Recommended Changes column says what to fix |

Rules **fail closed**. When a required value is not declared in the workbook, compliance
has not been demonstrated, so the answer is `N` and the comment explains what to verify.
For example, a workbook that declares no font inherits Tableau's default, which is not
Arial — so the font question answers `N`, not "unknown".

A rule with nothing to assess cannot be violated and answers `Y`. For instance, a colour
rule on a workbook with no colour encodings reports `Y`.

---

## 5. Agent 2 — Post-Review Verification

### 5.1 What it does

1. Re-runs **every** rule against the revised XML.
2. Matches each new result to the baseline using a stable key:
   `RULE-ID :: target-type :: target-id`.
3. Classifies each previously-cited issue:

| Classification | Meaning |
|---|---|
| `RESOLVED` | The cited issue no longer reproduces |
| `UNRESOLVED` | Still failing |
| `PARTIALLY_RESOLVED` | Some assertions of the rule fixed, others not |
| `CANNOT_VERIFY` | The object was deleted, or the value is no longer declared |
| `NEW_REGRESSION` | **Passed before, fails now — the fix broke something** |
| `UNCHANGED_PASS` | Was fine, still fine |

4. Produces before/after evidence and a sign-off recommendation.

> **Why the regression check matters.** During testing, removing a view to satisfy the
> 6-view limit left its worksheet orphaned — a new violation created by the fix itself.
> Agent 2 flagged it as `NEW_REGRESSION`. That is the category of defect a human
> re-reading a checklist almost always misses.

### 5.2 Where to put the revised XML

Again, anywhere — but keep the baseline, the revision and the audit JSON together:

```
BI_review_agent/
├── incoming/
│   ├── MyDashboard.xml              ← baseline (v1, what Agent 1 reviewed)
│   └── MyDashboard_v2.xml           ← revised (what the developer sent back)
├── output/
│   └── MyDashboard_prereview_2026-11-07_pre_review.json   ← from Agent 1
└── sme_feedback.yaml                ← optional reviewer comments
```

### 5.3 The command

```bash
.venv/bin/tableau-qc post-review "incoming/MyDashboard_v2.xml" \
    --previous-audit "output/MyDashboard_prereview_2026-11-07_pre_review.json" \
    --baseline-xml "incoming/MyDashboard.xml" \
    --pdf \
    --basename MyDashboard_postreview_2026-11-07
```

**Agent 2 needs at least one baseline.** Supply either:

- `--previous-audit <json>` — **preferred**, this is the actual list of cited issues; or
- `--baseline-xml <xml>` — the original workbook, used if no JSON exists.

Supplying both is best: the JSON gives the cited issues, the XML enables full
before/after evidence.

**Exit codes:** `0` = sign-off ready, `1` = unresolved items or regressions remain.

### 5.4 Optional — feeding in SME comments

If a reviewer raised points beyond the automated rules, record them in a YAML file:

```yaml
feedback:
  - rule_id: CTL-LAYOUT-004            # optional: ties the comment to a rule
    target_id: "Dashboard A:zone-20"   # optional: ties it to an object
    author: A. Shi
    raised_on: 2026-11-07
    comment: Increase the padding around the KPI tiles.

  - author: P. Vijayakumar
    comment: Confirm the Cotality logomark is in the upper left corner.
```

Pass it with `--sme-feedback sme_feedback.yaml`. Comments tied to a `rule_id` are
verified automatically; the rest appear on an **SME Feedback** tab marked
`CANNOT_VERIFY` for the reviewer to confirm by hand.

---

## 6. Files currently in the repository

### 6.1 Real inputs supplied by stakeholders

| File | What it is |
|---|---|
| `6th_oct_newfiles/Draft-Tableau Design & Performance Guide.docx` | **The standard (v3.0).** Source of every rule |
| `6th_oct_newfiles/draft Tableau Dashboard Review - [Report Name].xlsx` | **The checklist template**, including the new *Agent Review* tab. Used at runtime as the Excel output template |
| `27th_oct_new_files/Model Performance Dashboard.XML` | **The real workbook under review.** 3 dashboards, 21 worksheets, 59 calculated fields |
| `27th_oct_new_files/Tableau_Compliance_Review_Report.docx` | A human/Gemini review of the same workbook — used to validate the agent's findings |

### 6.2 Files generated for testing — NOT review artifacts

> **These are listed explicitly because they must not be mistaken for deliverables.**

| File | Why it exists |
|---|---|
| `27th_oct_new_files/Model Performance Dashboard_Remediated_v3.XML` | **Simulated "fixed" workbook.** No stakeholder has yet returned a revised XML, so this was generated by `scripts/apply_v3_remediation.py` to prove Agent 2 works end to end. Delete it once a real revision arrives |
| `27th_oct_new_files/Model Performance Dashboard_Remediated.XML` | Earlier simulated revision (superseded) |
| `27th_oct_new_files/sme_feedback_from_review_report.yaml` | SME comments **transcribed by hand** from the compliance review `.docx`, to exercise the feedback path |
| `tests/fixtures/**` | 90+ miniature workbooks, each isolating one rule, plus XXE / billion-laughs security fixtures |

**What "simulated" means precisely:** the remediated XML is the real workbook with
scripted edits applied — views consolidated, padding set to 20px/12px, palettes swapped
to Cotality colours, Apply buttons enabled, spelling corrected, floating objects docked.
Each edit maps to a specific rule finding. It behaves like a genuine developer fix, but
**no developer produced it**, so its post-review report is a demonstration, not a QC
record.

### 6.3 Reports produced to date

| File | Status |
|---|---|
| `output/ModelPerformanceDashboard_prereview_2026-11-07_pre_review.{json,xlsx,pdf}` | **Genuine review artifact** of the real workbook |
| `output/ModelPerformanceDashboard_postreview_2026-11-07_post_review.{…}` | Demonstration only — run against the simulated revision |

---

## 7. Results on the current workbook

`Model Performance Dashboard.XML` · SHA-256 `aa610f1739c8…` · **Overall: FAIL**
204 findings — 145 PASS, 46 FAIL, 13 ADVISORY, 0 MANUAL.

**Agent Review tab — all 19 questions answered:**

| Verdict | Count | Items |
|---|---|---|
| **PASS** | 8 | Metadata complete · Arial fonts · View ordering · Axis labels · Interactivity instructions · Custom SQL · Filter cardinality · Sheet hygiene |
| **FAIL** | 8 | Brand colours (`tableau20_10_0` palette) · View count (7 and 11, limit 6) · Red/green accessibility · Padding below 10px · Text sizes 9pt & 22pt · Floating containers · Spelling & naming · 5 filters missing Apply button |
| **ADVISORY** | 3 | Logo (position verified, image needs eyes) · Font-size consistency · Gridlines/banding |

Every finding was independently corroborated by the human compliance review.

---

## 8. Changing the standards (no code required)

Rules live in `config/rules/*.yaml`. To change a threshold, edit the YAML:

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
        value: 6                      # ← change the limit here
    recommendation: >
      Reduce the dashboard to at most 6 views.
```

Validate after any edit:

```bash
.venv/bin/tableau-qc rules       # schema-validates and lists every rule
.venv/bin/python -m pytest tests -q
```

Checklist questions map to rules in `config/checklist/agent_review.yaml` and
`tech_review.yaml`. Adding a row to the spreadsheet means adding a matching entry there.

### 8.1 Content standards are YAML too

Word lists and tolerances that encode a Cotality decision live in
`config/standards/content.yaml`, not in code. A reviewer can edit any of these:

| Setting | Controls |
|---|---|
| `misspellings` | The spell-check word list (41 entries) |
| `metadata_elements` | Phrases that prove the data update date / contact / owner are present |
| `interactivity_phrases` | Words that count as usage instructions |
| `naming_defect_patterns` | What makes a name "technical" rather than business-friendly |
| `logo.upper_left_max_*` | How far from the corner a logo may sit |

Tableau *facts* — such as which `type-v2` values are layout containers — stay in code,
because they describe the file format rather than a Cotality standard.

### 8.2 Mistakes are caught when the rules load, not on a workbook

The repository is semantically validated at load time. These all fail immediately with a
message naming the rule:

| Mistake | Message |
|---|---|
| `field: siz.widht` | `'siz' does not exist on Dashboard` |
| `operator: between` with a single value | `requires a list of exactly two bounds` |
| `operator: in` with a scalar | `requires a list value` |
| `operator: matches` with a broken regex | `invalid regular expression` |
| Two assertions on the same field | `duplicate assertion on field …` |
| `checklist_ref` pointing at a missing cell | reported by `tableau-qc rules` |

---

## 9. What will always need a human

These are not gaps to be closed — the information does not exist in a workbook file, and
**adding an LLM does not change that**, because an LLM reading the XML is bounded by the
same information.

| Check | Why |
|---|---|
| Dashboard loads in under 8 seconds | A runtime measurement; needs a live server |
| Logo is the correct image and legible | The XML stores the *filename*, not the image. Position and filename are verified; the picture is not |
| Metadata values are correct | Presence of "Data Last Updated / Contact / Owner" is verified; whether the date is current is not |
| Filters and actions behave correctly | Structural integrity is checked; runtime behaviour is not |
| Filter has too many unique values | The values live in the Hyper extract, not the workbook |
| Business-friendly naming, tooltip usefulness | Mechanical defects are detected and reported as **ADVISORY**; quality of language is a judgement |

The entire **Peer Review** tab is deliberately out of scope — it is a human sign-off
instrument covering audience fit, requirements and data accuracy.

### Known gap in the checklist itself

The redesigned checklist has **no dashboard-size question**. `CTL-LAYOUT-001` and
`CTL-LAYOUT-002` (1600×900) are still enforced and appear in `QC Findings` and the PDF,
but they answer no checklist cell. `tableau-qc rules` reports this explicitly as
`NOTE  enforced but not on the checklist`. If a size row is added to the spreadsheet,
add a `checklist_ref` to both rules.

---

## 10. Configuration map

Everything a reviewer can change without a developer:

```
config/
├── rules/                      27 QC rules
│   ├── layout.yaml             size, view count, padding
│   ├── typography.yaml         fonts and text sizes
│   ├── colour.yaml             brand palette, accessibility
│   ├── structure.yaml          tiling, logo, view ordering
│   ├── content.yaml            metadata, instructions, naming, spelling
│   ├── charts.yaml             gridlines, labels
│   └── performance.yaml        optimizer, filters, custom SQL, hygiene
├── checklist/                  question -> rule mapping
│   ├── agent_review.yaml       Agent Review tab (19 questions)
│   └── tech_review.yaml        Tech Review tab (24 questions)
└── standards/
    └── content.yaml            word lists, label phrases, tolerances
```

Environment overrides: `TABLEAU_QC_RULES_DIR`, `TABLEAU_QC_CHECKLIST`,
`TABLEAU_QC_STANDARDS`, `TABLEAU_QC_EXCEL_TEMPLATE`, `TABLEAU_QC_OUTPUT_DIR`.

---

## 11. Quick reference

```bash
# Setup (once)
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# List all active rules
.venv/bin/tableau-qc rules

# AGENT 1 — review a new workbook
.venv/bin/tableau-qc pre-review "incoming/MyDashboard.xml" --pdf \
    --basename MyDashboard_prereview_2026-11-07

# AGENT 2 — verify the developer's fixes
.venv/bin/tableau-qc post-review "incoming/MyDashboard_v2.xml" \
    --previous-audit "output/MyDashboard_prereview_2026-11-07_pre_review.json" \
    --baseline-xml "incoming/MyDashboard.xml" \
    --sme-feedback "sme_feedback.yaml" \
    --pdf --basename MyDashboard_postreview_2026-11-07

# Validate the rule repository against the checklist (CI-friendly)
.venv/bin/tableau-qc rules --strict

# Run the test suite (444 tests)
.venv/bin/python -m pytest tests -q
```

**Golden rules**

1. Keep the Agent 1 **JSON** — Agent 2 needs it.
2. Never delete `tests/fixtures/` — the test suite depends on it.
3. Files named `*_Remediated*` are **simulated**, not review artifacts.
4. `ADVISORY` is not a pass. A human decides.

---

## 12. Assurance

- **444 automated tests**, all passing.
- **Every rule has a passing and a failing fixture**, so no rule can silently stop working.
- **Deterministic** — identical input always produces identical output; verified by test.
- **Every automated PASS/FAIL carries evidence**: field, expected, observed and XPath.
- **Security tested** against XXE, billion-laughs, external DTD and malformed input.
- **Every parser has a dedicated unit-test module** (9 of 9).
- **Rules are semantically validated at load time** — field paths, operator/value
  compatibility and checklist references.
- **No review standard is hard-coded in Python** — thresholds, word lists and label
  phrases all live in `config/`.
- **No workbook XML is ever sent to an LLM.** LLM enrichment is optional, off by default,
  and can only add advisory text — it can never change an objective result.

---

## Appendix A — The 27 rules

| Rule ID | Severity | Scope | Checks |
|---------|----------|-------|--------|
| `CTL-LAYOUT-001` | HIGH | dashboard | Width is 1600 px |
| `CTL-LAYOUT-002` | HIGH | dashboard | Height is 900 px |
| `CTL-LAYOUT-003` | HIGH | dashboard | No more than 6 views |
| `CTL-LAYOUT-004` | MEDIUM | view zone | At least 10 px outer and inner padding |
| `CTL-TYPO-001` | HIGH | workbook | Arial / Arial Black only |
| `CTL-TYPO-002` | MEDIUM | workbook | Text sizes within the guide bands |
| `CTL-TYPO-003` | MEDIUM | workbook | One font size per text category *(advisory)* |
| `CTL-COLOR-001` | HIGH | workbook | Cotality brand palettes only |
| `CTL-COLOR-002` | HIGH | mark palette | No red/green in one view |
| `CTL-COLOR-003` | MEDIUM | mark palette | 1-2 dominant colours *(advisory)* |
| `CTL-STRUCT-001` | MEDIUM | dashboard | Tiled containers over floating |
| `CTL-STRUCT-002` | HIGH | dashboard | Logo in the upper-left corner |
| `CTL-STRUCT-003` | LOW | image | No placeholder asset names *(advisory)* |
| `CTL-STRUCT-004` | LOW | dashboard | Summary above detail *(advisory)* |
| `CTL-CONTENT-001` | HIGH | workbook | Metadata complete |
| `CTL-CONTENT-002` | MEDIUM | workbook | Interactivity instructions *(advisory)* |
| `CTL-CONTENT-003` | MEDIUM | workbook | No spelling errors |
| `CTL-CONTENT-004` | MEDIUM | workbook | Business-friendly names *(advisory)* |
| `CTL-CONTENT-005` | MEDIUM | workbook | No raw calculation refs in tooltips *(advisory)* |
| `CTL-CHART-001` | LOW | workbook | Gridlines and banding reduced *(advisory)* |
| `CTL-CHART-002` | LOW | worksheet | Labels or axes, not both *(advisory)* |
| `CTL-PERF-001` | HIGH | workbook | No suppressed Workbook Optimizer rules |
| `CTL-PERF-002` | MEDIUM | filter zone | Apply button on multi-select filters |
| `CTL-PERF-003` | MEDIUM | filter zone | Avoid enumerated high-cardinality filters *(advisory)* |
| `CTL-PERF-004` | HIGH | workbook | No custom SQL on live connections |
| `CTL-HYG-001` | MEDIUM | workbook | Unused worksheets deleted |
| `CTL-HYG-002` | LOW | worksheet | Used worksheets hidden |

## Appendix B — Checklist coverage

| Row | Question | Rules | Verdict type |
|-----|----------|-------|--------------|
| AR-05 | Logo upper-left, visible | `CTL-STRUCT-002/003` | Automated + residual visual check |
| AR-06 | Metadata complete | `CTL-CONTENT-001` | Automated + residual value check |
| AR-07 | Arial font throughout | `CTL-TYPO-001` | Fully automated |
| AR-08 | Cotality branding colours | `CTL-COLOR-001` | Fully automated |
| AR-10 | No more than 6 views | `CTL-LAYOUT-003` | Fully automated |
| AR-11 | Effective colour usage, accessibility | `CTL-COLOR-002/003` | Fully automated |
| AR-12 | Views organised by importance | `CTL-STRUCT-004` | Advisory (geometry heuristic) |
| AR-13 | Minimum 10px padding | `CTL-LAYOUT-004` | Fully automated |
| AR-14 | Text size follows guide | `CTL-TYPO-002` | Fully automated |
| AR-15 | Consistent font sizes per category | `CTL-TYPO-003` | Advisory |
| AR-16 | Gridlines and banding reduced | `CTL-CHART-001` | Advisory |
| AR-17 | Concise horizontal x-axis labels | `CTL-CHART-002` | Advisory + residual visual check |
| AR-18 | Tiled over floating containers | `CTL-STRUCT-001` | Fully automated |
| AR-19 | Directions on interactivity | `CTL-CONTENT-002` | Advisory + residual check |
| AR-20 | Business-friendly names, spelling | `CTL-CONTENT-003/004/005` | Automated (spelling) + advisory (naming) |
| AR-22 | Limit custom SQL on live connections | `CTL-PERF-004` | Fully automated |
| AR-23 | Show Apply Button on multi-select | `CTL-PERF-002` | Fully automated |
| AR-24 | Avoid high-cardinality filter lists | `CTL-PERF-003` | Advisory + residual cardinality check |
| AR-25 | Close unneeded / hide used sheets | `CTL-HYG-001/002` | Fully automated |
