"""DataHub-independent incident lifecycle used by writers and tests."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from dataforge.detectors import Finding


@dataclass(frozen=True)
class IncidentRecord:
    incident_id: str
    finding: Finding
    status: str = "OPEN"
    owner: str = ""
    resolution: str = ""
    verified_at: str = ""

    @classmethod
    def from_finding(cls, incident_id: str, finding: Finding) -> "IncidentRecord":
        return cls(incident_id=incident_id, finding=finding)

    def acknowledge(self, owner: str) -> "IncidentRecord":
        if self.status != "OPEN" or not owner.strip():
            raise ValueError("An OPEN incident requires a named owner.")
        return replace(self, status="ACKNOWLEDGED", owner=owner)

    def remediate(self, resolution: str) -> "IncidentRecord":
        if self.status not in {"OPEN", "ACKNOWLEDGED"} or not resolution.strip():
            raise ValueError("An open incident requires a resolution.")
        return replace(self, status="REMEDIATED", resolution=resolution)

    def verify(self) -> "IncidentRecord":
        if self.status != "REMEDIATED":
            raise ValueError("Only REMEDIATED incidents can be verified.")
        return replace(self, status="VERIFIED", verified_at=datetime.now(timezone.utc).isoformat())
