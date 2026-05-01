"""Excel workbook generation from report-ready metrics."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from sand_bulletin.dashboard.data import (
    geography_metric_table,
    national_kpis,
    priority_intervention_table,
    top_facilities_by_metric,
)
from sand_bulletin.ingestion.batches import UploadBatchManifest
from sand_bulletin.ingestion.datasets import DatasetKind


def write_excel_workbook(
    path: Path,
    metrics: pd.DataFrame,
    issues: pd.DataFrame,
    manifest: UploadBatchManifest,
    resolution: pd.DataFrame | None = None,
) -> None:
    """Write the ministry review workbook."""

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        _summary_sheet(metrics, manifest).to_excel(writer, sheet_name="summary_kpis", index=False)
        _facility_rankings_sheet(metrics).to_excel(
            writer,
            sheet_name="facility_rankings",
            index=False,
        )
        priority_intervention_table(metrics).to_excel(
            writer,
            sheet_name="priority_facilities",
            index=False,
        )
        geography_metric_table(
            metrics,
            "district",
            [
                "total_deliveries",
                "live_births",
                "neonatal_mortality_rate_per_1000_live_births",
                "stillbirth_rate_per_1000_deliveries",
                "total_deliveries_pct_change",
                "neonatal_deaths_total_pct_change",
            ],
        ).to_excel(writer, sheet_name="district_trends", index=False)
        _clinical_indicators_sheet(metrics).to_excel(
            writer,
            sheet_name="clinical_indicators",
            index=False,
        )
        _readiness_scores_sheet(metrics).to_excel(
            writer,
            sheet_name="readiness_scores",
            index=False,
        )
        _watchlist_sheet(metrics).to_excel(
            writer,
            sheet_name="vulnerability_watchlist",
            index=False,
        )
        _nowcasts_sheet(metrics).to_excel(
            writer,
            sheet_name="nowcasts",
            index=False,
        )
        (resolution if resolution is not None else pd.DataFrame()).to_excel(
            writer,
            sheet_name="clinical_resolution",
            index=False,
        )
        issues.to_excel(writer, sheet_name="data_quality_issues", index=False)
        metrics.to_excel(writer, sheet_name="metric_trace", index=False)

        facility_source = manifest.datasets[DatasetKind.FACILITIES].frame
        facility_source.to_excel(writer, sheet_name="facilities", index=False)

        _format_workbook(writer.book)


def _summary_sheet(metrics: pd.DataFrame, manifest: UploadBatchManifest) -> pd.DataFrame:
    kpis = national_kpis(metrics)
    period_start = metrics["reporting_period_start"].iloc[0] if not metrics.empty else None
    period_end = metrics["reporting_period_end"].iloc[0] if not metrics.empty else None
    return pd.DataFrame(
        [
            {"metric": "tenant_id", "value": manifest.tenant_id, "unit": None},
            {"metric": "country_code", "value": manifest.country_code, "unit": None},
            {"metric": "reporting_period_start", "value": period_start, "unit": None},
            {"metric": "reporting_period_end", "value": period_end, "unit": None},
            {"metric": "total_deliveries", "value": kpis["total_deliveries"], "unit": "count"},
            {"metric": "live_births", "value": kpis["live_births"], "unit": "count"},
            {
                "metric": "neonatal_mortality_rate",
                "value": kpis["neonatal_mortality_rate_per_1000_live_births"],
                "unit": "per 1,000 live births",
            },
            {
                "metric": "stillbirth_rate",
                "value": kpis["stillbirth_rate_per_1000_deliveries"],
                "unit": "per 1,000 deliveries",
            },
            {
                "metric": "low_birth_weight_rate",
                "value": kpis["low_birth_weight_rate_pct"],
                "unit": "percent",
            },
            {"metric": "preterm_birth_rate", "value": kpis["preterm_birth_rate_pct"], "unit": "percent"},
        ]
    )


def _facility_rankings_sheet(metrics: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for label, metric_name in (
        ("deliveries", "total_deliveries"),
        ("neonatal_mortality", "neonatal_mortality_rate_per_1000_live_births"),
        ("performance", "facility_performance_score"),
    ):
        frame = top_facilities_by_metric(metrics, metric_name).copy()
        frame.insert(0, "ranking", label)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _clinical_indicators_sheet(metrics: pd.DataFrame) -> pd.DataFrame:
    indicators = [
        "total_deliveries",
        "live_births",
        "neonatal_mortality_rate_per_1000_live_births",
        "early_neonatal_mortality_rate_per_1000_live_births",
        "late_neonatal_mortality_rate_per_1000_live_births",
        "stillbirth_rate_per_1000_deliveries",
        "preterm_birth_rate_pct",
        "low_birth_weight_rate_pct",
        "low_apgar_rate_pct",
    ]
    rows = metrics[
        (metrics["geography_level"].isin(["national", "province", "district"]))
        & (metrics["metric_name"].isin(indicators))
    ]
    return rows[
        [
            "geography_level",
            "geography_id",
            "metric_name",
            "metric_value",
            "metric_unit",
            "numerator",
            "denominator",
        ]
    ].reset_index(drop=True)


def _readiness_scores_sheet(metrics: pd.DataFrame) -> pd.DataFrame:
    names = [
        "neonatal_readiness_score",
        "neonatal_readiness_equipment_subscore",
        "neonatal_readiness_workforce_subscore",
        "neonatal_readiness_operations_subscore",
        "neonatal_readiness_governance_subscore",
    ]
    return _facility_metric_pivot(metrics, names)


def _watchlist_sheet(metrics: pd.DataFrame) -> pd.DataFrame:
    names = ["facility_vulnerability_score", "vulnerability_watchlist_rank", "anomaly_flag_count"]
    table = _facility_metric_pivot(metrics, names)
    if table.empty or "vulnerability_watchlist_rank" not in table:
        return table
    return table.sort_values(
        ["vulnerability_watchlist_rank", "facility_vulnerability_score"],
        ascending=[True, False],
        na_position="last",
    ).reset_index(drop=True)


def _nowcasts_sheet(metrics: pd.DataFrame) -> pd.DataFrame:
    names = [
        "nowcast_expected_delivery_volume_next_month",
        "nowcast_expected_live_births_next_month",
        "nowcast_expected_high_risk_births_next_month",
        "nowcast_facility_stress_probability_next_month",
    ]
    return _facility_metric_pivot(metrics, names)


def _facility_metric_pivot(metrics: pd.DataFrame, metric_names: list[str]) -> pd.DataFrame:
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


def _format_workbook(workbook) -> None:
    for worksheet in workbook.worksheets:
        worksheet.freeze_panes = "A2"
        for column_cells in worksheet.columns:
            column_letter = column_cells[0].column_letter
            max_length = max(len(str(cell.value or "")) for cell in column_cells[:50])
            worksheet.column_dimensions[column_letter].width = min(max(max_length + 2, 12), 42)
