"""Reproducible scan evidence and explicit human verification state."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from dataforge.detectors import Finding


@dataclass(frozen=True)
class EvidencePack:
    run_id: str
    source_snapshots: Mapping[str, str]
    schema_versions: Mapping[str, str]
    findings: Sequence[Finding]
    owner: str = ""
    status: str = "ADVISORY"
    reviewer: str = ""
    rationale: str = ""

    @property
    def input_hash(self) -> str:
        payload = {
            "run_id": self.run_id,
            "source_snapshots": dict(sorted(self.source_snapshots.items())),
            "schema_versions": dict(sorted(self.schema_versions.items())),
            # detected_at is presentation metadata and must not make the same
            # source population hash differently across repeated runs.
            "findings": [{key: value for key, value in finding.to_dict().items() if key != "detected_at"} for finding in self.findings],
        }
        return sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()

    @property
    def blocking_findings(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity.value == "critical"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "input_hash": self.input_hash,
            "source_snapshots": dict(self.source_snapshots),
            "schema_versions": dict(self.schema_versions),
            "findings": [finding.to_dict() for finding in self.findings],
            "owner": self.owner,
            "status": self.status,
            "reviewer": self.reviewer,
            "rationale": self.rationale,
        }

    def lock(self, reviewer: str, rationale: str) -> "EvidencePack":
        if self.status != "PROVISIONAL_LOCK":
            raise ValueError("Only PROVISIONAL_LOCK evidence can be locked.")
        if not reviewer.strip() or not rationale.strip():
            raise ValueError("A reviewer and rationale are required.")
        return replace(self, status="LOCKED", reviewer=reviewer, rationale=rationale)


def build_evidence_pack(
    run_id: str,
    findings: Sequence[Finding],
    source_snapshots: Mapping[str, str],
    schema_versions: Mapping[str, str],
    owner: str = "",
) -> EvidencePack:
    blocking = any(finding.severity.value == "critical" for finding in findings)
    status = "HALT" if blocking else "PROVISIONAL_LOCK" if owner else "ADVISORY"
    return EvidencePack(run_id, source_snapshots, schema_versions, findings, owner=owner, status=status)
