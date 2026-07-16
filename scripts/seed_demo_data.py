"""Seed the local DataHub instance with demo metadata.

Two modes:
  --ingest-datapack   Load the nyc-taxi demo metadata via DataHub recipe.
  --plant-freshness-issue  Update a dataset's lastModified to be older than SLA.

This script uses the official DataHub Python SDK to emit MetadataChangeProposal
events directly to GMS - no MCP server required.
"""
from __future__ import annotations

import argparse
import logging
import time
from typing import Optional

from datahub.emitter.mce_builder import (
    make_dataset_urn,
    make_ml_model_urn,
    make_ml_feature_group_urn,
    make_ml_feature_urn,
)
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    SchemaMetadataClass,
    SchemaFieldClass,
    SchemaFieldDataTypeClass,
    StringTypeClass,
    NumberTypeClass,
    DateTypeClass,
    UpstreamLineageClass,
    UpstreamClass,
    DatasetLineageTypeClass,
    MLModelPropertiesClass,
    MLFeaturePropertiesClass,
    MLFeatureGroupPropertiesClass,
)

log = logging.getLogger(__name__)

GMS = "http://localhost:8080"

NYC_RIDES_URN = make_dataset_urn("dbt", "nyc_taxi.rides", "PROD")
NYC_FHV_URN = make_dataset_urn("dbt", "nyc_taxi.fhv", "PROD")
CRITMIN_MODEL_URN = make_ml_model_urn("critmin", "risk-scorer", "v1")
CRITMIN_FEATURE_GROUP_URN = make_ml_feature_group_urn("critmin", "supply-chain-features")


def emit(emitter: DatahubRestEmitter, mcp: MetadataChangeProposalWrapper) -> None:
    emitter.emit_mcp(mcp)
    log.info("emitted %s on %s", mcp.aspect.__class__.__name__, mcp.entityUrn)


def ingest_datapack(emitter: DatahubRestEmitter) -> None:
    """Create demo datasets + ML model + lineage edges."""
    # 1. Datasets with properties (incl. lastModified for freshness check)
    emit(emitter, MetadataChangeProposalWrapper(
        entityUrn=NYC_RIDES_URN,
        aspect=DatasetPropertiesClass(
            name="nyc_taxi.rides",
            description="Yellow taxi ride data (dbt-modeled).",
            uri="bigquery://acme-prod/nyc_taxi.rides",
            tags=["domain:transport", "tier:1"],
            customProperties={"source": "nyc.gov TLC"},
        ),
    ))
    emit(emitter, MetadataChangeProposalWrapper(
        entityUrn=NYC_FHV_URN,
        aspect=DatasetPropertiesClass(
            name="nyc_taxi.fhv",
            description="High-volume for-hire-vehicle rides.",
            uri="bigquery://acme-prod/nyc_taxi.fhv",
            tags=["domain:transport", "tier:2"],
            customProperties={"source": "nyc.gov TLC"},
        ),
    ))

    # 2. Schemas
    rides_schema = SchemaMetadataClass(
        schemaName="nyc_taxi.rides",
        platform="urn:li:dataPlatform:dbt",
        version=0,
        hash="",
        platformSchema={"platformSchema": "dbt"},
        fields=[
            SchemaFieldClass(fieldPath="ride_id", type=SchemaFieldDataTypeClass(NumberTypeClass()), nullable=False),
            SchemaFieldClass(fieldPath="pickup_datetime", type=SchemaFieldDataTypeClass(DateTypeClass()), nullable=False),
            SchemaFieldClass(fieldPath="dropoff_datetime", type=SchemaFieldDataTypeClass(DateTypeClass()), nullable=False),
            SchemaFieldClass(fieldPath="passenger_count", type=SchemaFieldDataTypeClass(NumberTypeClass()), nullable=True),
            SchemaFieldClass(fieldPath="trip_distance", type=SchemaFieldDataTypeClass(NumberTypeClass()), nullable=False),
            SchemaFieldClass(fieldPath="fare_amount", type=SchemaFieldDataTypeClass(NumberTypeClass()), nullable=False),
        ],
    )
    emit(emitter, MetadataChangeProposalWrapper(entityUrn=NYC_RIDES_URN, aspect=rides_schema))

    # 3. ML model (CritMin risk scorer)
    emit(emitter, MetadataChangeProposalWrapper(
        entityUrn=CRITMIN_MODEL_URN,
        aspect=MLModelPropertiesClass(
            name="CritMin Risk Scorer",
            description="NLP-based critical-mineral supply-chain risk score (0-100).",
            externalUrl="https://example.com/critmin",
            version="v1",
            type="XGBoost",
            trainingMetrics={"auc": 0.91, "logloss": 0.24},
        ),
    ))

    # 4. Feature group + features
    emit(emitter, MetadataChangeProposalWrapper(
        entityUrn=CRITMIN_FEATURE_GROUP_URN,
        aspect=MLFeatureGroupPropertiesClass(
            name="supply-chain-features",
            description="NLP features extracted from SEC filings + supply-chain news.",
        ),
    ))

    for fid, desc in [
        ("critmin.sentiment_polarity", "Mean sentiment polarity across SEC filings + news."),
        ("critmin.mineral_mention_count", "Total critical-mineral mentions across corpus."),
        ("critmin.price_deviation_signal", "Proxy for price-deviation mention intensity."),
    ]:
        feat_urn = make_ml_feature_urn(fid)
        emit(emitter, MetadataChangeProposalWrapper(
            entityUrn=feat_urn,
            aspect=MLFeaturePropertiesClass(name=fid, description=desc),
        ))

    # 5. Lineage edges: datasets -> feature group -> ML model
    emit(emitter, MetadataChangeProposalWrapper(
        entityUrn=CRITMIN_FEATURE_GROUP_URN,
        aspect=UpstreamLineageClass(upstreams=[
            UpstreamClass(dataset=NYC_RIDES_URN, type=DatasetLineageTypeClass.TRANSFORMED),
            UpstreamClass(dataset=NYC_FHV_URN, type=DatasetLineageTypeClass.TRANSFORMED),
        ]),
    ))
    emit(emitter, MetadataChangeProposalWrapper(
        entityUrn=CRITMIN_MODEL_URN,
        aspect=UpstreamLineageClass(upstreams=[
            UpstreamClass(dataset=CRITMIN_FEATURE_GROUP_URN, type=DatasetLineageTypeClass.TRANSFORMED),
        ]),
    ))

    log.info("Datapack ingest complete. Visit http://localhost:9002 to browse.")


def plant_freshness_issue(emitter: DatahubRestEmitter, age_hours: int = 36) -> None:
    """Rewrite the dataset's lastModified to be `age_hours` old (simulates stale data)."""
    stale_ms = int((time.time() - age_hours * 3600) * 1000)
    emit(emitter, MetadataChangeProposalWrapper(
        entityUrn=NYC_RIDES_URN,
        aspect=DatasetPropertiesClass(
            name="nyc_taxi.rides",
            description="Yellow taxi ride data (dbt-modeled). [STALE - planted issue]",
            uri="bigquery://acme-prod/nyc_taxi.rides",
            tags=["domain:transport", "tier:1"],
            customProperties={
                "source": "nyc.gov TLC",
                "lastModified": str(stale_ms),
            },
        ),
    ))
    log.info("Planted freshness issue on %s (age=%dh)", NYC_RIDES_URN, age_hours)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gms", default=GMS, help="DataHub GMS URL")
    p.add_argument("--ingest-datapack", action="store_true")
    p.add_argument("--plant-freshness-issue", action="store_true")
    p.add_argument("--age-hours", type=int, default=36)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    emitter = DatahubRestEmitter(gms_server=args.gms)

    if args.ingest_datapack:
        ingest_datapack(emitter)
    if args.plant_freshness_issue:
        plant_freshness_issue(emitter, args.age_hours)
    if not (args.ingest_datapack or args.plant_freshness_issue):
        p.error("specify --ingest-datapack and/or --plant-freshness-issue")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
