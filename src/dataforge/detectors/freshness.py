"""Freshness-drop detector.

Compares each upstream dataset's `lastModified` timestamp against the
configured SLA. If a dataset hasn't been written to within `freshness_sla_hours`,
we surface a Finding that the downstream ML model is consuming stale inputs.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from dataforge.config import Severity, get_settings
from dataforge.datahub_client import DataHubClient
from dataforge.detectors import Finding, FindingType

log = logging.getLogger(__name__)


def detect_freshness_drop(
    client: DataHubClient,
    dataset_urn: str,
    sla_hours: Optional[int] = None,
) -> Optional[Finding]:
    """Return a Finding if the dataset is older than SLA, else None."""
    settings = get_settings()
    sla_seconds = (sla_hours or settings.freshness_sla_hours) * 3600

    last_modified_ms = client.get_dataset_freshness(dataset_urn)
    if last_modified_ms is None:
        log.debug("No freshness info for %s; skipping", dataset_urn)
        return None

    age_seconds = (time.time() * 1000 - last_modified_ms) / 1000.0
    if age_seconds < sla_seconds:
        return None

    age_hours = age_seconds / 3600.0
    severity = (
        Severity.CRITICAL if age_hours > sla_seconds * 2 / 3600
        else Severity.WARN
    )

    return Finding(
        target_urn=dataset_urn,
        finding_type=FindingType.FRESHNESS_DROP,
        severity=severity,
        title=f"Freshness SLA violation: {dataset_urn.split(':')[-1]} is {age_hours:.1f}h old",
        description=(
            f"Dataset {dataset_urn} has not been updated for {age_hours:.1f} hours, "
            f"exceeding the configured SLA of {settings.freshness_sla_hours}h. "
            f"Downstream ML models trained on this dataset will silently degrade."
        ),
        evidence={
            "last_modified_ms": last_modified_ms,
            "age_hours": round(age_hours, 2),
            "sla_hours": settings.freshness_sla_hours,
        },
        suggested_resolution=(
            "Investigate the upstream pipeline (Airflow / Spark job). Common causes: "
            "(1) source system outage, (2) scheduler paused, (3) silent job failure. "
            "If a known issue, link the incident to the source dataset's upstream."
        ),
    )
