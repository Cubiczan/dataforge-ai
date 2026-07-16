"""Incident writer.

Turns a Finding into a DataHub incident and (optionally) asks the LLM
to draft a human-readable summary + resolution note before writing it back
to the graph. Resolution notes are stored as DataHubIncidentProperties.aspect
updates so downstream agents inherit them as structured context.
"""
from __future__ import annotations

import logging
from typing import Optional

from dataforge.config import LLMProvider, Settings, get_settings
from dataforge.datahub_client import DataHubClient
from dataforge.detectors import Finding

log = logging.getLogger(__name__)


def _draft_with_openai(finding: Finding, model: str, api_key: str) -> tuple[str, str]:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    sys = (
        "You are a senior ML reliability engineer. Given a silent failure detected "
        "on a data pipeline, write (1) a one-paragraph incident summary suitable for "
        "an on-call engineer, and (2) a concrete resolution note describing the next "
        "diagnostic step. Be terse, technical, and avoid speculation."
    )
    user = finding.to_json(indent=2) if hasattr(finding, "to_json") else str(finding.to_dict())
    r = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": sys},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
    )
    text = r.choices[0].message.content or ""
    # Split into summary / resolution on the first blank line
    parts = text.split("\n\n", 1)
    summary = parts[0].strip()
    resolution = parts[1].strip() if len(parts) > 1 else finding.suggested_resolution or ""
    return summary, resolution


def _draft_with_anthropic(finding: Finding, model: str, api_key: str) -> tuple[str, str]:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    sys = (
        "You are a senior ML reliability engineer. Draft (1) a one-paragraph incident "
        "summary and (2) a concrete resolution note. Separate them with a blank line. "
        "Be terse and technical."
    )
    user = str(finding.to_dict())
    r = client.messages.create(
        model=model,
        max_tokens=400,
        system=sys,
        messages=[{"role": "user", "content": user}],
    )
    text = r.content[0].text if r.content else ""
    parts = text.split("\n\n", 1)
    return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""


def _draft_with_ollama(finding: Finding, model: str, base_url: str) -> tuple[str, str]:
    import ollama
    client = ollama.Client(host=base_url)
    r = client.chat(
        model=model,
        messages=[
            {"role": "system", "content": "Draft a 2-paragraph incident summary and resolution note."},
            {"role": "user", "content": str(finding.to_dict())},
        ],
    )
    text = r["message"]["content"]
    parts = text.split("\n\n", 1)
    return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""


def _draft_incident_text(finding: Finding, settings: Settings) -> tuple[str, str]:
    """Use the configured LLM provider to draft summary + resolution."""
    try:
        if settings.llm_provider == LLMProvider.OPENAI and settings.openai_api_key:
            return _draft_with_openai(finding, settings.openai_model, settings.openai_api_key)
        if settings.llm_provider == LLMProvider.ANTHROPIC and settings.anthropic_api_key:
            return _draft_with_anthropic(finding, settings.anthropic_model, settings.anthropic_api_key)
        if settings.llm_provider == LLMProvider.OLLAMA:
            return _draft_with_ollama(finding, settings.ollama_model, settings.ollama_base_url)
    except Exception as exc:  # pragma: no cover
        log.warning("LLM drafting failed (%s); falling back to rule-based text", exc)

    # Fallback: use the finding's own description + suggested resolution
    return finding.description, finding.suggested_resolution or "Investigate per playbook."


def write_incident(
    client: DataHubClient,
    finding: Finding,
    settings: Optional[Settings] = None,
) -> str:
    """Turn a Finding into a DataHub incident. Returns the incident urn."""
    settings = settings or get_settings()
    summary, resolution = _draft_incident_text(finding, settings)

    incident_urn = client.raise_incident(
        target_urn=finding.target_urn,
        incident_type=finding.finding_type.value,
        title=finding.title,
        description=f"{summary}\n\nResolution guidance:\n{resolution}",
        severity=finding.severity.value.upper(),
    )

    log.info(
        "Incident %s raised on %s (type=%s severity=%s)",
        incident_urn,
        finding.target_urn,
        finding.finding_type.value,
        finding.severity.value,
    )
    return incident_urn
