# Architecture

## Design goals

1. **Reads AND writes DataHub.** Hackathon rubric explicitly rewards contributing back to the graph, not just reading metadata. Every finding becomes a `DataHubIncidentProperties` aspect on the failing entity.
2. **Agent-native.** Decisions are made by a small LLM-driven writer that turns structured evidence into human-readable incident text + resolution notes. The LLM is pluggable (OpenAI / Anthropic / Ollama).
3. **Stateless + idempotent.** The agent keeps a tiny local state (last-seen schema snapshots, baseline feature distributions) but the source of truth is always DataHub itself. Restarts are safe.
4. **Runnable locally in 5 minutes.** `bash scripts/setup_datahub.sh` brings up DataHub via `docker quickstart`, ingests the nyc-taxi + CritMin demo metadata, and the agent can run immediately.

## Component responsibilities

### `datahub_client.py`

Single class (`DataHubClient`) that wraps:
- `httpx` for GraphQL queries (lineage traversal, schema lookup, dataset freshness)
- `acryl-datahub`'s `DatahubRestEmitter` for emitting `MetadataChangeProposalWrapper` events (the standard write path)
- Tenacity-retried HTTP calls for transient failures

Why not use the MCP server exclusively? Two reasons:
1. The MCP server is a thin wrapper over the same GraphQL/REST surface — using it would add a hop without gaining capability for our use case.
2. REST/GraphQL access works against any DataHub deployment (including managed Acryl) without requiring the MCP server to be deployed alongside.

The MCP server is still supported as an optional transport via `MCP_SERVER_URL` in the config; if set, the agent will route lineage queries through it. This keeps us aligned with the hackathon's integration-surface guidance without making MCP a hard dependency.

### `detectors/`

Three pure functions, each returning a `Finding | None`:

- **`freshness.py`** — `detect_freshness_drop(client, dataset_urn)`. Reads `DatasetProperties.lastModified` (falls back to `DatasetProperties` aspect via REST if GraphQL doesn't expose it). Computes age vs. SLA. Severity escalates from WARN to CRITICAL when age exceeds 2× SLA.
- **`schema_drift.py`** — `detect_schema_drift(client, dataset_urn)`. Reads `SchemaMetadata` aspect. Compares field paths + types against the last snapshot (stored in `.dataforge/state/schemas/<urn>.json`). On first observation, snapshots and returns None. On subsequent runs, returns added/removed/retyped fields.
- **`distribution.py`** — `detect_distribution_shift(feature_id, current_values, reference_values=None)`. Computes PSI (Population Stability Index) and a two-sample KS test. PSI > 0.20 or KS p < 0.05 triggers a finding. Reference distribution is stored in `.dataforge/state/distributions/<feature_id>.json`.

Each `Finding` carries: target URN, finding type, severity, title, description, structured evidence dict, and a rule-based `suggested_resolution` that the LLM writer may override or refine.

### `writers/incident.py`

`write_incident(client, finding)`:
1. Calls the configured LLM with the finding's evidence and asks for a one-paragraph incident summary + a concrete resolution note.
2. Constructs a `DataHubIncidentPropertiesClass` with type, severity, title, description (LLM-drafted), status=ACTIVE, createdAt, actor.
3. Wraps it in a `MetadataChangeProposalWrapper` and emits via `DatahubRestEmitter.emit_mcp(...)`.
4. Returns the new incident URN (`urn:li:incident:<uuid>`).

If the LLM call fails (network, bad key, etc.), the writer falls back to the finding's rule-based description + suggested_resolution. **The agent never blocks on LLM availability** — degraded-mode operation is a hard requirement for production ML tooling.

### `adapters/critmin.py`

The CritMin Oracle model (the user's pre-existing project) computes a 0–100 supply-chain risk score from NLP features extracted from SEC filings + news. The adapter exposes three feature extractors:

- `critmin.sentiment_polarity` — `(pos - neg) / (pos + neg)` over a lexicon
- `critmin.mineral_mention_count` — count of `lithium|cobalt|nickel|copper|...` mentions
- `critmin.price_deviation_signal` — count of `price|surge|spike|drop|volatility` mentions

For the hackathon demo these run over a synthetic corpus (`make_synthetic_corpus(drift=True)` injects drift-inducing language so the distribution-shift detector has something to find). In production these would be wired to the actual CritMin feature pipeline.

### `agent.py`

`DataForgeAgent.run_once()`:
1. Health-check DataHub GMS
2. List all `MLModel` entities via GraphQL
3. For each model:
   - Walk upstream lineage (datasets + feature groups)
   - For each dataset: run freshness + schema-drift detectors
   - For each CritMin feature: sample values from the adapter, run distribution-shift detector
4. Collect findings, render to console (Rich), and write each as an incident via `write_incident`

`run_forever(poll_interval)` wraps `run_once` in a `while True: sleep` loop for daemon-style operation.

## Data flow (write-back path)

```
Finding (Python dataclass)
    │
    ▼
writers.incident.write_incident
    │
    ├── LLM draft (summary + resolution)
    │
    ▼
DataHubIncidentPropertiesClass(
    type, severity, title,
    description=summary + resolution,
    status=ACTIVE, createdAt, actor
)
    │
    ▼
MetadataChangeProposalWrapper(entityUrn=target_urn, aspect=...)
    │
    ▼
DatahubRestEmitter.emit_mcp(...)
    │
    ▼
POST /api/graphql (or /openapi/v1/...)  →  DataHub GMS
    │
    ▼
DataHub search/UI shows incident on the entity's page
Other agents querying lineage inherit the incident context
```

## Failure modes (and what we do about them)

| Failure | Behavior |
|---|---|
| DataHub GMS unreachable | Agent logs error, returns `[]`, exits non-zero. No incidents written. |
| LLM provider down / bad key | Writer falls back to rule-based text from `Finding.suggested_resolution`. Incident still written. |
| Detector throws on a single entity | Caught per-entity; other entities in the same scan still processed. |
| State file corrupt | Detector logs warning, treats as first-run (re-baselines). |
| Dry-run mode (`AGENT_DRY_RUN=true`) | All write paths short-circuit with a log line. Detectors still run. |

## Production hardening (not in scope for hackathon)

- Replace synthetic CritMin corpus with the real feature store
- Snapshot reference distributions on a schedule (not rolling baseline)
- Emit `DataHubIncidentProperties` only if no ACTIVE incident of the same type already exists on the target (deduplication)
- Add an `OWNERS` lookup so incidents are routed to the right team
- Wire `resolve_incident` to an external SLO/healthcheck so resolved upstream issues auto-close DataHub incidents
