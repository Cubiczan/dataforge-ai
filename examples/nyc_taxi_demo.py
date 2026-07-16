"""End-to-end demo: plant freshness + distribution issues, run agent, show incidents.

Usage:
    # 1. Start local DataHub (one-time)
    bash scripts/setup_datahub.sh

    # 2. Run this demo
    python examples/nyc_taxi_demo.py

The demo:
  - Connects to local DataHub (http://localhost:8080)
  - Verifies health
  - Lists registered ML models
  - Walks upstream lineage, runs freshness / schema / distribution detectors
  - Writes any findings back as DataHub incidents
  - Prints a summary table of raised incidents (visible in the DataHub UI under Incidents)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow running from repo root without install
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dataforge.agent import DataForgeAgent
from dataforge.config import get_settings
from dataforge.datahub_client import DataHubClient

console = Console()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    console.print(Panel.fit(
        "[bold cyan]DataForge AI - nyc-taxi + CritMin Demo[/bold cyan]\n"
        "Demonstrates silent-failure detection on a DataHub lineage graph.",
        border_style="cyan",
    ))

    settings = get_settings()
    if settings.agent_dry_run:
        console.print("[yellow]DRY-RUN mode enabled - incidents will not be written to DataHub.[/yellow]")

    client = DataHubClient(settings=settings)
    if not client.health():
        console.print(
            "[red]DataHub GMS is not reachable at "
            f"{settings.datahub_gms_url}.[/red]\n"
            "Start it with:  bash scripts/setup_datahub.sh"
        )
        return 1

    console.print(f"[green]Connected to DataHub at {settings.datahub_gms_url}[/green]")
    console.print(f"[dim]Frontend UI: {settings.datahub_frontend_url}[/dim]\n")

    agent = DataForgeAgent(client=client, settings=settings)
    findings = agent.run_once()

    _print_summary(findings)
    return 0 if findings else 0


def _print_summary(findings: list) -> None:
    """Render a final summary table of all findings raised to DataHub."""
    if not findings:
        console.print(Panel(
            "[green]No silent failures detected in this run.[/green]\n"
            "Possible reasons:\n"
            "  - Datasets are within freshness SLA\n"
            "  - No schema changes since baseline\n"
            "  - Feature distributions within PSI threshold\n\n"
            "Try planting an issue:  python scripts/seed_demo_data.py --plant-freshness-issue",
            title="All clear",
            border_style="green",
        ))
        return

    table = Table(title="Incidents raised to DataHub", show_lines=True)
    table.add_column("#", style="dim")
    table.add_column("Type", style="cyan")
    table.add_column("Severity", style="yellow")
    table.add_column("Target URN", style="dim")
    table.add_column("Title")

    for i, f in enumerate(findings, 1):
        sev = f.severity.value.upper()
        if f.severity.value == "critical":
            sev = f"[red bold]{sev}[/red bold]"
        elif f.severity.value == "warn":
            sev = f"[yellow]{sev}[/yellow]"
        table.add_row(str(i), f.finding_type.value, sev, f.target_urn, f.title)

    console.print(table)
    console.print(
        f"\n[bold green]{len(findings)} incident(s) now visible in DataHub UI -> Incidents tab.[/bold green]"
    )


if __name__ == "__main__":
    raise SystemExit(main())
