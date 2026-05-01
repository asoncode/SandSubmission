"""Data preparation helpers for the Streamlit dashboard."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from sand_bulletin.analytics import AnalyticsBlockedError, ReportMetric, build_report_ready_metrics
from sand_bulletin.data_quality import (
    AnalysisMode,
    DataQualitySummary,
    resolution_frame,
    resolve_clinical_submissions,
    validate_upload_batch,
)
from sand_bulletin.ingestion.batches import UploadBatchManifest
from sand_bulletin.ingestion.datasets import DatasetKind


@dataclass(frozen=True)
class DashboardDataset:
    """All data frames required by the operational dashboard."""

    quality_summary: DataQualitySummary
    metrics: list[ReportMetric]
    metrics_frame: pd.DataFrame
    issues_frame: pd.DataFrame
    resolution_frame: pd.DataFrame
    mode_comparison_frame: pd.DataFrame
    analysis_mode: AnalysisMode
    analytics_blocked: bool
    block_reason: str | None = None


def build_dashboard_dataset(
    manifest: UploadBatchManifest,
    allow_high_severity: bool = False,
    analysis_mode: AnalysisMode | str = AnalysisMode.VALIDATED,
) -> DashboardDataset:
    """Build dashboard-ready data from the shared quality and metrics layers."""

    quality_summary = validate_upload_batch(manifest)
    mode = AnalysisMode(analysis_mode)
    resolution = resolve_clinical_submissions(
        manifest.datasets[DatasetKind.CLINICAL_NEONATAL].frame,
        mode,
    )
    try:
        metrics = build_report_ready_metrics(
            manifest,
            quality_summary,
            allow_high_severity=allow_high_severity,
            analysis_mode=mode,
        )
        blocked = False
        reason = None
    except AnalyticsBlockedError as exc:
        metrics = []
        blocked = True
        reason = str(exc)

    return DashboardDataset(
        quality_summary=quality_summary,
        metrics=metrics,
        metrics_frame=metric_frame(metrics),
        issues_frame=issue_frame(quality_summary),
        resolution_frame=resolution_frame(resolution),
        mode_comparison_frame=mode_comparison_frame(manifest, quality_summary),
        analysis_mode=mode,
        analytics_blocked=blocked,
        block_reason=reason,
    )


def mode_comparison_frame(
    manifest: UploadBatchManifest,
    quality_summary: DataQualitySummary,
) -> pd.DataFrame:
    """Compare row handling and headline KPIs across analysis modes."""

    rows: list[dict[str, object]] = []
    for mode in AnalysisMode:
        resolution = resolve_clinical_submissions(
            manifest.datasets[DatasetKind.CLINICAL_NEONATAL].frame,
            mode,
        )
        try:
            metrics = build_report_ready_metrics(
                manifest,
                quality_summary,
                allow_high_severity=True,
                analysis_mode=mode,
            )
            metrics_df = metric_frame(metrics)
            kpis = national_kpis(metrics_df)
            blocked = False
        except AnalyticsBlockedError:
            kpis = {
                "total_deliveries": None,
                "live_births": None,
                "neonatal_mortality_rate_per_1000_live_births": None,
                "stillbirth_rate_per_1000_deliveries": None,
            }
            blocked = True
        rows.append(
            {
                "analysis_mode": mode.value,
                "clinical_rows_used": len(resolution.frame),
                "selected_conflict_groups": resolution.selected_conflict_groups,
                "unresolved_conflict_groups": resolution.unresolved_conflict_groups,
                "excluded_rows": resolution.excluded_rows,
                "blocked_without_override": mode == AnalysisMode.RAW and quality_summary.high_count > 0,
                "metrics_blocked": blocked,
                "total_deliveries": kpis["total_deliveries"],
                "live_births": kpis["live_births"],
                "nmr_per_1000": kpis["neonatal_mortality_rate_per_1000_live_births"],
                "stillbirth_rate_per_1000": kpis["stillbirth_rate_per_1000_deliveries"],
            }
        )
    return pd.DataFrame(rows)


def metric_frame(metrics: list[ReportMetric]) -> pd.DataFrame:
    """Convert report metric records to a dashboard-friendly data frame."""

    if not metrics:
        return pd.DataFrame(
            columns=[
                "tenant_id",
                "country_code",
                "metric_version",
                "reporting_period_start",
                "reporting_period_end",
                "geography_level",
                "geography_id",
                "facility_id",
                "metric_name",
                "metric_value",
                "metric_unit",
                "numerator",
                "denominator",
                "source_table",
                "source_fields",
                "calculation_rule",
                "trace_payload",
            ]
        )
    return pd.DataFrame([metric.as_record() for metric in metrics])


def issue_frame(summary: DataQualitySummary) -> pd.DataFrame:
    """Convert data quality issues to a dashboard-friendly data frame."""

    if not summary.issues:
        return pd.DataFrame(
            columns=[
                "severity",
                "issue_type",
                "dataset_kind",
                "facility_id",
                "reporting_month",
                "affected_column",
                "observed_value",
                "expected_rule",
                "suggested_action",
                "source_row_number",
            ]
        )
    return pd.DataFrame([issue.as_record() for issue in summary.issues])


def national_kpis(metrics: pd.DataFrame) -> dict[str, float | None]:
    """Return the core national KPI values for compact display."""

    national = metrics[
        (metrics["geography_level"] == "national") & (metrics["geography_id"] == "national")
    ]
    names = (
        "total_deliveries",
        "live_births",
        "neonatal_mortality_rate_per_1000_live_births",
        "stillbirth_rate_per_1000_deliveries",
        "low_birth_weight_rate_pct",
        "preterm_birth_rate_pct",
    )
    return {name: _first_metric_value(national, name) for name in names}


def top_facilities_by_metric(
    metrics: pd.DataFrame,
    metric_name: str,
    limit: int = 10,
    ascending: bool = False,
) -> pd.DataFrame:
    """Return top facility rows for one metric."""

    if metrics.empty:
        return pd.DataFrame(columns=["facility_id", "metric_value", "metric_unit"])
    rows = metrics[
        (metrics["geography_level"] == "facility") & (metrics["metric_name"] == metric_name)
    ].copy()
    if rows.empty:
        return rows
    rows = rows.sort_values(["metric_value", "facility_id"], ascending=[ascending, True])
    return rows[["facility_id", "metric_value", "metric_unit"]].head(limit).reset_index(drop=True)


def geography_metric_table(
    metrics: pd.DataFrame,
    geography_level: str,
    metric_names: list[str],
) -> pd.DataFrame:
    """Pivot selected metrics by geography for tables and charts."""

    rows = metrics[
        (metrics["geography_level"] == geography_level) & (metrics["metric_name"].isin(metric_names))
    ]
    if rows.empty:
        return pd.DataFrame(columns=["geography_id", *metric_names])
    table = rows.pivot_table(
        index="geography_id",
        columns="metric_name",
        values="metric_value",
        aggfunc="first",
    ).reset_index()
    return table.sort_values("geography_id").reset_index(drop=True)


def facility_metric_table(metrics: pd.DataFrame, metric_names: list[str]) -> pd.DataFrame:
    """Pivot selected facility metrics into one row per facility."""

    if metrics.empty:
        return pd.DataFrame(columns=["facility_id", *metric_names])
    rows = metrics[
        (metrics["geography_level"] == "facility") & (metrics["metric_name"].isin(metric_names))
    ]
    if rows.empty:
        return pd.DataFrame(columns=["facility_id", *metric_names])
    table = rows.pivot_table(
        index="facility_id",
        columns="metric_name",
        values="metric_value",
        aggfunc="first",
    ).reset_index()
    return table.sort_values("facility_id").reset_index(drop=True)


def priority_intervention_table(metrics: pd.DataFrame, limit: int = 5) -> pd.DataFrame:
    """Rank facilities for immediate follow-up using outcome, volume, and vulnerability."""

    names = [
        "total_deliveries",
        "neonatal_mortality_rate_per_1000_live_births",
        "facility_vulnerability_score",
        "neonatal_readiness_score",
        "avg_referral_time_hrs",
    ]
    table = facility_metric_table(metrics, names)
    required = [
        "total_deliveries",
        "neonatal_mortality_rate_per_1000_live_births",
        "facility_vulnerability_score",
    ]
    if table.empty or any(column not in table for column in required):
        return pd.DataFrame(
            columns=[
                "rank",
                "facility_id",
                "priority_score",
                "risk_band",
                "why",
                *required,
                "neonatal_readiness_score",
            ]
        )

    scored = table.copy()
    max_deliveries = max(float(scored["total_deliveries"].max() or 1), 1.0)
    max_mortality = max(
        float(scored["neonatal_mortality_rate_per_1000_live_births"].max() or 1),
        1.0,
    )
    scored["priority_score"] = (
        scored["neonatal_mortality_rate_per_1000_live_births"].fillna(0) / max_mortality * 40.0
        + scored["total_deliveries"].fillna(0) / max_deliveries * 30.0
        + scored["facility_vulnerability_score"].fillna(0) / 100.0 * 30.0
    )
    scored["risk_band"] = scored["facility_vulnerability_score"].apply(score_band)
    scored["why"] = scored.apply(_priority_reason, axis=1)
    scored = scored.sort_values(["priority_score", "facility_id"], ascending=[False, True]).head(limit)
    scored.insert(0, "rank", range(1, len(scored) + 1))
    display_columns = [
        "rank",
        "facility_id",
        "priority_score",
        "risk_band",
        "why",
        "total_deliveries",
        "neonatal_mortality_rate_per_1000_live_births",
        "facility_vulnerability_score",
        "neonatal_readiness_score",
    ]
    return scored[[column for column in display_columns if column in scored]].reset_index(drop=True)


def driver_insights(metrics: pd.DataFrame) -> list[str]:
    """Return concise computed insights connecting outcomes to readiness and vulnerability."""

    table = facility_metric_table(
        metrics,
        [
            "neonatal_mortality_rate_per_1000_live_births",
            "neonatal_readiness_score",
            "facility_vulnerability_score",
            "total_deliveries",
        ],
    )
    if table.empty:
        return []

    insights: list[str] = []
    if {"neonatal_readiness_score", "neonatal_mortality_rate_per_1000_live_births"} <= set(table):
        low = table[table["neonatal_readiness_score"] < 60]
        higher = table[table["neonatal_readiness_score"] >= 60]
        if not low.empty and not higher.empty:
            insights.append(
                "Facilities below 60 readiness average "
                f"{low['neonatal_mortality_rate_per_1000_live_births'].mean():.1f} neonatal deaths "
                "per 1,000 live births, compared with "
                f"{higher['neonatal_mortality_rate_per_1000_live_births'].mean():.1f} among facilities at or above 60."
            )
    if {"facility_vulnerability_score", "neonatal_mortality_rate_per_1000_live_births"} <= set(table):
        high = table[table["facility_vulnerability_score"] >= 60]
        lower = table[table["facility_vulnerability_score"] < 60]
        if not high.empty and not lower.empty:
            insights.append(
                "High-vulnerability facilities average "
                f"{high['neonatal_mortality_rate_per_1000_live_births'].mean():.1f} neonatal deaths "
                "per 1,000 live births, versus "
                f"{lower['neonatal_mortality_rate_per_1000_live_births'].mean():.1f} in lower-vulnerability facilities."
            )
    if {"total_deliveries", "facility_vulnerability_score"} <= set(table):
        high_volume_cutoff = table["total_deliveries"].quantile(0.75)
        high_volume = table[table["total_deliveries"] >= high_volume_cutoff]
        overlap = high_volume[high_volume["facility_vulnerability_score"] >= 60]
        if not overlap.empty:
            facilities = ", ".join(overlap.sort_values("facility_id")["facility_id"].head(6))
            insights.append(
                f"{len(overlap)} high-volume facilities also score high vulnerability; examples: {facilities}."
            )
    return insights


def score_band(value: float | None) -> str:
    """Convert a 0-100 score into an interpretable risk band."""

    if value is None or pd.isna(value):
        return "Unknown"
    score = float(value)
    if score >= 80:
        return "Critical"
    if score >= 60:
        return "High"
    if score >= 40:
        return "Moderate"
    return "Low"


def _first_metric_value(metrics: pd.DataFrame, metric_name: str) -> float | None:
    rows = metrics[metrics["metric_name"] == metric_name]
    if rows.empty:
        return None
    value = rows.iloc[0]["metric_value"]
    if pd.isna(value):
        return None
    return float(value)


def _priority_reason(row: pd.Series) -> str:
    reasons: list[str] = []
    mortality = row.get("neonatal_mortality_rate_per_1000_live_births")
    vulnerability = row.get("facility_vulnerability_score")
    readiness = row.get("neonatal_readiness_score")
    deliveries = row.get("total_deliveries")
    if not pd.isna(mortality):
        reasons.append(f"NMR {float(mortality):.1f}/1,000")
    if not pd.isna(vulnerability):
        reasons.append(f"{score_band(float(vulnerability)).lower()} vulnerability")
    if not pd.isna(readiness) and float(readiness) < 60:
        reasons.append(f"readiness {float(readiness):.1f}")
    if not pd.isna(deliveries):
        reasons.append(f"{float(deliveries):,.0f} deliveries")
    return "; ".join(reasons)
