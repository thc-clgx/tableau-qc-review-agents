"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from tableau_qc.checklist import load_checklist
from tableau_qc.parsers.workbook_parser import WorkbookParser
from tableau_qc.rules.loader import load_rules
from tableau_qc.xmlio.loader import load_xml_file

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
RULE_FIXTURES = FIXTURES / "rules"
SECURITY_FIXTURES = FIXTURES / "security"
CONFIG_RULES = PROJECT_ROOT / "config" / "rules"
CONFIG_CHECKLIST = PROJECT_ROOT / "config" / "checklist"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def rule_fixtures_dir() -> Path:
    return RULE_FIXTURES


@pytest.fixture(scope="session")
def security_fixtures_dir() -> Path:
    return SECURITY_FIXTURES


@pytest.fixture(scope="session")
def sample_xml_path() -> Path:
    return FIXTURES / "sample_workbook.xml"


@pytest.fixture(scope="session")
def compliant_xml_path() -> Path:
    return FIXTURES / "compliant_workbook.xml"


@pytest.fixture(scope="session")
def non_compliant_xml_path() -> Path:
    return FIXTURES / "non_compliant_workbook.xml"


@pytest.fixture(scope="session")
def new_workbook_xml_path() -> Path:
    """Real-world workbook containing CDATA blocks and deep zone nesting."""
    path = PROJECT_ROOT / "examples" / "workbooks" / "Model Performance Dashboard.XML"
    if not path.is_file():
        pytest.skip("Model Performance Dashboard.XML not available")
    return path


@pytest.fixture(scope="session")
def rules_dir() -> Path:
    return CONFIG_RULES


@pytest.fixture(scope="session")
def checklist_path() -> Path:
    return CONFIG_CHECKLIST


@pytest.fixture(scope="session")
def repository():
    return load_rules(CONFIG_RULES)


@pytest.fixture(scope="session")
def checklist_definition():
    return load_checklist(CONFIG_CHECKLIST)


@pytest.fixture(scope="session")
def sample_document(sample_xml_path):
    return load_xml_file(sample_xml_path)


@pytest.fixture(scope="session")
def sample_workbook(sample_document):
    return WorkbookParser(sample_document).parse()


def parse_fixture(path: Path):
    """Parse any fixture XML into the normalised model."""
    return WorkbookParser(load_xml_file(path)).parse()
