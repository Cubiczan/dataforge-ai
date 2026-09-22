"""DataForge AI - Production ML agent for DataHub lineage observability.

DataForge watches the ML lineage graph in DataHub, detects silent failures
(freshness drops, schema drift, feature distribution shift), and writes
incidents + resolutions back into DataHub so downstream agents inherit
the context.

Apache License 2.0 - Copyright 2026 Cubiczan / Icohangar-Ops
"""
from __future__ import annotations

__version__ = "0.1.0"

from dataforge.config import Settings, get_settings

# Keep deterministic detectors and evidence contracts importable in minimal
# environments; DataHub runtime dependencies are required only by the agent.
try:  # pragma: no cover - depends on optional DataHub installation
    from dataforge.datahub_client import DataHubClient
    from dataforge.agent import DataForgeAgent
except ImportError:  # pragma: no cover
    DataHubClient = None  # type: ignore[assignment,misc]
    DataForgeAgent = None  # type: ignore[assignment,misc]

__all__ = ["__version__", "Settings", "get_settings", "DataHubClient", "DataForgeAgent"]
