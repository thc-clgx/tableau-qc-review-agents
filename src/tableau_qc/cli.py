"""Command line interface for the Tableau XML dashboard review agents."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from .agents.post_review import PostTechnicalReviewAgent, VerificationInputError
from .agents.pre_review import PreTechnicalReviewAgent
from .checklist import load_checklist
from .rules.loader import load_rules
from .rules.validation import unmapped_rule_ids, validate_checklist_references
from .settings import DEFAULT_CHECKLIST_PATH, DEFAULT_OUTPUT_DIR, DEFAULT_RULES_DIR


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--rules", default=str(DEFAULT_RULES_DIR), help="YAML rule file or directory")
    parser.add_argument(
        "--checklist", default=str(DEFAULT_CHECKLIST_PATH), help="Checklist definition YAML"
    )
    parser.add_argument("--excel-template", default=None, help="Review checklist .xlsx template")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Report output folder")
    parser.add_argument("--basename", default=None, help="Base name for generated report files")
    parser.add_argument("--no-json", action="store_true", help="Skip the JSON report")
    parser.add_argument("--no-excel", action="store_true", help="Skip the Excel report")
    parser.add_argument("--pdf", action="store_true", help="Also write a PDF report")
    parser.add_argument("--rule-id", action="append", default=None, help="Only run these rule ids")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tableau-qc",
        description="Deterministic QC review of Tableau workbook XML against Cotality standards.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    pre = subparsers.add_parser("pre-review", help="Agent 1: pre-technical review of workbook XML")
    pre.add_argument("xml", help="Path to the Tableau workbook XML")
    pre.add_argument("--category", action="append", default=None, help="Only run these categories")
    pre.add_argument("--tag", action="append", default=None, help="Only run rules with these tags")
    _common_arguments(pre)

    post = subparsers.add_parser(
        "post-review", help="Agent 2: verify a revised workbook against previous findings"
    )
    post.add_argument("revised_xml", help="Path to the revised Tableau workbook XML")
    post.add_argument("--baseline-xml", default=None, help="Path to the baseline workbook XML")
    post.add_argument("--previous-audit", default=None, help="Previous audit JSON from Agent 1")
    post.add_argument("--sme-feedback", default=None, help="Optional SME feedback YAML/JSON")
    _common_arguments(post)

    rules = subparsers.add_parser("rules", help="Validate and list the YAML rule repository")
    rules.add_argument("--rules", default=str(DEFAULT_RULES_DIR), help="YAML rule file or directory")
    rules.add_argument(
        "--checklist",
        default=str(DEFAULT_CHECKLIST_PATH),
        help="Checklist definition used to cross-check rule references",
    )
    rules.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any rule is unmapped or references a missing cell",
    )

    return parser


def _run_pre_review(args: argparse.Namespace) -> int:
    agent = PreTechnicalReviewAgent(
        rules_path=args.rules,
        checklist_path=args.checklist,
        excel_template=args.excel_template,
        rule_ids=args.rule_id,
        categories=args.category,
        tags=args.tag,
    )
    report, artifacts = agent.run_and_export(
        args.xml,
        output_dir=args.output_dir,
        basename=args.basename,
        write_json=not args.no_json,
        write_excel=not args.no_excel,
        write_pdf=args.pdf,
    )
    summary = report.summary
    print(f"Workbook       : {report.workbook.get('name')}")
    print(f"Rules evaluated: {summary['rules_evaluated']} ({summary['rules_failed']} failed)")
    print(f"Overall status : {summary['overall_status']}")
    for status, count in summary["by_status"].items():
        print(f"  {status:<16} {count}")
    for label, path in artifacts.as_dict().items():
        if path:
            print(f"{label:<15}: {path}")
    return 1 if summary["overall_status"] == "FAIL" else 0


def _run_post_review(args: argparse.Namespace) -> int:
    agent = PostTechnicalReviewAgent(
        rules_path=args.rules,
        checklist_path=args.checklist,
        excel_template=args.excel_template,
        rule_ids=args.rule_id,
    )
    report, artifacts = agent.run_and_export(
        args.revised_xml,
        baseline_xml=args.baseline_xml,
        previous_audit_json=args.previous_audit,
        sme_feedback_path=args.sme_feedback,
        output_dir=args.output_dir,
        basename=args.basename,
        write_json=not args.no_json,
        write_excel=not args.no_excel,
        write_pdf=args.pdf,
    )
    summary = report.summary
    print(f"Comparisons    : {summary['total_comparisons']}")
    for status, count in summary["by_verification"].items():
        print(f"  {status:<20} {count}")
    print(f"Sign-off ready : {'YES' if summary['sign_off_ready'] else 'NO'}")
    for label, path in artifacts.as_dict().items():
        if path:
            print(f"{label:<15}: {path}")
    return 0 if summary["sign_off_ready"] else 1


def _run_rules(args: argparse.Namespace) -> int:
    repository = load_rules(args.rules)
    print(f"Loaded {len(repository)} rules from {args.rules}")
    for rule in repository:
        state = "enabled" if rule.enabled else "disabled"
        print(f"  {rule.id:<18} [{rule.severity.value:<8}] {rule.scope:<22} {rule.title} ({state})")

    problems: List[str] = []
    checklist = load_checklist(args.checklist) if args.checklist else None
    if checklist is not None:
        cells = [f"{item.sheet}!{item.cell}" for item in checklist.items]
        mapped = {rid for item in checklist.items for rid in item.rule_ids}
        problems = validate_checklist_references(repository, cells)
        unmapped = unmapped_rule_ids(repository, mapped)

        print(f"\nChecklist cross-check against {args.checklist}")
        if problems:
            for problem in problems:
                print(f"  ERROR {problem}")
        else:
            print("  every checklist_ref points at a real question")
        if unmapped:
            print(
                "  NOTE  enforced but not on the checklist: " + ", ".join(unmapped)
            )
        missing = sorted(
            rid for rid in mapped if repository.by_id(rid) is None
        )
        if missing:
            problems.extend(f"checklist references unknown rule '{r}'" for r in missing)
            for rule_id in missing:
                print(f"  ERROR checklist references unknown rule '{rule_id}'")

    return 1 if (problems and args.strict) else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "pre-review":
            return _run_pre_review(args)
        if args.command == "post-review":
            return _run_post_review(args)
        if args.command == "rules":
            return _run_rules(args)
    except (VerificationInputError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.error(f"Unknown command {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
