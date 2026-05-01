"""Pure analytics calculations for report-ready metrics."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Iterable, Optional

import pandas as pd

from sand_bulletin.analytics.metrics import ReportMetric
from sand_bulletin.data_quality import (
    AnalysisMode,
    DataQualitySummary,
    ResolutionResult,
    resolve_clinical_submissions,
    validate_upload_batch,
)
from sand_bulletin.ingestion.batches import UploadBatchManifest
from sand_bulletin.ingestion.datasets import DatasetKind
from sand_bulletin.nowcasting import build_nowcast_metrics


METRIC_VERSION = "slice8_v1"
RATE_PER_1000 = 1000.0


class AnalyticsBlockedError(RuntimeError):
    """Raised when high-severity data quality issues block analytics generation."""


@dataclass(frozen=True)
class ReportingWindow:
    """Current and previous reporting windows used for trends."""

    current_start: date
    current_end: date
    previous_start: Optional[date]
    previous_end: Optional[date]


def build_report_ready_metrics(
    manifest: UploadBatchManifest,
    quality_summary: Optional[DataQualitySummary] = None,
    allow_high_severity: bool = False,
    analysis_mode: AnalysisMode | str = AnalysisMode.VALIDATED,
) -> list[ReportMetric]:
    """Build traceable report-ready metrics from a validated upload batch."""

    summary = quality_summary or validate_upload_batch(manifest)
    mode = AnalysisMode(analysis_mode)
    blocking_issues = _blocking_high_issues(summary, mode)
    if blocking_issues and not allow_high_severity:
        raise AnalyticsBlockedError(
            f"Analytics blocked by {len(blocking_issues)} unresolved high-severity data quality issues."
        )

    window = _infer_latest_quarter_window(manifest)
    resolution = resolve_clinical_submissions(
        manifest.datasets[DatasetKind.CLINICAL_NEONATAL].frame.copy(),
        mode,
    )
    clinical = resolution.frame
    facilities = manifest.datasets[DatasetKind.FACILITIES].frame.copy()
    governance = manifest.datasets[DatasetKind.GOVERNANCE].frame.copy()
    operations = manifest.datasets[DatasetKind.OPERATIONS].frame.copy()

    current = _period_filter(clinical, window.current_start, window.current_end)
    previous = (
        _period_filter(clinical, window.previous_start, window.previous_end)
        if window.previous_start and window.previous_end
        else pd.DataFrame(columns=clinical.columns)
    )

    metrics: list[ReportMetric] = []
    metrics.extend(_clinical_aggregate_metrics(manifest, window, current, "national", "national"))
    metrics.extend(_grouped_clinical_metrics(manifest, window, current, facilities, "province"))
    metrics.extend(_grouped_clinical_metrics(manifest, window, current, facilities, "district"))
    metrics.extend(_facility_volume_metrics(manifest, window, current))
    metrics.extend(_trend_metrics(manifest, window, current, previous, "national", "national"))
    metrics.extend(_grouped_trend_metrics(manifest, window, current, previous, facilities, "province"))
    metrics.extend(_grouped_trend_metrics(manifest, window, current, previous, facilities, "district"))
    metrics.extend(_performance_score_metrics(manifest, window, governance, operations))
    metrics.extend(_readiness_score_metrics(manifest, window, facilities, governance, operations, manifest.datasets[DatasetKind.HEALTHCARE_WORKERS].frame.copy()))
    metrics.extend(_vulnerability_score_metrics(manifest, window, current, previous, facilities, governance, operations, manifest.datasets[DatasetKind.HEALTHCARE_WORKERS].frame.copy()))
    metrics.extend(_anomaly_metrics(manifest, window, current, previous))
    metrics.extend(
        build_nowcast_metrics(
            manifest,
            summary,
            allow_high_severity=allow_high_severity,
            analysis_mode=mode,
        )
    )
    metrics.extend(_top_volume_rank_metrics(manifest, window, current))
    return _tag_resolution(metrics, resolution)


def _infer_latest_quarter_window(manifest: UploadBatchManifest) -> ReportingWindow:
    clinical = manifest.datasets[DatasetKind.CLINICAL_NEONATAL].frame
    months = sorted(month for month in clinical["reporting_month"].dropna().unique())
    if not months:
        raise AnalyticsBlockedError("Analytics requires at least one reporting_month.")

    current_months = months[-3:] if len(months) >= 3 else months
    previous_months = months[-6:-3] if len(months) >= 6 else []
    return ReportingWindow(
        current_start=current_months[0],
        current_end=current_months[-1],
        previous_start=previous_months[0] if previous_months else None,
        previous_end=previous_months[-1] if previous_months else None,
    )


def _period_filter(frame: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    return frame[(frame["reporting_month"] >= start) & (frame["reporting_month"] <= end)].copy()


def _blocking_high_issues(
    summary: DataQualitySummary,
    mode: AnalysisMode,
) -> list[object]:
    if mode == AnalysisMode.RAW:
        return [issue for issue in summary.issues if issue.severity.value == "high"]
    non_blocking = {
        "conflicting_facility_month_submission",
        "low_reporting_completeness",
    }
    return [
        issue
        for issue in summary.issues
        if issue.severity.value == "high" and issue.issue_type not in non_blocking
    ]


def _tag_resolution(
    metrics: list[ReportMetric],
    resolution: ResolutionResult,
) -> list[ReportMetric]:
    trace = resolution.trace_payload()
    return [
        replace(metric, trace_payload={**metric.trace_payload, **trace})
        for metric in metrics
    ]


def _clinical_aggregate_metrics(
    manifest: UploadBatchManifest,
    window: ReportingWindow,
    frame: pd.DataFrame,
    geography_level: str,
    geography_id: str,
    facility_id: Optional[str] = None,
) -> list[ReportMetric]:
    totals = _clinical_totals(frame)
    total_deaths = totals["neonatal_deaths_0_7d"] + totals["neonatal_deaths_8_28d"]
    metrics: list[ReportMetric] = []

    for name, value in totals.items():
        metrics.append(
            _metric(
                manifest,
                window,
                geography_level,
                geography_id,
                name,
                float(value),
                "count",
                "clinical_neonatal_monthly",
                [name],
                f"sum({name}) over reporting period",
                facility_id=facility_id,
                trace_payload={"row_count": int(len(frame))},
            )
        )

    metrics.extend(
        [
            _rate_metric(
                manifest,
                window,
                geography_level,
                geography_id,
                "neonatal_mortality_rate_per_1000_live_births",
                total_deaths,
                totals["live_births"],
                ["neonatal_deaths_0_7d", "neonatal_deaths_8_28d", "live_births"],
                "(early + late neonatal deaths) / live births * 1000",
                facility_id=facility_id,
            ),
            _rate_metric(
                manifest,
                window,
                geography_level,
                geography_id,
                "early_neonatal_mortality_rate_per_1000_live_births",
                totals["neonatal_deaths_0_7d"],
                totals["live_births"],
                ["neonatal_deaths_0_7d", "live_births"],
                "early neonatal deaths / live births * 1000",
                facility_id=facility_id,
            ),
            _rate_metric(
                manifest,
                window,
                geography_level,
                geography_id,
                "late_neonatal_mortality_rate_per_1000_live_births",
                totals["neonatal_deaths_8_28d"],
                totals["live_births"],
                ["neonatal_deaths_8_28d", "live_births"],
                "late neonatal deaths / live births * 1000",
                facility_id=facility_id,
            ),
            _rate_metric(
                manifest,
                window,
                geography_level,
                geography_id,
                "stillbirth_rate_per_1000_deliveries",
                totals["stillbirths"],
                totals["total_deliveries"],
                ["stillbirths", "total_deliveries"],
                "stillbirths / total deliveries * 1000",
                facility_id=facility_id,
            ),
            _rate_metric(
                manifest,
                window,
                geography_level,
                geography_id,
                "preterm_birth_rate_pct",
                totals["preterm_births_28_32w"] + totals["preterm_births_32_37w"],
                totals["live_births"],
                ["preterm_births_28_32w", "preterm_births_32_37w", "live_births"],
                "(28-32w + 32-37w preterm births) / live births * 100",
                multiplier=100.0,
                metric_unit="percent",
                facility_id=facility_id,
            ),
            _rate_metric(
                manifest,
                window,
                geography_level,
                geography_id,
                "low_birth_weight_rate_pct",
                totals["birth_weight_less_2500g"],
                totals["live_births"],
                ["birth_weight_less_2500g", "live_births"],
                "birth weight <2500g / live births * 100",
                multiplier=100.0,
                metric_unit="percent",
                facility_id=facility_id,
            ),
            _rate_metric(
                manifest,
                window,
                geography_level,
                geography_id,
                "low_apgar_rate_pct",
                totals["apgar_less_7_at_5min"],
                totals["live_births"],
                ["apgar_less_7_at_5min", "live_births"],
                "Apgar <7 at 5 minutes / live births * 100",
                multiplier=100.0,
                metric_unit="percent",
                facility_id=facility_id,
            ),
        ]
    )

    for cause in (
        "death_birth_asphyxia",
        "death_prematurity",
        "death_sepsis",
        "death_congenital",
        "death_other",
    ):
        metrics.append(
            _rate_metric(
                manifest,
                window,
                geography_level,
                geography_id,
                f"{cause}_share_pct",
                totals[cause],
                total_deaths,
                [cause, "neonatal_deaths_0_7d", "neonatal_deaths_8_28d"],
                f"{cause} / total neonatal deaths * 100",
                multiplier=100.0,
                metric_unit="percent",
                facility_id=facility_id,
            )
        )

    return metrics


def _grouped_clinical_metrics(
    manifest: UploadBatchManifest,
    window: ReportingWindow,
    current: pd.DataFrame,
    facilities: pd.DataFrame,
    geography: str,
) -> list[ReportMetric]:
    joined = current.merge(facilities[["facility_id", geography]], on="facility_id", how="left")
    metrics: list[ReportMetric] = []
    for geography_id, group in joined.groupby(geography, dropna=False):
        metrics.extend(
            _clinical_aggregate_metrics(
                manifest,
                window,
                group,
                geography,
                str(geography_id),
            )
        )
    return metrics


def _facility_volume_metrics(
    manifest: UploadBatchManifest,
    window: ReportingWindow,
    current: pd.DataFrame,
) -> list[ReportMetric]:
    metrics: list[ReportMetric] = []
    for facility_id, group in current.groupby("facility_id"):
        metrics.extend(
            _clinical_aggregate_metrics(
                manifest,
                window,
                group,
                "facility",
                str(facility_id),
                facility_id=str(facility_id),
            )
        )
    return metrics


def _trend_metrics(
    manifest: UploadBatchManifest,
    window: ReportingWindow,
    current: pd.DataFrame,
    previous: pd.DataFrame,
    geography_level: str,
    geography_id: str,
    facility_id: Optional[str] = None,
) -> list[ReportMetric]:
    current_totals = _clinical_totals(current)
    previous_totals = _clinical_totals(previous)
    metrics: list[ReportMetric] = []
    for metric_name in ("total_deliveries", "live_births", "stillbirths"):
        metrics.extend(
            _change_metrics(
                manifest,
                window,
                geography_level,
                geography_id,
                metric_name,
                current_totals[metric_name],
                previous_totals[metric_name],
                "clinical_neonatal_monthly",
                [metric_name],
                facility_id=facility_id,
            )
        )

    current_deaths = current_totals["neonatal_deaths_0_7d"] + current_totals["neonatal_deaths_8_28d"]
    previous_deaths = previous_totals["neonatal_deaths_0_7d"] + previous_totals["neonatal_deaths_8_28d"]
    metrics.extend(
        _change_metrics(
            manifest,
            window,
            geography_level,
            geography_id,
            "neonatal_deaths_total",
            current_deaths,
            previous_deaths,
            "clinical_neonatal_monthly",
            ["neonatal_deaths_0_7d", "neonatal_deaths_8_28d"],
            facility_id=facility_id,
        )
    )
    return metrics


def _grouped_trend_metrics(
    manifest: UploadBatchManifest,
    window: ReportingWindow,
    current: pd.DataFrame,
    previous: pd.DataFrame,
    facilities: pd.DataFrame,
    geography: str,
) -> list[ReportMetric]:
    current_joined = current.merge(facilities[["facility_id", geography]], on="facility_id", how="left")
    previous_joined = previous.merge(facilities[["facility_id", geography]], on="facility_id", how="left")
    metrics: list[ReportMetric] = []
    for geography_id, group in current_joined.groupby(geography, dropna=False):
        previous_group = previous_joined[previous_joined[geography] == geography_id]
        metrics.extend(
            _trend_metrics(
                manifest,
                window,
                group,
                previous_group,
                geography,
                str(geography_id),
            )
        )
    return metrics


def _performance_score_metrics(
    manifest: UploadBatchManifest,
    window: ReportingWindow,
    governance: pd.DataFrame,
    operations: pd.DataFrame,
) -> list[ReportMetric]:
    joined = governance.merge(
        operations[["facility_id", "referral_feedback_rate"]],
        on="facility_id",
        how="left",
    )
    metrics: list[ReportMetric] = []
    component_columns = [
        "hmis_reporting_completeness",
        "death_audits_conducted_pct",
        "staff_trained_on_protocol_pct",
        "thermal_care_protocol_compliance",
        "infection_prevention_score",
        "referral_feedback_rate",
    ]
    for _, row in joined.iterrows():
        components = [float(row[column]) for column in component_columns if not pd.isna(row[column])]
        if row.get("quality_improvement_active") is True:
            components.append(1.0)
        elif row.get("quality_improvement_active") is False:
            components.append(0.0)
        score = sum(components) / len(components) * 100.0 if components else None
        metrics.append(
            _metric(
                manifest,
                window,
                "facility",
                str(row["facility_id"]),
                "facility_performance_score",
                score,
                "score_0_100",
                "governance_facility,operations_facility",
                component_columns + ["quality_improvement_active"],
                "mean available reporting/governance/quality/referral components * 100",
                facility_id=str(row["facility_id"]),
                trace_payload={"component_count": len(components)},
            )
        )
    return metrics


def _top_volume_rank_metrics(
    manifest: UploadBatchManifest,
    window: ReportingWindow,
    current: pd.DataFrame,
) -> list[ReportMetric]:
    totals = (
        current.groupby("facility_id", as_index=False)["total_deliveries"]
        .sum()
        .sort_values(["total_deliveries", "facility_id"], ascending=[False, True])
        .head(10)
    )
    metrics: list[ReportMetric] = []
    for rank, row in enumerate(totals.itertuples(index=False), start=1):
        metrics.append(
            _metric(
                manifest,
                window,
                "facility",
                str(row.facility_id),
                "top_volume_rank",
                float(rank),
                "rank",
                "clinical_neonatal_monthly",
                ["total_deliveries"],
                "dense rank by total deliveries over reporting period",
                facility_id=str(row.facility_id),
                trace_payload={"total_deliveries": float(row.total_deliveries)},
            )
        )
    return metrics


def _readiness_score_metrics(
    manifest: UploadBatchManifest,
    window: ReportingWindow,
    facilities: pd.DataFrame,
    governance: pd.DataFrame,
    operations: pd.DataFrame,
    workforce: pd.DataFrame,
) -> list[ReportMetric]:
    joined = (
        facilities.merge(governance, on="facility_id", how="left", suffixes=("", "_governance"))
        .merge(operations, on="facility_id", how="left", suffixes=("", "_operations"))
        .merge(workforce, on="facility_id", how="left", suffixes=("", "_workforce"))
    )
    metrics: list[ReportMetric] = []
    for _, row in joined.iterrows():
        facility_id = str(row["facility_id"])
        equipment = _mean_score(
            [
                _availability_score(row.get("nicu_available")),
                _positive_count_score(row.get("nicu_beds"), good=10),
                _positive_count_score(row.get("incubators_functional"), good=8),
                _positive_count_score(row.get("cpap_machines"), good=4),
                _positive_count_score(row.get("resuscitation_tables"), good=4),
                _positive_count_score(row.get("radiant_warmers"), good=6),
                _positive_count_score(row.get("phototherapy_units"), good=6),
            ]
        )
        workforce_score = _mean_score(
            [
                _positive_count_score(row.get("neonatal_trained_nurses"), good=10),
                _positive_count_score(row.get("pediatricians"), good=3),
                _positive_count_score(row.get("neonatologists"), good=1),
                _positive_count_score(row.get("staff_per_delivery_2024"), good=0.03),
                _availability_score(row.get("night_shift_coverage")),
            ]
        )
        operations_score = _mean_score(
            [
                _positive_count_score(row.get("oxygen_cylinders_available"), good=10),
                _positive_count_score(row.get("oxygen_concentrators"), good=5),
                1.0 if row.get("oxygen_plant") is True else 0.0,
                1.0 if row.get("ambulance_available") is True else 0.0,
                _availability_score(row.get("kangaroo_care_practiced")),
                _inverse_count_score(row.get("essential_drugs_stockouts_days"), bad=14),
                1.0 if row.get("surfactant_available") is True else 0.0,
                _frequency_score(row.get("antibiotics_available")),
            ]
        )
        governance_score = _mean_score(
            [
                _fraction(row.get("infection_prevention_score")),
                _fraction(row.get("thermal_care_protocol_compliance")),
                _fraction(row.get("staff_trained_on_protocol_pct")),
                _fraction(row.get("death_audits_conducted_pct")),
                1.0 if row.get("newborn_protocol_exists") is True else 0.0,
            ]
        )
        total = (
            equipment * 0.30
            + workforce_score * 0.25
            + operations_score * 0.25
            + governance_score * 0.20
        ) * 100.0
        components = {
            "equipment": equipment * 100.0,
            "workforce": workforce_score * 100.0,
            "operations": operations_score * 100.0,
            "governance": governance_score * 100.0,
        }
        for name, value in components.items():
            metrics.append(
                _metric(
                    manifest,
                    window,
                    "facility",
                    facility_id,
                    f"neonatal_readiness_{name}_subscore",
                    value,
                    "score_0_100",
                    "facilities,governance_facility,operations_facility,workforce_facility",
                    _readiness_source_fields(),
                    f"{name} readiness subscore normalized to 0-100",
                    facility_id=facility_id,
                    trace_payload={"component": name},
                )
            )
        metrics.append(
            _metric(
                manifest,
                window,
                "facility",
                facility_id,
                "neonatal_readiness_score",
                total,
                "score_0_100",
                "facilities,governance_facility,operations_facility,workforce_facility",
                _readiness_source_fields(),
                "weighted readiness score: equipment 30%, workforce 25%, operations 25%, governance 20%",
                facility_id=facility_id,
                trace_payload=components,
            )
        )
    return metrics


def _vulnerability_score_metrics(
    manifest: UploadBatchManifest,
    window: ReportingWindow,
    current: pd.DataFrame,
    previous: pd.DataFrame,
    facilities: pd.DataFrame,
    governance: pd.DataFrame,
    operations: pd.DataFrame,
    workforce: pd.DataFrame,
) -> list[ReportMetric]:
    current_by_facility = _facility_current_frame(current)
    previous_by_facility = _facility_current_frame(previous)
    readiness = {
        metric.facility_id: metric.metric_value or 0.0
        for metric in _readiness_score_metrics(manifest, window, facilities, governance, operations, workforce)
        if metric.metric_name == "neonatal_readiness_score"
    }
    joined = (
        current_by_facility.merge(previous_by_facility, on="facility_id", how="left", suffixes=("", "_previous"))
        .merge(operations[["facility_id", "avg_referral_time_hrs", "essential_drugs_stockouts_days"]], on="facility_id", how="left")
        .merge(workforce[["facility_id", "staff_per_delivery_2024"]], on="facility_id", how="left")
        .merge(governance[["facility_id", "hmis_reporting_completeness", "infection_prevention_score"]], on="facility_id", how="left")
    )
    max_deliveries = max(float(joined["total_deliveries"].max() or 1), 1.0)
    metrics: list[ReportMetric] = []
    scored_rows: list[dict[str, object]] = []
    for _, row in joined.iterrows():
        facility_id = str(row["facility_id"])
        deaths = float(row["neonatal_deaths_total"])
        live_births = float(row["live_births"] or 0)
        nmr = deaths / live_births * 1000 if live_births else 0.0
        previous_deaths = float(row.get("neonatal_deaths_total_previous") or 0)
        mortality_change = _bounded((deaths - previous_deaths) / max(previous_deaths, 1.0), 0.0, 3.0) / 3.0
        outcome_burden = _bounded(nmr / 80.0, 0.0, 1.0)
        workload = _bounded(float(row["total_deliveries"]) / max_deliveries, 0.0, 1.0)
        readiness_gap = 1.0 - _bounded(readiness.get(facility_id, 0.0) / 100.0, 0.0, 1.0)
        workforce_pressure = 1.0 - _positive_count_score(row.get("staff_per_delivery_2024"), good=0.03)
        operational_weakness = _mean_score(
            [
                _bounded(float(row.get("avg_referral_time_hrs") or 0) / 4.0, 0.0, 1.0),
                _bounded(float(row.get("essential_drugs_stockouts_days") or 0) / 14.0, 0.0, 1.0),
            ]
        )
        governance_weakness = 1.0 - _mean_score(
            [
                _fraction(row.get("hmis_reporting_completeness")),
                _fraction(row.get("infection_prevention_score")),
            ]
        )
        score = (
            outcome_burden * 0.25
            + mortality_change * 0.15
            + workload * 0.15
            + readiness_gap * 0.20
            + workforce_pressure * 0.10
            + operational_weakness * 0.10
            + governance_weakness * 0.05
        ) * 100.0
        components = {
            "outcome_burden": outcome_burden * 100.0,
            "mortality_change": mortality_change * 100.0,
            "workload": workload * 100.0,
            "readiness_gap": readiness_gap * 100.0,
            "workforce_pressure": workforce_pressure * 100.0,
            "operational_weakness": operational_weakness * 100.0,
            "governance_weakness": governance_weakness * 100.0,
        }
        explanation = _watchlist_explanation(components)
        scored_rows.append({"facility_id": facility_id, "score": score, "explanation": explanation})
        metrics.append(
            _metric(
                manifest,
                window,
                "facility",
                facility_id,
                "facility_vulnerability_score",
                score,
                "score_0_100",
                "clinical_neonatal_monthly,facilities,governance_facility,operations_facility,workforce_facility",
                [
                    "neonatal_deaths_0_7d",
                    "neonatal_deaths_8_28d",
                    "live_births",
                    "total_deliveries",
                    "avg_referral_time_hrs",
                    "essential_drugs_stockouts_days",
                    "staff_per_delivery_2024",
                    "hmis_reporting_completeness",
                    "infection_prevention_score",
                ],
                "weighted vulnerability score combining outcome burden, trend, workload, readiness gap, workforce, operations, and governance",
                facility_id=facility_id,
                trace_payload={**components, "explanation": explanation},
            )
        )
    for rank, row in enumerate(sorted(scored_rows, key=lambda item: (-float(item["score"]), str(item["facility_id"])))[:10], start=1):
        metrics.append(
            _metric(
                manifest,
                window,
                "facility",
                str(row["facility_id"]),
                "vulnerability_watchlist_rank",
                float(rank),
                "rank",
                "report_ready_metrics",
                ["facility_vulnerability_score"],
                "rank facilities by vulnerability score descending",
                facility_id=str(row["facility_id"]),
                trace_payload={"explanation": row["explanation"], "vulnerability_score": row["score"]},
            )
        )
    return metrics


def _anomaly_metrics(
    manifest: UploadBatchManifest,
    window: ReportingWindow,
    current: pd.DataFrame,
    previous: pd.DataFrame,
) -> list[ReportMetric]:
    current_by_facility = _facility_current_frame(current)
    previous_by_facility = _facility_current_frame(previous)
    joined = current_by_facility.merge(previous_by_facility, on="facility_id", how="left", suffixes=("", "_previous"))
    metrics: list[ReportMetric] = []
    for _, row in joined.iterrows():
        facility_id = str(row["facility_id"])
        anomaly_count = 0
        flags: list[str] = []
        deliveries = float(row["total_deliveries"])
        previous_deliveries = float(row.get("total_deliveries_previous") or 0)
        deaths = float(row["neonatal_deaths_total"])
        previous_deaths = float(row.get("neonatal_deaths_total_previous") or 0)
        if previous_deliveries >= 20 and deliveries <= previous_deliveries * 0.5:
            anomaly_count += 1
            flags.append("deliveries_dropped_by_at_least_50_percent")
        if previous_deaths >= 1 and deaths >= max(10, previous_deaths * 2):
            anomaly_count += 1
            flags.append("neonatal_deaths_doubled_or_exceeded_10")
        if deaths == 0 and deliveries >= 150:
            anomaly_count += 1
            flags.append("zero_deaths_with_high_delivery_volume")
        metrics.append(
            _metric(
                manifest,
                window,
                "facility",
                facility_id,
                "anomaly_flag_count",
                float(anomaly_count),
                "count",
                "clinical_neonatal_monthly",
                ["total_deliveries", "neonatal_deaths_0_7d", "neonatal_deaths_8_28d"],
                "count simple facility-level anomaly flags versus previous reporting period",
                facility_id=facility_id,
                trace_payload={"flags": flags},
            )
        )
    return metrics


def _clinical_totals(frame: pd.DataFrame) -> dict[str, float]:
    columns = (
        "total_deliveries",
        "live_births",
        "neonatal_deaths_0_7d",
        "neonatal_deaths_8_28d",
        "stillbirths",
        "death_birth_asphyxia",
        "death_prematurity",
        "death_sepsis",
        "death_congenital",
        "death_other",
        "preterm_births_28_32w",
        "preterm_births_32_37w",
        "apgar_less_7_at_5min",
        "birth_weight_less_2500g",
    )
    return {column: float(frame[column].sum()) if column in frame else 0.0 for column in columns}


def _facility_current_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "facility_id",
                "total_deliveries",
                "live_births",
                "neonatal_deaths_total",
                "stillbirths",
            ]
        )
    grouped = frame.groupby("facility_id", as_index=False).agg(
        total_deliveries=("total_deliveries", "sum"),
        live_births=("live_births", "sum"),
        neonatal_deaths_0_7d=("neonatal_deaths_0_7d", "sum"),
        neonatal_deaths_8_28d=("neonatal_deaths_8_28d", "sum"),
        stillbirths=("stillbirths", "sum"),
    )
    grouped["neonatal_deaths_total"] = (
        grouped["neonatal_deaths_0_7d"] + grouped["neonatal_deaths_8_28d"]
    )
    return grouped.drop(columns=["neonatal_deaths_0_7d", "neonatal_deaths_8_28d"])


def _readiness_source_fields() -> list[str]:
    return [
        "nicu_available",
        "nicu_beds",
        "incubators_functional",
        "cpap_machines",
        "resuscitation_tables",
        "radiant_warmers",
        "phototherapy_units",
        "neonatal_trained_nurses",
        "pediatricians",
        "neonatologists",
        "staff_per_delivery_2024",
        "night_shift_coverage",
        "oxygen_cylinders_available",
        "oxygen_concentrators",
        "oxygen_plant",
        "ambulance_available",
        "kangaroo_care_practiced",
        "essential_drugs_stockouts_days",
        "surfactant_available",
        "antibiotics_available",
        "infection_prevention_score",
        "thermal_care_protocol_compliance",
        "staff_trained_on_protocol_pct",
        "death_audits_conducted_pct",
        "newborn_protocol_exists",
    ]


def _availability_score(value: object) -> float:
    normalized = str(value).lower()
    if normalized in {"yes", "full", "true"}:
        return 1.0
    if normalized == "partial":
        return 0.5
    return 0.0


def _frequency_score(value: object) -> float:
    normalized = str(value).lower()
    return {
        "always": 1.0,
        "usually": 0.75,
        "rarely": 0.25,
        "never": 0.0,
    }.get(normalized, 0.0)


def _positive_count_score(value: object, good: float) -> float:
    if pd.isna(value) or good <= 0:
        return 0.0
    return _bounded(float(value) / good, 0.0, 1.0)


def _inverse_count_score(value: object, bad: float) -> float:
    if pd.isna(value) or bad <= 0:
        return 0.0
    return 1.0 - _bounded(float(value) / bad, 0.0, 1.0)


def _fraction(value: object) -> float:
    if pd.isna(value):
        return 0.0
    return _bounded(float(value), 0.0, 1.0)


def _mean_score(values: list[float]) -> float:
    usable = [value for value in values if not pd.isna(value)]
    return sum(usable) / len(usable) if usable else 0.0


def _bounded(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _watchlist_explanation(components: dict[str, float]) -> str:
    labels = {
        "outcome_burden": "high outcome burden",
        "mortality_change": "rising neonatal deaths",
        "workload": "high workload",
        "readiness_gap": "readiness gaps",
        "workforce_pressure": "workforce pressure",
        "operational_weakness": "operational bottlenecks",
        "governance_weakness": "governance weakness",
    }
    top = sorted(components.items(), key=lambda item: item[1], reverse=True)[:3]
    reasons = [labels[key] for key, value in top if value >= 25]
    if not reasons:
        reasons = [labels[top[0][0]]] if top else ["relative risk profile"]
    return "Flagged for " + ", ".join(reasons) + "."


def _rate_metric(
    manifest: UploadBatchManifest,
    window: ReportingWindow,
    geography_level: str,
    geography_id: str,
    metric_name: str,
    numerator: float,
    denominator: float,
    source_fields: list[str],
    calculation_rule: str,
    multiplier: float = RATE_PER_1000,
    metric_unit: str = "per_1000",
    facility_id: Optional[str] = None,
) -> ReportMetric:
    value = (numerator / denominator * multiplier) if denominator else None
    return _metric(
        manifest,
        window,
        geography_level,
        geography_id,
        metric_name,
        value,
        metric_unit,
        "clinical_neonatal_monthly",
        source_fields,
        calculation_rule,
        numerator=numerator,
        denominator=denominator,
        facility_id=facility_id,
    )


def _change_metrics(
    manifest: UploadBatchManifest,
    window: ReportingWindow,
    geography_level: str,
    geography_id: str,
    base_name: str,
    current_value: float,
    previous_value: float,
    source_table: str,
    source_fields: list[str],
    facility_id: Optional[str] = None,
) -> list[ReportMetric]:
    absolute = current_value - previous_value
    pct = (absolute / previous_value * 100.0) if previous_value else None
    direction = "up" if absolute > 0 else "down" if absolute < 0 else "flat"
    return [
        _metric(
            manifest,
            window,
            geography_level,
            geography_id,
            f"{base_name}_absolute_change",
            absolute,
            "count",
            source_table,
            source_fields,
            "current period value - previous period value",
            numerator=current_value,
            denominator=previous_value,
            facility_id=facility_id,
            trace_payload={"direction": direction},
        ),
        _metric(
            manifest,
            window,
            geography_level,
            geography_id,
            f"{base_name}_pct_change",
            pct,
            "percent",
            source_table,
            source_fields,
            "(current period value - previous period value) / previous period value * 100",
            numerator=absolute,
            denominator=previous_value,
            facility_id=facility_id,
            trace_payload={"direction": direction},
        ),
    ]


def _metric(
    manifest: UploadBatchManifest,
    window: ReportingWindow,
    geography_level: str,
    geography_id: str,
    metric_name: str,
    metric_value: Optional[float],
    metric_unit: Optional[str],
    source_table: str,
    source_fields: list[str],
    calculation_rule: str,
    numerator: Optional[float] = None,
    denominator: Optional[float] = None,
    facility_id: Optional[str] = None,
    trace_payload: Optional[dict[str, object]] = None,
) -> ReportMetric:
    return ReportMetric(
        tenant_id=manifest.tenant_id,
        country_code=manifest.country_code,
        metric_version=METRIC_VERSION,
        reporting_period_start=window.current_start,
        reporting_period_end=window.current_end,
        geography_level=geography_level,
        geography_id=geography_id,
        facility_id=facility_id,
        metric_name=metric_name,
        metric_value=metric_value,
        metric_unit=metric_unit,
        numerator=numerator,
        denominator=denominator,
        source_table=source_table,
        source_fields=source_fields,
        calculation_rule=calculation_rule,
        trace_payload=trace_payload or {},
    )
