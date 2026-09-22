from dataforge.config import Severity
from dataforge.detectors import Finding, FindingType
from dataforge.evidence import build_evidence_pack
from dataforge.incident_lifecycle import IncidentRecord


def finding(severity=Severity.WARN):
    return Finding(
        target_urn="urn:li:dataset:spend",
        finding_type=FindingType.FRESHNESS_DROP,
        severity=severity,
        title="Freshness test",
        description="test finding",
        evidence={"age_hours": 30},
    )


def test_evidence_hash_is_reproducible_and_owner_controls_lock():
    pack = build_evidence_pack("run-1", [finding()], {"spend": "abc"}, {"spend": "v1"})
    assert pack.status == "ADVISORY"
    assert pack.input_hash == pack.input_hash
    owned = build_evidence_pack("run-1", [finding()], {"spend": "abc"}, {"spend": "v1"}, owner="data-owner")
    assert owned.status == "PROVISIONAL_LOCK"
    assert owned.lock("reviewer", "Checked source snapshot and resolution.").status == "LOCKED"


def test_critical_finding_halts_evidence():
    pack = build_evidence_pack("run-2", [finding(Severity.CRITICAL)], {"spend": "abc"}, {"spend": "v1"}, owner="owner")
    assert pack.status == "HALT"


def test_incident_lifecycle():
    incident = IncidentRecord.from_finding("inc-1", finding())
    incident = incident.acknowledge("data-owner").remediate("Refreshed the source.")
    assert incident.verify().status == "VERIFIED"
