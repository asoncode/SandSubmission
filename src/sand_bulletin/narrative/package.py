"""Build LLM-safe metric packages from report-ready metrics."""

from __future__ import annotations

import pandas as pd

from sand_bulletin.dashboard.data import top_facilities_by_metric
from sand_bulletin.data_quality import DataQualitySummary
from sand_bulletin.narrative.models import (
    DataQualityBrief,
    MetricPackage,
    MetricValue,
    RankedFacility,
)


NATIONAL_KPI_NAMES = [
    "total_deliveries",
    "live_births",
    "neonatal_mortality_rate_per_1000_live_births",
    "stillbirth_rate_per_1000_deliveries",
    "preterm_birth_rate_pct",
    "low_birth_weight_rate_pct",
]

CHANGE_METRIC_NAMES = [
    "total_deliveries_pct_change",
    "live_births_pct_change",
    "neonatal_deaths_total_pct_change",
    "stillbirths_pct_change",
]


def build_metric_package(metrics: pd.DataFrame, summary: DataQualitySummary) -> MetricPackage:
    """Create a computed-only package for narrative generation."""

    if metrics.empty:
        raise ValueError("Narrative generation requires report-ready metrics.")

    first = metrics.iloc[0]
    national = metrics[
        (metrics["geography_level"] == "national") & (metrics["geography_id"] == "national")
    ]
    return MetricPackage(
        tenant_id=str(first["tenant_id"]),
        country_code=str(first["country_code"]),
        reporting_period_start=first["reporting_period_start"],
        reporting_period_end=first["reporting_period_end"],
        metric_version=str(first["metric_version"]),
        national_kpis=[
            _metric_value(row)
            for _, row in national[national["metric_name"].isin(NATIONAL_KPI_NAMES)].iterrows()
        ],
        top_changes=[
            _metric_value(row)
            for _, row in national[national["metric_name"].isin(CHANGE_METRIC_NAMES)].iterrows()
        ],
        highest_volume_facilities=_ranked(
            top_facilities_by_metric(metrics, "total_deliveries", limit=10)
        ),
        highest_mortality_facilities=_ranked(
            top_facilities_by_metric(
                metrics,
                "neonatal_mortality_rate_per_1000_live_births",
                limit=10,
            )
        ),
        strongest_performance_facilities=_ranked(
            top_facilities_by_metric(metrics, "facility_performance_score", limit=10)
        ),
        highest_vulnerability_facilities=_ranked(
            top_facilities_by_metric(metrics, "facility_vulnerability_score", limit=10)
        ),
        data_quality=DataQualityBrief(
            issue_count=summary.issue_count,
            high_count=summary.high_count,
            medium_count=summary.medium_count,
            low_count=summary.low_count,
            can_generate_report=summary.can_generate_report,
            issue_counts_by_type=summary.counts_by_type(),
        ),
    )


def _metric_value(row: pd.Series) -> MetricValue:
    return MetricValue(
        name=str(row["metric_name"]),
        value=None if pd.isna(row["metric_value"]) else float(row["metric_value"]),
        unit=None if pd.isna(row["metric_unit"]) else str(row["metric_unit"]),
        numerator=None if pd.isna(row["numerator"]) else float(row["numerator"]),
        denominator=None if pd.isna(row["denominator"]) else float(row["denominator"]),
        source_fields=[str(value) for value in row["source_fields"]],
        calculation_rule=str(row["calculation_rule"]),
    )


def _ranked(frame: pd.DataFrame) -> list[RankedFacility]:
    ranked: list[RankedFacility] = []
    for index, row in frame.reset_index(drop=True).iterrows():
        ranked.append(
            RankedFacility(
                facility_id=str(row["facility_id"]),
                metric_name=str(row.get("metric_name", "")) if "metric_name" in row else "selected_metric",
                value=None if pd.isna(row["metric_value"]) else float(row["metric_value"]),
                unit=None if pd.isna(row["metric_unit"]) else str(row["metric_unit"]),
                rank=index + 1,
            )
        )
    return ranked
