"""DataHub REST/GraphQL client wrapper.

Wraps the official `acryl-datahub` REST emitter + a small GraphQL helper for
queries that the Python SDK does not yet expose (lineage traversal, incident
aspects). Designed to work against `datahub docker quickstart` out of the box.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from datahub.emitter.mce_builder import make_dataset_urn, make_ml_model_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    DataHubIncidentPropertiesClass,
    IncidentTypeClass,
    FreshnessAssertionInfoClass,
)
from tenacity import retry, stop_after_attempt, wait_exponential

from dataforge.config import Settings, get_settings

log = logging.getLogger(__name__)


@dataclass
class LineageNode:
    """A node in the ML lineage graph returned by DataHub."""

    urn: str
    entity_type: str  # dataset | mlModel | mlFeatureGroup | mlModelDeployment
    name: str
    platform: Optional[str] = None
    upstreams: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.upstreams is None:
            self.upstreams = []


class DataHubClient:
    """Thin wrapper over DataHub GMS REST + GraphQL APIs."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._http = httpx.Client(
            base_url=self.settings.datahub_gms_url,
            headers=self.settings.gms_auth_header,
            timeout=30.0,
        )

    # ----------------------------------------------------------------- core

    def health(self) -> bool:
        """Return True if GMS /health endpoint returns 200."""
        try:
            r = self._http.get("/health")
            return r.status_code == 200
        except httpx.HTTPError as exc:
            log.error("DataHub health check failed: %s", exc)
            return False

    # ---------------------------------------------------- lineage traversal

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def get_downstream_lineage(self, urn: str, depth: int = 3) -> list[LineageNode]:
        """Walk downstream lineage of an entity (what depends on this urn)."""
        query = """
        query downstreamLineage($urn: String!, $depth: Int!) {
          entity(urn: $urn) {
            ... on Dataset {
              downstreamRelationships(input: { start: 0, count: 100 }) {
                relationships {
                  entity { urn type ... on Dataset { name platform { name } } }
                }
              }
            }
            ... on MLModel {
              downstreamRelationships(input: { start: 0, count: 100 }) {
                relationships {
                  entity { urn type ... on MLModel { name } }
                }
              }
            }
          }
        }
        """
        payload = {"query": query, "variables": {"urn": urn, "depth": depth}}
        r = self._http.post("/api/graphql", json=payload)
        r.raise_for_status()
        data = r.json()
        return self._parse_lineage(data, urn)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def get_upstream_lineage(self, urn: str, depth: int = 3) -> list[LineageNode]:
        """Walk upstream lineage (what this urn depends on)."""
        query = """
        query upstreamLineage($urn: String!, $depth: Int!) {
          entity(urn: $urn) {
            ... on Dataset {
              upstreamRelationships(input: { start: 0, count: 100 }) {
                relationships {
                  entity { urn type ... on Dataset { name platform { name } } }
                }
              }
            }
            ... on MLModel {
              upstreamRelationships(input: { start: 0, count: 100 }) {
                relationships {
                  entity { urn type ... on Dataset { name } ... on MLFeatureGroup { name } }
                }
              }
            }
          }
        }
        """
        payload = {"query": query, "variables": {"urn": urn, "depth": depth}}
        r = self._http.post("/api/graphql", json=payload)
        r.raise_for_status()
        return self._parse_lineage(r.json(), urn)

    def _parse_lineage(self, data: dict[str, Any], root_urn: str) -> list[LineageNode]:
        nodes: list[LineageNode] = []
        entity = data.get("data", {}).get("entity") or {}
        for rel_key in ("upstreamRelationships", "downstreamRelationships"):
            rels = entity.get(rel_key, {}).get("relationships", []) if rel_key in entity else []
            for rel in rels:
                e = rel.get("entity", {})
                nodes.append(
                    LineageNode(
                        urn=e["urn"],
                        entity_type=e.get("type", "dataset"),
                        name=e.get("name", e["urn"]),
                        platform=(e.get("platform") or {}).get("name"),
                    )
                )
        return nodes

    # ------------------------------------------------------- dataset metadata

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def get_dataset_schema(self, dataset_urn: str) -> dict[str, Any]:
        """Return the schemaMetadata aspect for a dataset (or {} if absent)."""
        query = """
        query datasetSchema($urn: String!) {
          dataset(urn: $urn) {
            schemaMetadata(version: 0) {
              name
              platformSchema { platformSchema }
              fields { fieldPath type { type } nullable }
            }
          }
        }
        """
        r = self._http.post(
            "/api/graphql",
            json={"query": query, "variables": {"urn": dataset_urn}},
        )
        r.raise_for_status()
        ds = r.json().get("data", {}).get("dataset") or {}
        return ds.get("schemaMetadata") or {}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def get_dataset_freshness(self, dataset_urn: str) -> Optional[float]:
        """Return most recent `lastModified` timestamp (epoch ms) or None."""
        query = """
        query datasetFreshness($urn: String!) {
          dataset(urn: $urn) {
            browsePathV2 { path { name } }
            institutionalMemory { elements { url } }
          }
        }
        """
        # Freshness in DataHub is typically surfaced via DatasetProperties.lastModified
        # which the GraphQL layer exposes differently per version. We fall back to
        # the REST aspect endpoint to remain stable across DataHub releases.
        r = self._http.get(
            "/openapi/v1/dataset/{urn}/datasetProperties".format(urn=dataset_urn.replace("urn:li:dataset:(urn:li:dataPlatform:", "").replace(")", "")),
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        props = r.json().get("datasetProperties") or {}
        ts = props.get("lastModified", {}).get("time")
        return float(ts) if ts else None

    # ------------------------------------------------------------- incidents

    def raise_incident(
        self,
        *,
        target_urn: str,
        incident_type: str,
        title: str,
        description: str,
        severity: str = "WARN",
        actor: str = "urn:li:corpuser:dataforge-ai",
    ) -> str:
        """Write a DataHubIncidentProperties aspect to the graph.

        Returns the incident urn (urn:li:incident:<uuid>).
        """
        if self.settings.agent_dry_run:
            log.info("[DRY-RUN] Would raise incident on %s: %s", target_urn, title)
            return "urn:li:incident:dry-run"

        from uuid import uuid4
        incident_urn = f"urn:li:incident:{uuid4()}"

        props = DataHubIncidentPropertiesClass(
            type=incident_type,
            severity=severity,
            title=title,
            description=description,
            status=IncidentTypeClass.ACTIVE,
            createdAt=int(__import__("time").time() * 1000),
            createdBy=actor,
        )
        mcp = MetadataChangeProposalWrapper(
            entityUrn=target_urn,
            aspect=props,
        )
        # Use the official emitter rather than raw REST so aspect serialization is correct.
        from datahub.emitter.rest_emitter import DatahubRestEmitter
        emitter = DatahubRestEmitter(
            gms_server=self.settings.datahub_gms_url,
            token=self.settings.datahub_gms_token,
        )
        emitter.emit_mcp(mcp)
        log.info("Raised incident %s on %s", incident_urn, target_urn)
        return incident_urn

    def resolve_incident(self, incident_urn: str, resolution_note: str) -> bool:
        """Mark an active incident as RESOLVED with a note."""
        if self.settings.agent_dry_run:
            log.info("[DRY-RUN] Would resolve %s: %s", incident_urn, resolution_note)
            return True

        props = DataHubIncidentPropertiesClass(
            status=IncidentTypeClass.RESOLVED,
            resolution=resolution_note,
            resolvedAt=int(__import__("time").time() * 1000),
        )
        from datahub.emitter.rest_emitter import DatahubRestEmitter
        emitter = DatahubRestEmitter(
            gms_server=self.settings.datahub_gms_url,
            token=self.settings.datahub_gms_token,
        )
        mcp = MetadataChangeProposalWrapper(entityUrn=incident_urn, aspect=props)
        emitter.emit_mcp(mcp)
        log.info("Resolved incident %s", incident_urn)
        return True

    # --------------------------------------------------------- ML model lookup

    def list_ml_models(self) -> list[LineageNode]:
        """List all MLModel entities registered in DataHub."""
        query = """
        query listMLModels($input: ListMLModelsInput!) {
          listMLModels(input: $input) {
            models { urn name }
          }
        }
        """
        r = self._http.post(
            "/api/graphql",
            json={"query": query, "variables": {"input": {"start": 0, "count": 100}}},
        )
        r.raise_for_status()
        models = (r.json().get("data") or {}).get("listMLModels", {}).get("models", [])
        return [
            LineageNode(urn=m["urn"], entity_type="mlModel", name=m.get("name", m["urn"]))
            for m in models
        ]

    # --------------------------------------------------------------- closeout

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "DataHubClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
