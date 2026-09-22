# DataForge AI

> Production-ML observability agent that watches the **DataHub lineage graph**, detects silent failures in your ML models, and writes **incidents + resolutions back into DataHub** so downstream agents inherit the context.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![DataHub](https://img.shields.io/badge/DataHub-0.13+-teal.svg)](https://datahubproject.io/)

Built for the **[Build with DataHub: The Agent Hackathon](https://datahub.devpost.com/)** — *Production ML Agents* track.

---

## Why this exists

Production ML models fail silently. A feature pipeline stops refreshing. A dbt model drops a column. A source distribution drifts. The model keeps serving predictions, and nobody notices until a downstream business metric slips.

**DataHub already knows about all of this** — it has the lineage, the schemas, the ownership, the freshness signals. What it lacks is an *agent* that continuously checks those signals against the model's expectations and raises structured incidents when something is wrong.

DataForge AI is that agent. It runs as a sidecar to your DataHub instance, polls the metadata graph, runs three classes of detector, and writes `DataHubIncidentProperties` aspects back to the graph — so the next agent (or human on-call) that picks up the model sees not just "what failed" but "what to do about it".

---

## Architecture

```
            ┌──────────────────────────────────────────────┐
            │              DataHub GMS (REST)               │
            │   datasets · ML models · lineage · incidents  │
            └───────────────┬───────────────────┬──────────┘
                            │ read              │ write
                            ▼                   ▲
        ┌────────────────────────────┐    ┌─────────────────────┐
        │   DataForge Agent (poll)   │───►│   Incident Writer   │
        │  ┌──────────────────────┐  │    │  (LLM-drafted text) │
        │  │ Freshness Detector   │  │    └─────────────────────┘
        │  │ Schema-Drift Detector│  │
        │  │ Dist-Shift Detector  │  │
        │  └──────────────────────┘  │
        └────────────────────────────┘
                    ▲
                    │ feature values
        ┌────────────────────────────┐
        │   CritMin Model Adapter    │
        │  (NLP features → samples)  │
        └────────────────────────────┘
```

See [`docs/architecture.md`](docs/architecture.md) for the full design.

---

## Quickstart

```bash
# 1. Clone
git clone https://github.com/Cubiczan/dataforge-ai.git
cd dataforge-ai
pip install -e ".[dev]"

# 2. Start local DataHub + ingest demo metadata
bash scripts/setup_datahub.sh

# 3. (optional) Plant a freshness issue so the detector has something to find
python scripts/seed_demo_data.py --plant-freshness-issue

# 4. Run the agent
cp .env.example .env
dataforge demo
```

You should see output like:

```
Scanning 1 ML model(s) for silent failures...

Model: CritMin Risk Scorer  urn:li:mlModel:(urn:li:dataPlatform:critmin,risk-scorer,v1)
Type        Severity   Target                                                Title
freshness   WARN       urn:li:dataset:(urn:li:dataPlatform:dbt,nyc_taxi...)  Freshness SLA violation: nyc_taxi.rides is 36.0h old
schema      CRITICAL   urn:li:dataset:(urn:li:dataPlatform:dbt,nyc_taxi...)  Schema drift detected on nyc_taxi.rides
distribution CRITICAL  urn:li:mlFeature:critmin.sentiment_polarity           Feature distribution shift (PSI=0.412)

3 incident(s) now visible in DataHub UI → Incidents tab.
```

---

## What it detects

| Detector | Signal | Source | Example failure |
|---|---|---|---|
| **Freshness drop** | `DatasetProperties.lastModified` older than SLA | DataHub GraphQL | Airflow job silently paused for 36h |
| **Schema drift** | `SchemaMetadata.fields` differs from prior snapshot | DataHub GraphQL | dbt model drops `vendor_id` column |
| **Distribution shift** | PSI > 0.20 or KS p-value < 0.05 on feature values | Feature store / adapter | Sentiment polarity flips positive → negative after supplier bankruptcy |

Each finding is wrapped in a `DataHubIncidentProperties` aspect and emitted back to DataHub via the official `acryl-datahub` emitter. The incident text is drafted by an LLM (OpenAI / Anthropic / Ollama) using the finding's structured evidence, so the on-call engineer gets both "what" and "next step".

## Evidence and Remediation Controls

Every scan can be grouped into an `EvidencePack` containing a run ID, source
snapshot hashes, schema versions, findings and a deterministic input hash.
Evidence is `ADVISORY` without an owner, `PROVISIONAL_LOCK` with an owner, and
`HALT` when a critical finding exists. A named reviewer can move provisional
evidence to `LOCKED` after verifying the remediation rationale.

Incidents use an explicit lifecycle:

```text
OPEN -> ACKNOWLEDGED -> REMEDIATED -> VERIFIED
```

This keeps DataHub incident writes aligned with the downstream control-spine
contract while leaving DataHub as the system of record.

---

## Why DataHub (the part judges care about)

The hackathon rubric explicitly rewards projects that **go beyond reading metadata and contribute back to the graph**. DataForge AI does both:

- **Reads** ML model → feature group → dataset lineage via GraphQL
- **Reads** `schemaMetadata` + `datasetProperties` aspects via REST
- **Writes** `DataHubIncidentProperties` aspects back to the entities where the failures were detected
- **Writes** incident resolutions when the underlying issue is resolved (closing the loop)

The incidents DataForge raises are not stored in a side database — they live inside DataHub's own graph, queryable by any other agent or human via the standard GraphQL API. That is the multiplier effect the hackathon is looking for.

---

## Configuration

All settings are loaded from `.env` (see [`.env.example`](.env.example)):

| Var | Default | Purpose |
|---|---|---|
| `DATAHUB_GMS_URL` | `http://localhost:8080` | DataHub GMS endpoint |
| `DATAHUB_GMS_TOKEN` | _empty_ | Personal access token (for cloud DataHub) |
| `LLM_PROVIDER` | `openai` | `openai` / `anthropic` / `ollama` |
| `OPENAI_API_KEY` | _empty_ | Required if `LLM_PROVIDER=openai` |
| `OPENAI_MODEL` | `gpt-4o-mini` | Any chat-capable model |
| `FRESHNESS_SLA_HOURS` | `24` | Freshness threshold |
| `DISTRIBUTION_PSI_THRESHOLD` | `0.20` | PSI above this = drift |
| `AGENT_POLL_INTERVAL_SECONDS` | `300` | Watch-mode poll interval |
| `AGENT_DRY_RUN` | `false` | If true, log incidents without writing to DataHub |

---

## CLI reference

```bash
dataforge health       # Check DataHub GMS reachability
dataforge scan         # Run a single scan + write incidents
dataforge scan --model-urn urn:li:mlModel:...   # Scan one model
dataforge watch        # Run forever (poll every 5 min by default)
dataforge demo         # End-to-end demo (nyc-taxi + CritMin)
```

---

## Repository layout

```
dataforge-ai/
├── LICENSE                          Apache 2.0
├── README.md                        This file
├── pyproject.toml                   Deps + CLI entrypoint
├── .env.example                     Config template
├── docs/
│   ├── architecture.md              Full architecture writeup
│   └── demo_script.md               3-minute demo video script
├── examples/
│   ├── nyc_taxi_demo.py             End-to-end demo entrypoint
│   └── sample_incidents.json        Sample incidents DataForge writes
├── scripts/
│   ├── setup_datahub.sh             One-shot local DataHub bootstrap
│   └── seed_demo_data.py            Load demo metadata + plant issues
└── src/dataforge/
    ├── agent.py                     Main poll loop
    ├── cli.py                       Typer-based CLI
    ├── config.py                    Pydantic settings
    ├── datahub_client.py            GMS REST + GraphQL wrapper
    ├── detectors/
    │   ├── freshness.py             Freshness SLA detector
    │   ├── schema_drift.py          Schema diff detector
    │   └── distribution.py          PSI + KS distribution-shift detector
    ├── writers/
    │   └── incident.py              LLM-drafted incident writer
    └── adapters/
        └── critmin.py               CritMin risk-model feature adapter
```

---

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).

Copyright 2026 Cubiczan / Icohangar-Ops.

---

## Acknowledgements

- [DataHub](https://datahubproject.io/) by Acryl Data — the metadata platform this agent runs on top of
- [acryl-datahub](https://pypi.org/project/acryl-datahub/) Python SDK
- Original CritMin Oracle project (NLP on SEC filings + supply-chain risk scoring) — refactored into the model adapter
