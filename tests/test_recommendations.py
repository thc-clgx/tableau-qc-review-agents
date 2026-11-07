"""Tests for the recommendation layer and optional LLM integration."""

from __future__ import annotations

import pytest

from conftest import parse_fixture
from tableau_qc.domain.findings import Status
from tableau_qc.recommendations.engine import RecommendationEngine
from tableau_qc.recommendations.llm import (
    LLMPayloadError,
    NullLLMProvider,
    build_llm_payload,
)
from tableau_qc.rules.engine import RuleEngine


class RecordingProvider:
    """Test double that records what it was asked to summarise."""

    def __init__(self) -> None:
        self.payloads = []

    @property
    def enabled(self) -> bool:
        return True

    def suggest(self, payload):
        self.payloads.append(payload)
        return {item["finding_key"]: "Consider the Analytics template." for item in payload}


@pytest.fixture()
def failing_findings(repository, non_compliant_xml_path):
    return RuleEngine(repository).execute(parse_fixture(non_compliant_xml_path))


def test_recommendations_only_for_actionable_findings(repository, compliant_xml_path):
    findings = RuleEngine(repository).execute(parse_fixture(compliant_xml_path))
    assert RecommendationEngine().build(findings) == []


def test_recommendations_are_deterministic(failing_findings):
    engine = RecommendationEngine()
    first = [r.as_dict() for r in engine.build(failing_findings)]
    second = [r.as_dict() for r in engine.build(failing_findings)]
    assert first == second
    assert first


def test_recommendation_contains_evidence_and_target(failing_findings):
    recommendation = RecommendationEngine().build(failing_findings)[0]
    assert recommendation.target
    assert recommendation.evidence
    assert "@" in recommendation.evidence[0]
    assert recommendation.advisory is None


def test_apply_writes_text_back_onto_findings(failing_findings):
    RecommendationEngine().apply(failing_findings)
    failed = [f for f in failing_findings if f.status is Status.FAIL]
    assert all(f.recommendation for f in failed)


def test_llm_disabled_by_default(failing_findings):
    assert NullLLMProvider().enabled is False
    assert NullLLMProvider().suggest([]) == {}
    assert all(r.advisory is None for r in RecommendationEngine().build(failing_findings))


def test_llm_payload_excludes_xml(failing_findings):
    payload = build_llm_payload(failing_findings)
    serialised = str(payload)
    assert "<workbook" not in serialised
    assert "<zone" not in serialised
    assert "xpath" not in serialised
    for item in payload:
        assert set(item) == {
            "finding_key",
            "rule_id",
            "title",
            "status",
            "severity",
            "target",
            "evidence",
        }


def test_llm_payload_refuses_markup():
    from tableau_qc.domain.findings import Finding

    finding = Finding(
        rule_id="CTL-TEST-001",
        title="<zone id='1'>injected</zone>",
        status=Status.FAIL,
        target_type="dashboard",
        target_id="D",
    )
    with pytest.raises(LLMPayloadError):
        build_llm_payload([finding])


def test_optional_provider_adds_advisory_without_changing_status(failing_findings):
    provider = RecordingProvider()
    engine = RecommendationEngine(provider)
    recommendations = engine.apply(failing_findings)
    assert provider.payloads
    advisory_findings = [f for f in recommendations if f.status is Status.FAIL]
    assert all("advisory" in f.recommendation for f in advisory_findings)
    assert all(f.status is Status.FAIL for f in advisory_findings)
