"""Schema-drift detector.

Captures the latest schemaMetadata aspect for a dataset and compares it
against the previously observed schema (stored in DataForge's local state).
Flags any added/removed/retyped field so downstream consumers can decide
whether to retrain or pin a feature schema version.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from dataforge.config import Severity, get_settings
from dataforge.datahub_client import DataHubClient
from dataforge.detectors import Finding, FindingType

log = logging.getLogger(__name__)


def _state_path(dataset_urn: str) -> Path:
    safe = dataset_urn.replace(":", "_").replace("(", "_").replace(")", "_")
    settings = get_settings()
    p = settings.state_dir / "schemas" / f"{safe}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_prior_schema(dataset_urn: str) -> dict:
    p = _state_path(dataset_urn)
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def _save_current_schema(dataset_urn: str, schema: dict) -> None:
    p = _state_path(dataset_urn)
    p.write_text(json.dumps(schema, indent=2, sort_keys=True))


def _diff_schemas(prior: dict, current: dict) -> dict:
    prior_fields = {f["fieldPath"]: f.get("type", {}).get("type", "unknown") for f in prior.get("fields", [])}
    current_fields = {f["fieldPath"]: f.get("type", {}).get("type", "unknown") for f in current.get("fields", [])}

    added = sorted(set(current_fields) - set(prior_fields))
    removed = sorted(set(prior_fields) - set(current_fields))
    retyped = sorted(
        f for f in (set(prior_fields) & set(current_fields))
        if prior_fields[f] != current_fields[f]
    )
    return {"added": added, "removed": removed, "retyped": retyped}


def detect_schema_drift(
    client: DataHubClient,
    dataset_urn: str,
) -> Optional[Finding]:
    """Return a Finding if the dataset schema has drifted since last check."""
    current = client.get_dataset_schema(dataset_urn)
    if not current or not current.get("fields"):
        log.debug("No schema metadata for %s; skipping", dataset_urn)
        return None

    prior = _load_prior_schema(dataset_urn)
    _save_current_schema(dataset_urn, current)

    if not prior:
        # First observation: baseline, no drift
        return None

    diff = _diff_schemas(prior, current)
    if not (diff["added"] or diff["removed"] or diff["retyped"]):
        return None

    settings = get_settings()
    severity = settings.schema_drift_severity
    if diff["removed"] or diff["retyped"]:
        # Removing fields or changing types is high-risk for downstream models
        severity = Severity.CRITICAL

    parts = []
    if diff["added"]:
        parts.append(f"+{len(diff['added'])} new fields: {', '.join(diff['added'][:5])}")
    if diff["removed"]:
        parts.append(f"-{len(diff['removed'])} removed fields: {', '.join(diff['removed'][:5])}")
    if diff["retyped"]:
        parts.append(f"~{len(diff['retyped'])} retyped fields: {', '.join(diff['retyped'][:5])}")

    return Finding(
        target_urn=dataset_urn,
        finding_type=FindingType.SCHEMA_DRIFT,
        severity=severity,
        title=f"Schema drift detected on {dataset_urn.split(':')[-1]}",
        description=(
            f"Dataset {dataset_urn} schema changed since last observation. "
            f"Changes: {'; '.join(parts)}. Downstream feature pipelines and "
            f"ML models depending on this dataset must be re-evaluated."
        ),
        evidence=diff,
        suggested_resolution=(
            "If added fields are expected: pin a feature schema version and notify "
            "downstream model owners. If fields were removed or retyped: block the "
            "deployment of models trained on the prior schema and trigger a retrain."
        ),
    )
