"""Pydantic models for LLM-safe metric packages and generated summaries."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class MetricValue(BaseModel):
    """One computed metric exposed to narrative generation."""

    name: str
    value: float | None
    unit: str | None = None
    numerator: float | None = None
    denominator: float | None = None
    source_fields: list[str] = Field(default_factory=list)
    calculation_rule: str


class RankedFacility(BaseModel):
    """Facility ranking item derived from computed metrics."""

    facility_id: str
    metric_name: str
    value: float | None
    unit: str | None = None
    rank: int


class DataQualityBrief(BaseModel):
    """Aggregated data quality status for narrative context."""

    issue_count: int
    high_count: int
    medium_count: int
    low_count: int
    can_generate_report: bool
    issue_counts_by_type: dict[str, int]


class MetricPackage(BaseModel):
    """Structured, computed-only package sent to the LLM."""

    tenant_id: str
    country_code: str
    reporting_period_start: date
    reporting_period_end: date
    metric_version: str
    national_kpis: list[MetricValue]
    top_changes: list[MetricValue]
    highest_volume_facilities: list[RankedFacility]
    highest_mortality_facilities: list[RankedFacility]
    strongest_performance_facilities: list[RankedFacility]
    highest_vulnerability_facilities: list[RankedFacility] = Field(default_factory=list)
    data_quality: DataQualityBrief


class NarrativeSummary(BaseModel):
    """Generated bulletin narrative sections."""

    mode: Literal["fallback", "openai"]
    executive_summary: str
    key_findings: list[str]
    facility_watchlist_explanation: str
    recommendations: list[str]
    metric_references: list[str]
    model: str | None = None
    raw_response_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
