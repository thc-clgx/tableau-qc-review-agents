"""Optional LLM integration.

Hard constraints enforced here:

* LLM usage is opt-in (``TABLEAU_QC_LLM_ENABLED``) and disabled by default.
* Only compact finding summaries are ever sent - never workbook XML.
* LLM output is advisory text only; it cannot change a PASS/FAIL outcome.
"""

from __future__ import annotations

import re
from typing import Dict, List, Protocol, Sequence, runtime_checkable

from ..domain.findings import Finding

#: Anything that looks like markup is refused before leaving the process.
_XML_PATTERN = re.compile(r"<\s*/?\s*[a-zA-Z][\w:.-]*[^>]*>")

MAX_SUMMARY_CHARS = 400


class LLMPayloadError(Exception):
    """Raised when a payload would leak raw workbook XML."""


@runtime_checkable
class LLMProvider(Protocol):
    """Interface implemented by optional LLM back ends."""

    @property
    def enabled(self) -> bool:  # pragma: no cover - protocol declaration
        ...

    def suggest(self, payload: List[Dict[str, str]]) -> Dict[str, str]:  # pragma: no cover
        """Return ``{finding_key: advisory text}``."""
        ...


class NullLLMProvider:
    """Default provider: performs no network calls and returns nothing."""

    @property
    def enabled(self) -> bool:
        return False

    def suggest(self, payload: List[Dict[str, str]]) -> Dict[str, str]:
        return {}


def _scrub(text: str) -> str:
    collapsed = " ".join(str(text).split())
    if _XML_PATTERN.search(collapsed):
        raise LLMPayloadError("Refusing to send XML markup to an LLM provider")
    return collapsed[:MAX_SUMMARY_CHARS]


def build_llm_payload(findings: Sequence[Finding]) -> List[Dict[str, str]]:
    """Build the minimal, XML-free payload describing each finding."""
    payload: List[Dict[str, str]] = []
    for finding in findings:
        evidence = "; ".join(
            f"{e.field_path}={e.observed!r} expected {e.operator} {e.expected!r}"
            for e in finding.evidence
            if e.note != "context"
        )
        payload.append(
            {
                "finding_key": finding.key,
                "rule_id": finding.rule_id,
                "title": _scrub(finding.title),
                "status": finding.status.value,
                "severity": finding.severity.value,
                "target": _scrub(finding.target_name or finding.target_id),
                "evidence": _scrub(evidence),
            }
        )
    return payload
