#!/usr/bin/env bash
# Bootstraps a local DataHub instance for the DataForge AI demo.
#
# What it does:
#   1. Installs the `acryl-datahub` CLI if missing
#   2. Runs `datahub docker quickstart` (pulls + starts DataHub stack on :8080 / :9002)
#   3. Ingests the nyc-taxi demo datapack so the lineage graph is non-empty
#   4. Registers the CritMin ML model + features so the agent has something to scan
#
# Prereqs: docker + docker-compose plugin, python >= 3.10
set -euo pipefail

DATAHUB_VERSION="${DATAHUB_VERSION:-0.13.2}"

echo "==> [1/4] Installing acryl-datahub CLI (v${DATAHUB_VERSION})"
if ! command -v datahub >/dev/null 2>&1; then
  python -m pip install --quiet "acryl-datahub==${DATAHUB_VERSION}" \
      "acryl-datahub[datahub-rest]" "acryl-datahub[dbt]"
fi
datahub version

echo "==> [2/4] Starting DataHub docker quickstart"
datahub docker quickstart --version "${DATAHUB_VERSION}"

echo "==> [3/4] Waiting for GMS to be healthy"
for i in $(seq 1 30); do
  if curl -sf http://localhost:8080/health >/dev/null; then
    echo "    GMS healthy after ${i}s"
    break
  fi
  sleep 1
done

echo "==> [4/4] Ingesting demo datapack (nyc-taxi + CritMin ML model)"
python "$(dirname "$0")/seed_demo_data.py" --ingest-datapack

echo
echo "Done. DataHub UI:  http://localhost:9002"
echo "Run the demo:      python examples/nyc_taxi_demo.py"
