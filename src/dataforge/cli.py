"""DataForge AI CLI."""
from __future__ import annotations

import logging

import typer
from rich.console import Console

from dataforge.config import get_settings

app = typer.Typer(help="DataForge AI - Production ML observability agent for DataHub.")
console = Console()


@app.command()
def scan(model_urn: str = typer.Option(None, help="Scan only this MLModel URN")) -> None:
    """Run a single scan pass and write any incidents to DataHub."""
    from dataforge.agent import DataForgeAgent

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    agent = DataForgeAgent(settings=get_settings())
    findings = agent.run_once(model_urn=model_urn)
    raise typer.Exit(code=0 if not findings else 1)


@app.command()
def watch(
    interval: int = typer.Option(None, help="Override poll interval (seconds)"),
) -> None:
    """Run the agent in watch mode (polls DataHub forever)."""
    from dataforge.agent import DataForgeAgent

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    agent = DataForgeAgent(settings=get_settings())
    agent.run_forever(poll_interval=interval)


@app.command()
def health() -> None:
    """Check DataHub GMS reachability."""
    from dataforge.datahub_client import DataHubClient

    client = DataHubClient(settings=get_settings())
    if client.health():
        console.print("[green]DataHub GMS is reachable.[/green]")
        raise typer.Exit(0)
    console.print("[red]Cannot reach DataHub GMS.[/red]")
    raise typer.Exit(1)


@app.command()
def demo() -> None:
    """Run the nyc-taxi + CritMin demo end-to-end."""
    from dataforge.agent import DataForgeAgent

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    console.print("[bold cyan]Running DataForge AI demo...[/bold cyan]")
    agent = DataForgeAgent(settings=get_settings())
    findings = agent.run_once()
    console.print(f"\n[bold]Demo complete:[/bold] {len(findings)} finding(s) raised.")


if __name__ == "__main__":  # pragma: no cover
    app()
