"""Generate grounded bulletin narrative sections."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from sand_bulletin.narrative.models import MetricPackage, NarrativeSummary


def generate_narrative(
    package: MetricPackage,
    api_key: str | None = None,
    model: str = "gpt-5.2",
    use_openai: bool = True,
) -> NarrativeSummary:
    """Generate narrative sections from computed metrics only."""

    if not api_key or not use_openai:
        return fallback_narrative(package, model=model)
    try:
        return _openai_narrative(package, api_key=api_key, model=model)
    except Exception as exc:
        fallback = fallback_narrative(package, model=model)
        return fallback.model_copy(update={"extra": {"openai_error": str(exc)}})


def fallback_narrative(package: MetricPackage, model: str | None = None) -> NarrativeSummary:
    """Create deterministic narrative text when OpenAI is unavailable."""

    kpis = {metric.name: metric for metric in package.national_kpis}
    deliveries = _fmt(kpis.get("total_deliveries").value if kpis.get("total_deliveries") else None, 0)
    live_births = _fmt(kpis.get("live_births").value if kpis.get("live_births") else None, 0)
    nmr = _fmt(
        kpis.get("neonatal_mortality_rate_per_1000_live_births").value
        if kpis.get("neonatal_mortality_rate_per_1000_live_births")
        else None,
        1,
    )
    stillbirth_rate = _fmt(
        kpis.get("stillbirth_rate_per_1000_deliveries").value
        if kpis.get("stillbirth_rate_per_1000_deliveries")
        else None,
        1,
    )
    top_volume = package.highest_volume_facilities[0].facility_id if package.highest_volume_facilities else None
    top_mortality = (
        package.highest_mortality_facilities[0].facility_id
        if package.highest_mortality_facilities
        else None
    )
    top_vulnerability = (
        package.highest_vulnerability_facilities[0].facility_id
        if package.highest_vulnerability_facilities
        else None
    )

    findings = [
        f"The period recorded {deliveries} deliveries and {live_births} live births.",
        f"The neonatal mortality rate was {nmr} per 1,000 live births.",
        f"The stillbirth rate was {stillbirth_rate} per 1,000 deliveries.",
    ]
    if top_volume:
        findings.append(f"{top_volume} had the highest delivery volume in the computed rankings.")
    if top_mortality:
        findings.append(f"{top_mortality} ranked highest by neonatal mortality rate and should be reviewed.")
    if top_vulnerability:
        findings.append(f"{top_vulnerability} ranked highest by vulnerability score.")
    if package.data_quality.high_count:
        findings.append(
            f"Data quality review found {package.data_quality.high_count} high-severity issues."
        )

    recommendations = []
    if package.data_quality.high_count:
        recommendations.append(
            "Keep this bulletin in preview status until duplicate facility-month records and other high-severity issues are corrected or formally signed off."
        )
    if top_vulnerability:
        recommendations.append(
            f"Prioritize {top_vulnerability} for immediate follow-up because it has the highest computed vulnerability score."
        )
    if top_mortality:
        recommendations.append(
            f"Open a clinical audit for {top_mortality}, the facility with the highest computed neonatal mortality rate."
        )
    if top_volume:
        recommendations.append(
            f"Check surge staffing and neonatal equipment coverage at {top_volume}, the highest-volume facility."
        )
    recommendations.append("Use the metric trace workbook to verify source fields behind each reported number.")

    return NarrativeSummary(
        mode="fallback",
        model=model,
        executive_summary=(
            f"{package.country_code} recorded {deliveries} deliveries and {live_births} live births "
            f"from {package.reporting_period_start} to {package.reporting_period_end}. Neonatal mortality "
            f"was {nmr} deaths per 1,000 live births and stillbirths were {stillbirth_rate} per 1,000 "
            "deliveries. This report should be treated as a preview until high-severity data quality "
            "issues are resolved." if package.data_quality.high_count else
            f"{package.country_code} recorded {deliveries} deliveries and {live_births} live births "
            f"from {package.reporting_period_start} to {package.reporting_period_end}. Neonatal mortality "
            f"was {nmr} deaths per 1,000 live births and stillbirths were {stillbirth_rate} per 1,000 deliveries."
        ),
        key_findings=findings,
        facility_watchlist_explanation=(
            "The watchlist is based on the computed vulnerability score, which combines outcome burden, "
            "recent mortality change, workload, readiness gaps, workforce pressure, operations, and governance."
        ),
        recommendations=recommendations,
        metric_references=[metric.name for metric in package.national_kpis],
    )


def _openai_narrative(package: MetricPackage, api_key: str, model: str) -> NarrativeSummary:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        instructions=_instructions(),
        input=json.dumps(package.model_dump(mode="json"), sort_keys=True),
        text={
            "format": {
                "type": "json_schema",
                "name": "bulletin_narrative",
                "strict": True,
                "schema": _narrative_schema(),
            }
        },
    )
    data = json.loads(response.output_text)
    try:
        parsed = NarrativeSummary.model_validate(
            {
                **data,
                "mode": "openai",
                "model": model,
                "raw_response_id": response.id,
            }
        )
    except ValidationError as exc:
        raise ValueError(f"OpenAI narrative response did not match schema: {exc}") from exc
    return parsed


def _instructions() -> str:
    return (
        "You write concise official public-health bulletin narrative. "
        "Use only numbers and facility IDs present in the provided MetricPackage JSON. "
        "Do not invent, estimate, round beyond normal prose formatting, or add external facts. "
        "If data quality high_count is greater than zero, clearly say the bulletin requires review "
        "before final publication. Write in plain leadership language, not metric variable names. "
        "Recommendations must be facility-specific when the package includes ranked facilities, and should "
        "state the action to take, not merely say to review data. Return only JSON matching the schema."
    )


def _narrative_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "executive_summary",
            "key_findings",
            "facility_watchlist_explanation",
            "recommendations",
            "metric_references",
        ],
        "properties": {
            "executive_summary": {"type": "string"},
            "key_findings": {"type": "array", "items": {"type": "string"}},
            "facility_watchlist_explanation": {"type": "string"},
            "recommendations": {"type": "array", "items": {"type": "string"}},
            "metric_references": {"type": "array", "items": {"type": "string"}},
        },
    }


def _fmt(value: float | None, decimals: int) -> str:
    if value is None:
        return "unavailable"
    return f"{value:,.{decimals}f}"
