# Project Story — DataForge AI

> Built for **Build with DataHub: The Agent Hackathon** — Production ML Agents track.
> Repo: https://github.com/Cubiczan/dataforge-ai (mirrors: [Icohangar-Ops](https://github.com/Icohangar-Ops/dataforge-ai), [Codeberg](https://codeberg.org/Cubiczan/dataforge-ai))

---

## Inspiration

Production ML models fail silently. A feature pipeline stops refreshing at 3am. A dbt model quietly drops a column. A source distribution drifts after a supplier goes bankrupt. The model keeps serving predictions — wrong predictions — and nobody notices until a downstream business metric slips a week later. By then the blast radius is large, the root cause is buried under a week of cached features, and the on-call engineer is triaging in the dark.

We've lived this. The original version of this project — **CritMin Oracle** — is an NLP model that reads SEC 10-K filings and supply-chain news to produce a 0–100 critical-mineral risk score. It worked great in dev. In prod, it silently degraded for nine days because a dbt model upstream had dropped the `vendor_id` column and the feature extractor was returning `NaN` for an entire feature. The model didn't error. It just got confidently wrong.

When we saw the DataHub hackathon, the realization was immediate: **DataHub already knows about every one of those failure modes.** It has the lineage, the schemas, the ownership, the freshness signals, the ML model registry. What it lacks is an *agent* that continuously checks those signals against the model's expectations and raises structured incidents when something is wrong. So we pivoted CritMin from "the model we ship" to "the model we protect" — and DataForge AI was born.

The north star became a single sentence: **the next agent that picks up this model should not start from scratch.** Every incident DataForge raises has to live inside DataHub's own graph, not in a side database, so any downstream agent or human querying the lineage inherits the context for free.

## What it does

DataForge AI is a production-ML observability agent that runs as a sidecar to your DataHub instance. On each poll cycle it:

1. **Lists every `MLModel` entity** registered in DataHub via GraphQL.
2. **Walks upstream lineage** from each model through feature groups to source datasets.
3. **Runs three silent-failure detectors** on each entity:
   - **Freshness drop** — compares `DatasetProperties.lastModified` against the configured SLA. Severity escalates from `WARN` to `CRITICAL` when age exceeds 2× SLA.
   - **Schema drift** — snapshots the `SchemaMetadata` aspect and diffs it against the prior observation. Flags added / removed / retyped fields. Removing or retyping a field is automatically `CRITICAL` because downstream feature extractors usually can't tolerate it.
   - **Distribution shift** — computes Population Stability Index (PSI) and a two-sample Kolmogorov-Smirnov statistic on feature values against a stored reference. PSI > 0.20 or KS p-value < 0.05 triggers a finding. Severity escalates to `CRITICAL` when PSI exceeds 2× threshold.
4. **Drafts incident text via LLM** (OpenAI / Anthropic / Ollama — pluggable). The LLM gets the finding's structured evidence and produces a one-paragraph incident summary plus a concrete resolution note. If the LLM call fails, the writer falls back to a rule-based description from the finding itself — the agent never blocks on LLM availability.
5. **Writes the incident back into DataHub** as a `DataHubIncidentProperties` aspect on the failing entity, via the official `acryl-datahub` emitter. The incident type, severity, title, description, evidence, and resolution guidance are all structured fields — not free-text blobs.
6. **Resolves incidents** when the underlying issue clears (closing the loop on the graph).

The end result: when you open the DataHub UI and navigate to any dataset or ML model that DataForge watches, you see the active incidents right there in the graph — queryable by any other agent via the standard GraphQL API. That's the multiplier. That's the part the hackathon rubric explicitly rewards.

## How we built it

**Architecture in one paragraph**: a Python agent (`dataforge.agent.DataForgeAgent`) polls DataHub GMS over REST + GraphQL, runs three pure-function detectors that each return an optional `Finding`, hands any findings to an LLM-backed incident writer that drafts human-readable text, and writes the result back as a `DataHubIncidentProperties` aspect via `acryl-datahub`'s `DatahubRestEmitter.emit_mcp()`. State (last-seen schema snapshots, baseline feature distributions) lives in a tiny local `.dataforge/state/` directory; the source of truth for everything else is always DataHub itself.

**Component breakdown:**

- `src/dataforge/datahub_client.py` — Single `DataHubClient` class wrapping `httpx` for GraphQL queries (lineage traversal, schema lookup, freshness) and `acryl-datahub`'s `DatahubRestEmitter` for emitting `MetadataChangeProposalWrapper` events. Tenacity-retried HTTP calls for transient failures.
- `src/dataforge/detectors/` — Three pure functions: `detect_freshness_drop()`, `detect_schema_drift()`, `detect_distribution_shift()`. Each returns `Finding | None`. The `Finding` dataclass carries target URN, type, severity, title, description, structured evidence dict, and a rule-based `suggested_resolution` the LLM may override.
- `src/dataforge/writers/incident.py` — `write_incident(client, finding)`. Calls the configured LLM with the finding's evidence, asks for a summary + resolution note, constructs a `DataHubIncidentPropertiesClass`, wraps it in a `MetadataChangeProposalWrapper`, and emits via `DatahubRestEmitter`. Falls back to rule-based text on LLM failure.
- `src/dataforge/adapters/critmin.py` — The original CritMin Oracle model, refactored into a feature adapter. Exposes three feature extractors (`critmin.sentiment_polarity`, `critmin.mineral_mention_count`, `critmin.price_deviation_signal`) that the distribution-shift detector samples from a synthetic SEC-filing corpus for the demo.
- `src/dataforge/agent.py` — Main poll loop. Lists ML models, walks upstream lineage, runs all three detectors per entity, renders findings via Rich, and writes incidents.
- `src/dataforge/cli.py` — Typer CLI: `dataforge scan`, `dataforge watch`, `dataforge health`, `dataforge demo`.
- `src/dataforge/config.py` — Pydantic settings loaded from `.env` with sensible defaults for `datahub docker quickstart`.

**Why we did NOT build on top of the DataHub MCP server as the primary transport**: The MCP server is a thin wrapper over the same GraphQL/REST surface — using it exclusively would have added a hop without gaining capability for our specific use case (we need to emit aspects, not just chat about metadata). We did add `MCP_SERVER_URL` as an optional config so the agent *can* route lineage queries through MCP if a deployment prefers that surface. This keeps us aligned with the hackathon's integration-surface guidance without making MCP a hard dependency.

**The detector math (distribution shift)**:

PSI is computed as:

$$\text{PSI} = \sum_{i=1}^{k} \left( p_{\text{actual},i} - p_{\text{expected},i} \right) \cdot \ln\left( \frac{p_{\text{actual},i}}{p_{\text{expected},i}} \right)$$

where $p_{\text{expected},i}$ and $p_{\text{actual},i}$ are the proportions of the reference and current samples falling into bucket $i$ of a shared 10-bucket histogram. We add $\epsilon = 10^{-6}$ to each proportion to avoid division-by-zero on empty buckets. Conventionally PSI < 0.10 is "no shift", 0.10–0.25 is "minor shift", and > 0.25 is "major shift". We default the threshold to **0.20** so the demo is sensitive enough to flag drift without false-positiving on normal sampling noise.

For the KS test we use `scipy.stats.ks_2samp` and flag drift at $p < 0.05$. PSI catches distribution-shape changes that KS misses (e.g. mean shifts that preserve the CDF shape); KS catches changes PSI is insensitive to (e.g. tail behavior). Running both gives us defense in depth.

**Demo setup**: `scripts/setup_datahub.sh` runs `datahub docker quickstart`, then `scripts/seed_demo_data.py --ingest-datapack` registers two dbt-modeled nyc-taxi datasets, the CritMin ML model, a feature group, three features, and the lineage edges connecting them. `--plant-freshness-issue` rewrites a dataset's `lastModified` to be 36 hours old so the freshness detector has something to find. The distribution-shift detector finds drift on its own thanks to a synthetic corpus that flips from positive to negative sentiment.

## Challenges we ran into

**1. Misunderstanding what DataHub actually is.** Our original blueprint proposed "extract raw data from DataHub → transform with NLP → load structured JSON back to DataHub." That doesn't work — DataHub is a *metadata catalog*, not a data lake. It tracks schemas, lineage, ownership, and ML metadata; it does not store raw datasets and has no `publish(data=...)` API. We caught this early enough to pivot cleanly, but it cost us a research cycle. The lesson: read the platform docs before designing the integration.

**2. DataHub's GraphQL surface is large and versioned differently across releases.** The `datasetProperties.lastModified` field is exposed differently in DataHub 0.13 vs 0.14 — sometimes via GraphQL, sometimes only via the REST aspect endpoint. We ended up with a hybrid approach: GraphQL for lineage traversal (where it's stable), REST `/openapi/v1/dataset/.../datasetProperties` for freshness (where it's stable). The `DataHubClient` class hides this from the detectors.

**3. The `DataHubIncidentPropertiesClass` API is sparsely documented.** We had to read the `datahub.metadata.schema_classes` source to figure out which fields are required vs optional, what the `status` enum accepts (`ACTIVE` / `RESOLVED`), and how the `actor` field should be formatted (`urn:li:corpuser:dataforge-ai`). The official emitter handles serialization correctly, but only if you construct the aspect class with the right kwargs — there's no schema validation at emit time, so mistakes fail silently.

**4. PSI is sensitive to bucket choice on small samples.** With our 100-document synthetic corpus, PSI on a perfectly stable feature would still register 0.05–0.10 due to bucket boundary effects. We had to add $\epsilon$ smoothing on the bucket proportions and pick a threshold (0.20) that's well above the noise floor but below the "major shift" convention (0.25). In a production deployment with millions of rows, this wouldn't matter — but for a hackathon demo with a small corpus, the calibration matters.

**5. LLM provider abstraction without over-engineering.** We wanted OpenAI, Anthropic, and Ollama to all work, but didn't want to pull in LangChain or LlamaIndex for a 50-line abstraction. The solution is three small functions (`_draft_with_openai`, `_draft_with_anthropic`, `_draft_with_ollama`) that each return `(summary, resolution)` and a dispatcher that picks one based on a config enum. Total cost: ~80 lines of code, zero dependencies beyond the official SDKs.

**6. The hackathon rubric explicitly rewards "contributing back to the graph, not just reading metadata."** This shaped every architectural decision. The easy path would have been to write incidents to a side database and surface them in a dashboard. We did the harder thing — emitting `DataHubIncidentProperties` aspects directly into DataHub — because that's what makes the project actually valuable to the next agent that touches the graph.

## Accomplishments that we're proud of

- **The agent reads AND writes DataHub.** Every finding becomes a structured aspect on the failing entity, queryable by any other agent via standard GraphQL. The hackathon prompt's #1 judging criterion is met directly.
- **The LLM is a runtime dependency, not a build-time one.** If OpenAI is down or the API key is bad, the agent falls back to rule-based incident text and keeps writing incidents. Degraded-mode operation is a hard requirement for production ML tooling.
- **The detector math is real.** PSI + two-sample KS is the industry-standard pair for feature distribution monitoring. We didn't invent a heuristic — we implemented the textbook approach with the right statistical edge cases handled (epsilon smoothing, shared bucket boundaries, two-sided p-values).
- **Local bootstrap is one command.** `bash scripts/setup_datahub.sh` brings up DataHub, ingests demo metadata, and the agent can run immediately. A judge with Docker installed can be looking at incidents in the DataHub UI in under five minutes.
- **The CritMin Oracle IP survived the pivot.** We didn't throw away the original project — we refactored its NLP feature extractors into a model adapter that the distribution-shift detector samples from. The model is now the thing being protected, not the thing being shipped, but the code is the same.

## What we learned

- **DataHub's metadata graph is genuinely agent-friendly.** The GraphQL API is well-typed, the lineage traversal is recursive, and the aspect-based write model means you can extend any entity with custom structured data without forking the schema. This is a much better foundation for agent workflows than we expected.
- **MCP is not always the right answer.** The DataHub MCP server is great for "chat with your metadata" use cases. For an always-on polling agent that needs to emit aspects, plain REST + GraphQL is simpler, faster, and works against any DataHub deployment without requiring MCP to be deployed alongside.
- **Production ML observability is a graph problem, not a metrics problem.** Traditional ML monitoring (Datadog, Arize, WhyLabs) treats each model as an isolated time series. DataHub's graph model lets you reason about *why* a model is degrading — because the upstream dataset is stale, because the schema drifted, because the feature distribution shifted. The graph is the diagnostic.
- **Incident text quality matters.** A finding that says "PSI=0.41" is useless to an on-call engineer at 3am. A finding that says "PSI=0.41, threshold=0.20, KS p=0.0012, mean shifted from +0.21 to -0.34, likely cause: upstream SEC filings shifted sentiment after supplier bankruptcy, suggested next step: refresh reference distribution and retrain" is actionable. The LLM-backed writer was the single biggest UX upgrade in the project.
- **Apache 2.0 is non-negotiable for hackathon credibility.** The rubric explicitly requires it, and judges check. We added the LICENSE file in the first commit, not the last.

## What's next for DataForge AI

- **Deduplication of active incidents.** Currently each poll cycle writes a new incident even if an identical one is already ACTIVE on the same entity. We need to query existing incidents before raising new ones and update rather than duplicate.
- **Auto-resolution.** Wire `resolve_incident()` to an external SLO/healthcheck so when the upstream dataset refreshes or the schema is restored, the DataHub incident auto-closes with a resolution note. Closing the loop is the difference between an alerting system and an observability system.
- **Real CritMin feature pipeline.** Replace the synthetic SEC-filing corpus with the actual CritMin Oracle NLP pipeline (transformers + SEC EDGAR fetcher). The adapter is already structured for this — it's a swap, not a rewrite.
- **Multi-model support.** The agent already iterates over all `MLModel` entities in DataHub, but the adapter registry is hard-coded to CritMin. We want a plugin model where each registered ML model declares its own feature adapter and the agent picks the right one based on the model's `platform` and `tags`.
- **Reference distribution snapshots on a schedule.** Today the detector uses a rolling baseline (each run replaces the reference with the current values). In production you'd snapshot the reference weekly and only update it on a deliberate "bump the baseline" action — otherwise slow drift compounds undetected.
- **OWNERS routing.** Look up the `Ownership` aspect on the failing entity and route the incident to the right team via Slack/PagerDuty. DataHub already has this data; we just need to consume it.
- **MCP server transport.** Add an optional mode where the agent routes lineage queries through the DataHub MCP server instead of direct REST/GraphQL, for deployments that prefer the MCP surface. The config knob (`MCP_SERVER_URL`) is already there; we just need to wire the transport.
- **Submit to DataHub itself.** The detectors and the incident writer are generic enough that we'd like to upstream them as a DataHub plugin / example repo. The hackathon is the proof-of-concept; the long-term home is the DataHub ecosystem.
