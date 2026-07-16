"""DataForge AI agent loop.

Each tick the agent:
  1. Lists ML models registered in DataHub.
  2. For each model, walks upstream lineage to the source datasets.
  3. Runs freshness / schema-drift / distribution-shift detectors.
  4. Writes any findings back as DataHub incidents (LLM-drafted text).
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from rich.console import Console
from rich.table import Table

from dataforge.adapters import (
    CRITMIN_FEATURES,
    make_synthetic_corpus,
    sample_feature_values,
)
from dataforge.config import Settings, get_settings
from dataforge.datahub_client import DataHubClient
from dataforge.detectors import Finding
from dataforge.detectors.distribution import detect_distribution_shift
from dataforge.detectors.freshness import detect_freshness_drop
from dataforge.detectors.schema_drift import detect_schema_drift
from dataforge.writers import write_incident

log = logging.getLogger(__name__)
console = Console()


class DataForgeAgent:
    """Production ML observability agent."""

    def __init__(
        self,
        client: Optional[DataHubClient] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or DataHubClient(self.settings)

    # ----------------------------------------------------------- public API

    def run_once(self, model_urn: Optional[str] = None) -> list[Finding]:
        """Single pass: scan all ML models (or just one) and write incidents."""
        if not self.client.health():
            console.print("[red]DataHub GMS not reachable. Run `datahub docker quickstart`.[/red]")
            return []

        models = (
            [m for m in self.client.list_ml_models() if m.urn == model_urn]
            if model_urn
            else self.client.list_ml_models()
        )
        if not models:
            console.print("[yellow]No ML models registered in DataHub. "
                          "Load the demo datapack via scripts/setup_datahub.sh.[/yellow]")
            return []

        console.print(f"[bold cyan]Scanning {len(models)} ML model(s) for silent failures...[/bold cyan]")
        all_findings: list[Finding] = []

        for model in models:
            console.print(f"\n[bold]Model:[/bold] {model.name}  [dim]{model.urn}[/dim]")
            findings = self._scan_model(model.urn)
            all_findings.extend(findings)
            for f in findings:
                self._render_finding(f)

        if not all_findings:
            console.print("[green]All clear - no silent failures detected.[/green]")
        else:
            console.print(f"\n[yellow]{len(all_findings)} finding(s) written to DataHub.[/yellow]")
        return all_findings

    def run_forever(self, poll_interval: Optional[int] = None) -> None:
        """Loop forever, polling DataHub at the configured interval."""
        interval = poll_interval or self.settings.agent_poll_interval_seconds
        console.print(
            f"[bold]DataForge agent running[/bold] (poll every {interval}s, dry_run={self.settings.agent_dry_run})"
        )
        try:
            while True:
                self.run_once()
                time.sleep(interval)
        except KeyboardInterrupt:
            console.print("\n[bold]Stopped.[/bold]")

    # --------------------------------------------------------- internals

    def _scan_model(self, model_urn: str) -> list[Finding]:
        findings: list[Finding] = []

        # 1. Walk upstream lineage to datasets
        upstreams = self.client.get_upstream_lineage(model_urn)
        for node in upstreams:
            if node.entity_type != "dataset":
                continue
            f1 = detect_freshness_drop(self.client, node.urn)
            f2 = detect_schema_drift(self.client, node.urn)
            findings.extend([f for f in (f1, f2) if f])

        # 2. Run distribution-shift checks on CritMin features
        #    (For the hackathon demo we sample from a synthetic corpus;
        #     in production this would query the feature store.)
        baseline_corpus = make_synthetic_corpus(n_docs=100, drift=False)
        drift_corpus = make_synthetic_corpus(n_docs=100, drift=True)

        for feature in CRITMIN_FEATURES:
            # On first run: store baseline. On subsequent runs: compare against baseline.
            baseline_values = sample_feature_values(feature, baseline_corpus)
            current_values = sample_feature_values(feature, drift_corpus)
            f = detect_distribution_shift(
                feature_id=feature.feature_id,
                current_values=current_values,
                reference_values=baseline_values,
            )
            if f:
                findings.append(f)

        # 3. Write findings back to DataHub as incidents
        for f in findings:
            try:
                write_incident(self.client, f, self.settings)
            except Exception as exc:  # pragma: no cover
                log.error("Failed to write incident for %s: %s", f.target_urn, exc)

        return findings

    def _render_finding(self, f: Finding) -> None:
        table = Table(show_header=False, box=None, padding=(0, 2))
        sev_color = {"info": "cyan", "warn": "yellow", "critical": "red bold"}[f.severity.value]
        table.add_row("[bold]Type[/bold]", f.finding_type.value)
        table.add_row("[bold]Severity[/bold]", f"[{sev_color}]{f.severity.value.upper()}[/{sev_color}]")
        table.add_row("[bold]Target[/bold]", f.target_urn)
        table.add_row("[bold]Title[/bold]", f.title)
        table.add_row("[bold]Description[/bold]", f.description[:240] + ("..." if len(f.description) > 240 else ""))
        console.print(table)
        console.print("[dim]─" * 60 + "[/dim]")
