"""Feature distribution-shift detector.

Computes Population Stability Index (PSI) and a two-sample Kolmogorov-Smirnov
statistic between the current feature distribution and a stored reference
(baseline) distribution. PSI > 0.25 is conventionally considered a major shift;
we default to 0.20 (warning) for hackathon demo sensitivity.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np
from scipy import stats

from dataforge.config import Severity, get_settings
from dataforge.detectors import Finding, FindingType

log = logging.getLogger(__name__)


def _state_path(feature_id: str) -> Path:
    safe = feature_id.replace(":", "_").replace("/", "_")
    settings = get_settings()
    p = settings.state_dir / "distributions" / f"{safe}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_reference(feature_id: str) -> Optional[list[float]]:
    p = _state_path(feature_id)
    if not p.exists():
        return None
    return json.loads(p.read_text()).get("values")


def _save_reference(feature_id: str, values: list[float]) -> None:
    p = _state_path(feature_id)
    p.write_text(json.dumps({"values": list(values)}))


def _psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    """Compute Population Stability Index.

    PSI = sum( (actual_pct - expected_pct) * ln(actual_pct / expected_pct) )
    """
    eps = 1e-6
    breakpoints = np.linspace(min(expected.min(), actual.min()), max(expected.max(), actual.max()), bins + 1)
    breakpoints[0] = -np.inf
    breakpoints[-1] = np.inf
    expected_pct = np.histogram(expected, bins=breakpoints)[0] / len(expected) + eps
    actual_pct = np.histogram(actual, bins=breakpoints)[0] / len(actual) + eps
    return float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))


def detect_distribution_shift(
    feature_id: str,
    current_values: list[float],
    reference_values: Optional[list[float]] = None,
) -> Optional[Finding]:
    """Return a Finding if the feature distribution has shifted."""
    settings = get_settings()

    if reference_values is None:
        reference_values = _load_reference(feature_id)

    if reference_values is None or len(reference_values) < 30:
        log.info("No reference distribution for %s; storing current as baseline", feature_id)
        _save_reference(feature_id, current_values)
        return None

    ref = np.asarray(reference_values, dtype=float)
    cur = np.asarray(current_values, dtype=float)

    psi_value = _psi(ref, cur)
    ks_stat, ks_pvalue = stats.ks_2samp(ref, cur)

    # Always refresh the reference so future runs compare against the latest baseline.
    # (In production you'd snapshot periodically; for the demo we use a rolling baseline.)
    _save_reference(feature_id, current_values)

    if psi_value < settings.distribution_psi_threshold and ks_pvalue > settings.distribution_ks_pvalue:
        return None

    severity = (
        Severity.CRITICAL if psi_value > settings.distribution_psi_threshold * 2
        else Severity.WARN
    )

    target_urn = f"urn:li:mlFeature:{feature_id}"
    return Finding(
        target_urn=target_urn,
        finding_type=FindingType.DISTRIBUTION_SHIFT,
        severity=severity,
        title=f"Feature distribution shift on {feature_id} (PSI={psi_value:.3f})",
        description=(
            f"Feature {feature_id} shows statistical drift from its reference distribution. "
            f"PSI={psi_value:.3f} (threshold={settings.distribution_psi_threshold}), "
            f"KS p-value={ks_pvalue:.4f} (threshold={settings.distribution_ks_pvalue}). "
            f"This suggests the upstream data-generating process has changed; models "
            f"trained on the prior distribution may produce unreliable predictions."
        ),
        evidence={
            "psi": round(psi_value, 4),
            "ks_statistic": round(float(ks_stat), 4),
            "ks_pvalue": round(float(ks_pvalue), 4),
            "n_reference": len(ref),
            "n_current": len(cur),
            "mean_reference": float(np.mean(ref)),
            "mean_current": float(np.mean(cur)),
        },
        suggested_resolution=(
            "If the shift is expected (e.g. business seasonality): refresh the reference "
            "distribution and bump the model schema version. If unexpected: investigate the "
            "source pipeline for upstream bugs, then retrain + re-validate the model before "
            "serving traffic."
        ),
    )
