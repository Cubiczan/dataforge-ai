"""Detectors for silent ML failures.

Each detector returns a `Finding` (or None if healthy). The agent loop
collects findings, drafts incidents via the LLM, and writes them to DataHub.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from dataforge.config import Severity


class FindingType(str, Enum):
    FRESHNESS_DROP = "freshness_drop"
    SCHEMA_DRIFT = "schema_drift"
    DISTRIBUTION_SHIFT = "distribution_shift"


@dataclass
class Finding:
    """A detected silent failure ready to be turned into a DataHub incident."""

    target_urn: str
    finding_type: FindingType
    severity: Severity
    title: str
    description: str
    evidence: dict[str, Any] = field(default_factory=dict)
    suggested_resolution: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_urn": self.target_urn,
            "finding_type": self.finding_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "evidence": self.evidence,
            "suggested_resolution": self.suggested_resolution,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }
