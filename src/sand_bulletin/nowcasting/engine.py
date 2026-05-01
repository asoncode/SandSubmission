"""Baseline-tested nowcasting for a small set of facility planning indicators."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional

import pandas as pd

from sand_bulletin.analytics.metrics import ReportMetric
from sand_bulletin.data_quality import (
    AnalysisMode,
    DataQualitySummary,
    resolve_clinical_submissions,
    validate_upload_batch,
)
from sand_bulletin.ingestion.batches import UploadBatchManifest
from sand_bulletin.ingestion.datasets import DatasetKind


NOWCAST_METRIC_VERSION = "slice8_nowcast_v1"
MIN_HISTORY_MONTHS = 5
MIN_BACKTEST_PERIODS = 2
TARGET_LABEL = "Estimated current value based on historical reporting patterns; not official reported data."


class NowcastingBlockedError(RuntimeError):
    """Raised when data quality prevents nowcasting without an explicit override."""


@dataclass(frozen=True)
class BacktestResult:
    """Backtest comparison between last-value baseline and a transparent candidate model."""

    model_name: str
    baseline_mae: float
    model_mae: float
    periods: int

    @property
    def beats_baseline(self) -> bool:
        """Return true when the model strictly improves on the last-value baseline."""

        return self.periods >= MIN_BACKTEST_PERIODS and self.model_mae < self.baseline_mae


def build_nowcast_metrics(
    manifest: UploadBatchManifest,
    quality_summary: Optional[DataQualitySummary] = None,
    allow_high_severity: bool = False,
    analysis_mode: AnalysisMode | str = AnalysisMode.VALIDATED,
) -> list[ReportMetric]:
    """Build next-month facility nowcasts only where backtesting beats the baseline."""

    summary = quality_summary or validate_upload_batch(manifest)
    mode = AnalysisMode(analysis_mode)
    blocking = [
        issue
        for issue in summary.issues
        if issue.severity.value == "high"
        and (mode == AnalysisMode.RAW or issue.issue_type not in {"conflicting_facility_month_submission", "low_reporting_completeness"})
    ]
    if blocking and not allow_high_severity:
        raise NowcastingBlockedError(
            f"Nowcasting blocked by {len(blocking)} unresolved high-severity data quality issues."
        )

    resolution = resolve_clinical_submissions(
        manifest.datasets[DatasetKind.CLINICAL_NEONATAL].frame,
        mode,
    )
    clinical = _monthly_facility_frame(
        resolution.frame
    )
    operations = manifest.datasets[DatasetKind.OPERATIONS].frame
    if clinical.empty:
        return []

    last_month = max(clinical["reporting_month"].dropna())
    forecast_month = _add_month(last_month)
    metrics: list[ReportMetric] = []

    for facility_id, group in clinical.groupby("facility_id"):
        ordered = group.sort_values("reporting_month").reset_index(drop=True)
        if len(ordered) < MIN_HISTORY_MONTHS:
            continue

        target_results = {
            "nowcast_expected_delivery_volume_next_month": _target_metric(
                manifest,
                str(facility_id),
                forecast_month,
                ordered,
                "total_deliveries",
                "estimated_count",
                "Transparent model selected by rolling-origin backtest against last-value baseline.",
            ),
            "nowcast_expected_live_births_next_month": _target_metric(
                manifest,
                str(facility_id),
                forecast_month,
                ordered,
                "live_births",
                "estimated_count",
                "Transparent model selected by rolling-origin backtest against last-value baseline.",
            ),
            "nowcast_expected_high_risk_births_next_month": _target_metric(
                manifest,
                str(facility_id),
                forecast_month,
                ordered,
                "high_risk_births",
                "estimated_count",
                "Preterm plus low-birth-weight burden proxy selected by rolling-origin backtest.",
            ),
        }
        emitted = {name: metric for name, metric in target_results.items() if metric is not None}
        metrics.extend(emitted.values())

        stress_metric = _stress_metric(
            manifest,
            str(facility_id),
            forecast_month,
            ordered,
            operations,
            emitted,
        )
        if stress_metric is not None:
            metrics.append(stress_metric)

    return metrics


def _monthly_facility_frame(clinical: pd.DataFrame) -> pd.DataFrame:
    grouped = clinical.groupby(["facility_id", "reporting_month"], as_index=False).agg(
        total_deliveries=("total_deliveries", "sum"),
        live_births=("live_births", "sum"),
        preterm_births_28_32w=("preterm_births_28_32w", "sum"),
        preterm_births_32_37w=("preterm_births_32_37w", "sum"),
        birth_weight_less_2500g=("birth_weight_less_2500g", "sum"),
    )
    grouped["high_risk_births"] = (
        grouped["preterm_births_28_32w"]
        + grouped["preterm_births_32_37w"]
        + grouped["birth_weight_less_2500g"]
    )
    grouped["stress_proxy"] = grouped.apply(_stress_proxy_value, axis=1)
    return grouped


def _target_metric(
    manifest: UploadBatchManifest,
    facility_id: str,
    forecast_month: date,
    frame: pd.DataFrame,
    target_column: str,
    metric_unit: str,
    calculation_rule: str,
) -> ReportMetric | None:
    values = [float(value) for value in frame[target_column].tolist()]
    backtest = _best_backtest(values)
    if backtest is None or not backtest.beats_baseline:
        return None

    forecast_value = _forecast(values, backtest.model_name)
    return _metric(
        manifest,
        facility_id,
        forecast_month,
        f"nowcast_expected_{_target_alias(target_column)}_next_month",
        forecast_value,
        metric_unit,
        ["facility_id", "reporting_month", target_column],
        calculation_rule,
        numerator=backtest.model_mae,
        denominator=backtest.baseline_mae,
        trace_payload=_trace(backtest, target_column),
    )


def _stress_metric(
    manifest: UploadBatchManifest,
    facility_id: str,
    forecast_month: date,
    frame: pd.DataFrame,
    operations: pd.DataFrame,
    emitted_targets: dict[str, ReportMetric],
) -> ReportMetric | None:
    values = [float(value) for value in frame["stress_proxy"].tolist()]
    backtest = _best_backtest(values)
    if backtest is None or not backtest.beats_baseline:
        return None

    forecast_value = _bounded(_forecast(values, backtest.model_name), 0.0, 1.0)
    delivery = emitted_targets.get("nowcast_expected_delivery_volume_next_month")
    high_risk = emitted_targets.get("nowcast_expected_high_risk_births_next_month")
    if delivery is not None and high_risk is not None and delivery.metric_value:
        forecast_value = _bounded(
            forecast_value * 0.75
            + _bounded((high_risk.metric_value or 0.0) / delivery.metric_value, 0.0, 1.0) * 0.25,
            0.0,
            1.0,
        )

    operational_context = _operational_context(operations, facility_id)
    trace = _trace(backtest, "stress_proxy")
    trace.update(operational_context)
    return _metric(
        manifest,
        facility_id,
        forecast_month,
        "nowcast_facility_stress_probability_next_month",
        forecast_value,
        "probability",
        [
            "facility_id",
            "reporting_month",
            "total_deliveries",
            "live_births",
            "high_risk_births",
            "essential_drugs_stockouts_days",
            "avg_referral_time_hrs",
        ],
        "Backtested stress proxy from delivery pressure and high-risk burden; operations context retained for interpretation.",
        numerator=backtest.model_mae,
        denominator=backtest.baseline_mae,
        trace_payload=trace,
    )


def _best_backtest(values: list[float]) -> BacktestResult | None:
    if len(values) < MIN_HISTORY_MONTHS:
        return None
    candidates: dict[str, Callable[[list[float]], float]] = {
        "rolling_3_month_mean": _rolling_mean_forecast,
        "three_month_trend": _trend_forecast,
    }
    baseline_errors: list[float] = []
    candidate_errors: dict[str, list[float]] = {name: [] for name in candidates}
    for index in range(3, len(values)):
        history = values[:index]
        actual = values[index]
        baseline_errors.append(abs(history[-1] - actual))
        for name, predictor in candidates.items():
            candidate_errors[name].append(abs(predictor(history) - actual))

    if not baseline_errors:
        return None
    baseline_mae = _mean(baseline_errors)
    results = [
        BacktestResult(name, baseline_mae, _mean(errors), len(errors))
        for name, errors in candidate_errors.items()
        if errors
    ]
    return min(results, key=lambda result: (result.model_mae, result.model_name)) if results else None


def _forecast(values: list[float], model_name: str) -> float:
    if model_name == "three_month_trend":
        return _trend_forecast(values)
    return _rolling_mean_forecast(values)


def _rolling_mean_forecast(values: list[float]) -> float:
    return max(0.0, _mean(values[-3:]))


def _trend_forecast(values: list[float]) -> float:
    recent = values[-3:]
    if len(recent) < 3:
        return _rolling_mean_forecast(values)
    average_delta = ((recent[1] - recent[0]) + (recent[2] - recent[1])) / 2.0
    return max(0.0, recent[-1] + average_delta)


def _stress_proxy_value(row: pd.Series) -> float:
    deliveries = float(row["total_deliveries"] or 0)
    live_births = float(row["live_births"] or 0)
    high_risk = float(row["high_risk_births"] or 0)
    delivery_pressure = _bounded(deliveries / 350.0, 0.0, 1.0)
    high_risk_rate = _bounded(high_risk / live_births, 0.0, 1.0) if live_births else 0.0
    return delivery_pressure * 0.65 + high_risk_rate * 0.35


def _operational_context(operations: pd.DataFrame, facility_id: str) -> dict[str, object]:
    rows = operations[operations["facility_id"] == facility_id]
    if rows.empty:
        return {}
    row = rows.iloc[0]
    return {
        "essential_drugs_stockouts_days": _optional_float(row.get("essential_drugs_stockouts_days")),
        "avg_referral_time_hrs": _optional_float(row.get("avg_referral_time_hrs")),
    }


def _metric(
    manifest: UploadBatchManifest,
    facility_id: str,
    forecast_month: date,
    metric_name: str,
    metric_value: Optional[float],
    metric_unit: str,
    source_fields: list[str],
    calculation_rule: str,
    numerator: Optional[float] = None,
    denominator: Optional[float] = None,
    trace_payload: Optional[dict[str, object]] = None,
) -> ReportMetric:
    return ReportMetric(
        tenant_id=manifest.tenant_id,
        country_code=manifest.country_code,
        metric_version=NOWCAST_METRIC_VERSION,
        reporting_period_start=forecast_month,
        reporting_period_end=forecast_month,
        geography_level="facility",
        geography_id=facility_id,
        facility_id=facility_id,
        metric_name=metric_name,
        metric_value=metric_value,
        metric_unit=metric_unit,
        numerator=numerator,
        denominator=denominator,
        source_table="clinical_neonatal_monthly,operations_facility",
        source_fields=source_fields,
        calculation_rule=calculation_rule,
        trace_payload=trace_payload or {},
    )


def _trace(backtest: BacktestResult, target_column: str) -> dict[str, object]:
    improvement = (
        (backtest.baseline_mae - backtest.model_mae) / backtest.baseline_mae
        if backtest.baseline_mae
        else 0.0
    )
    return {
        "label": TARGET_LABEL,
        "target_column": target_column,
        "model": backtest.model_name,
        "baseline": "last_observed_value",
        "baseline_mae": backtest.baseline_mae,
        "model_mae": backtest.model_mae,
        "mae_improvement_pct": improvement * 100.0,
        "backtest_periods": backtest.periods,
    }


def _target_alias(target_column: str) -> str:
    return {
        "total_deliveries": "delivery_volume",
        "live_births": "live_births",
        "high_risk_births": "high_risk_births",
    }[target_column]


def _add_month(month: date) -> date:
    year = month.year + (1 if month.month == 12 else 0)
    next_month = 1 if month.month == 12 else month.month + 1
    return date(year, next_month, 1)


def _optional_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _bounded(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
