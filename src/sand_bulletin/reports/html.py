"""HTML bulletin rendering."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from sand_bulletin.data_quality import AnalysisMode
from sand_bulletin.dashboard.data import (
    driver_insights,
    geography_metric_table,
    national_kpis,
    priority_intervention_table,
    score_band,
    top_facilities_by_metric,
)
from sand_bulletin.ingestion.batches import UploadBatchManifest
from sand_bulletin.ingestion.datasets import DatasetKind
from sand_bulletin.narrative.models import NarrativeSummary
from sand_bulletin.reports.charts import build_chart_assets


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def render_bulletin_html(
    metrics: pd.DataFrame,
    issues: pd.DataFrame,
    manifest: UploadBatchManifest,
    run_id: str,
    narrative: NarrativeSummary | None = None,
    resolution: pd.DataFrame | None = None,
    analysis_mode: AnalysisMode | str = AnalysisMode.VALIDATED,
) -> str:
    """Render the bulletin HTML from report-ready metrics."""

    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("bulletin.html.j2")
    period_start = metrics["reporting_period_start"].iloc[0] if not metrics.empty else None
    period_end = metrics["reporting_period_end"].iloc[0] if not metrics.empty else None
    kpis = national_kpis(metrics)
    high_count = int((issues["severity"] == "high").sum()) if not issues.empty else 0
    mode = AnalysisMode(analysis_mode)
    resolution_summary = _resolution_summary(resolution)
    suppress_decisions = mode == AnalysisMode.RAW
    charts = build_chart_assets(metrics, issues, manifest, mode)
    facility_labels = _facility_labels(manifest)
    briefs = _section_briefs(metrics, issues, kpis, resolution_summary, mode, facility_labels)
    priority_table = priority_intervention_table(metrics, limit=5)
    if not priority_table.empty:
        priority_table = _add_facility_display(priority_table, facility_labels)

    return template.render(
        run_id=run_id,
        tenant_id=manifest.tenant_id,
        country_code=manifest.country_code,
        period_start=period_start,
        period_end=period_end,
        kpis=kpis,
        reliability_status=_reliability_status(issues),
        high_issue_count=high_count,
        is_preview=high_count > 0,
        analysis_mode=mode.value,
        resolution_summary=resolution_summary,
        dq_summary=_dq_summary(issues),
        charts=charts,
        briefs=briefs,
        decision_outputs_suppressed=suppress_decisions,
        priority_facilities=[] if suppress_decisions else _records(priority_table),
        driver_insights=[] if suppress_decisions else driver_insights(metrics),
        qoq_table=_records(_qoq_table(metrics)),
        cause_table=_records(_cause_share_table(metrics)),
        special_facilities=_special_facility_groups(metrics, facility_labels),
        province_table=_records(
            geography_metric_table(
                metrics,
                "province",
                [
                    "total_deliveries",
                    "live_births",
                    "neonatal_mortality_rate_per_1000_live_births",
                    "stillbirth_rate_per_1000_deliveries",
                ],
            )
        ),
        district_trends=_records(
            geography_metric_table(
                metrics,
                "district",
                [
                    "total_deliveries_pct_change",
                    "neonatal_deaths_total_pct_change",
                    "stillbirths_pct_change",
                ],
            )
        ),
        top_volume=_records(_add_facility_display(top_facilities_by_metric(metrics, "total_deliveries"), facility_labels)),
        top_mortality=_records(
            _add_facility_display(
                top_facilities_by_metric(metrics, "neonatal_mortality_rate_per_1000_live_births"),
                facility_labels,
            )
        ),
        top_performance=_records(_add_facility_display(top_facilities_by_metric(metrics, "facility_performance_score"), facility_labels)),
        top_readiness=_records(_add_facility_display(top_facilities_by_metric(metrics, "neonatal_readiness_score"), facility_labels)),
        top_vulnerability=_records(_add_facility_display(top_facilities_by_metric(metrics, "facility_vulnerability_score"), facility_labels)),
        top_nowcast_deliveries=_records(
            _add_facility_display(top_facilities_by_metric(metrics, "nowcast_expected_delivery_volume_next_month"), facility_labels)
        ),
        top_nowcast_stress=_records(
            _add_facility_display(top_facilities_by_metric(metrics, "nowcast_facility_stress_probability_next_month"), facility_labels)
        ),
        watchlist=_watchlist_records(metrics, facility_labels),
        issue_counts=issues["severity"].value_counts().to_dict() if not issues.empty else {},
        issue_examples=_records(issues.head(12)),
        metric_count=len(metrics),
        issue_count=len(issues),
        narrative=narrative,
        format_number=_format_number,
        score_band=score_band,
    )


def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
    if frame.empty:
        return []
    return frame.where(pd.notna(frame), None).to_dict(orient="records")


def _watchlist_records(metrics: pd.DataFrame, labels: dict[str, str]) -> list[dict[str, object]]:
    if metrics.empty:
        return []
    rows = metrics[
        (metrics["geography_level"] == "facility")
        & (metrics["metric_name"] == "vulnerability_watchlist_rank")
    ].copy()
    if rows.empty:
        return []
    return _records(_add_facility_display(rows.sort_values(["metric_value", "facility_id"]).head(10), labels))


def _format_number(value: object, decimals: int = 1) -> str:
    if value is None or pd.isna(value):
        return "-"
    if isinstance(value, str):
        return value
    return f"{float(value):,.{decimals}f}"


def _reliability_status(issues: pd.DataFrame) -> dict[str, object]:
    if issues.empty:
        return {
            "label": "Ready for publication",
            "tone": "ready",
            "message": "No data quality issues were detected.",
        }
    high_count = int((issues["severity"] == "high").sum())
    if high_count:
        duplicate_count = int((issues["issue_type"] == "duplicate_facility_month").sum())
        conflict_count = int((issues["issue_type"] == "conflicting_facility_month_submission").sum())
        return {
            "label": "Critical review required",
            "tone": "critical",
            "message": (
                f"{high_count} high-severity issues were detected"
                + (
                    f", including {conflict_count} conflicting facility-month submission records"
                    if conflict_count
                    else ""
                )
                + (f" and {duplicate_count} exact duplicate report records" if duplicate_count else "")
                + ". Official publication should remain blocked until these are resolved or formally signed off."
            ),
        }
    return {
        "label": "Review recommended",
        "tone": "warning",
        "message": "Non-critical data quality issues were detected and should be reviewed before publication.",
    }


def _resolution_summary(resolution: pd.DataFrame | None) -> dict[str, object]:
    if resolution is None or resolution.empty:
        return {
            "decision_count": 0,
            "selected_groups": 0,
            "unresolved_groups": 0,
            "excluded_rows": 0,
        }
    selected = resolution["selected_row"].notna()
    unresolved = resolution["selected_row"].isna()
    rejected_count = resolution["rejected_rows"].fillna("").apply(
        lambda value: len([part for part in str(value).split(", ") if part])
    )
    return {
        "decision_count": int(len(resolution)),
        "selected_groups": int(selected.sum()),
        "unresolved_groups": int(unresolved.sum()),
        "excluded_rows": int(rejected_count.sum()),
    }


def _dq_summary(issues: pd.DataFrame) -> dict[str, object]:
    if issues.empty:
        return {
            "affected_months": "None",
            "affected_facilities": 0,
            "publication_status": "Ready for official publication",
        }
    months = sorted(str(value) for value in issues["reporting_month"].dropna().unique())
    high_count = int((issues["severity"] == "high").sum())
    return {
        "affected_months": ", ".join(months[:8]) + ("..." if len(months) > 8 else ""),
        "affected_facilities": int(issues["facility_id"].dropna().nunique()),
        "publication_status": (
            "Official publication should remain blocked until these issues are resolved or formally signed off."
            if high_count
            else "Metrics are suitable for preview and publication after routine review."
        ),
    }


def _section_briefs(
    metrics: pd.DataFrame,
    issues: pd.DataFrame,
    kpis: dict[str, float | None],
    resolution_summary: dict[str, object],
    mode: AnalysisMode,
    facility_labels: dict[str, str],
) -> dict[str, object]:
    province = geography_metric_table(
        metrics,
        "province",
        ["total_deliveries", "neonatal_mortality_rate_per_1000_live_births"],
    )
    top_province = None
    high_nmr_province = None
    if not province.empty:
        top_province_row = province.loc[province["total_deliveries"].idxmax()]
        high_nmr_row = province.loc[province["neonatal_mortality_rate_per_1000_live_births"].idxmax()]
        top_province = {
            "name": top_province_row["geography_id"],
            "deliveries": float(top_province_row["total_deliveries"]),
        }
        high_nmr_province = {
            "name": high_nmr_row["geography_id"],
            "nmr": float(high_nmr_row["neonatal_mortality_rate_per_1000_live_births"]),
        }

    priority = priority_intervention_table(metrics, limit=5)
    top_priority = None if priority.empty else priority.iloc[0].to_dict()
    top_priority_name = (
        facility_labels.get(str(top_priority["facility_id"]), str(top_priority["facility_id"]))
        if top_priority
        else None
    )
    high_count = int((issues["severity"] == "high").sum()) if not issues.empty else 0
    early = _national_metric(metrics, "early_neonatal_mortality_rate_per_1000_live_births")
    late = _national_metric(metrics, "late_neonatal_mortality_rate_per_1000_live_births")
    return {
        "headline": (
            f"The {mode.value} analysis contains {kpis.get('total_deliveries') or 0:,.0f} deliveries, "
            f"{kpis.get('live_births') or 0:,.0f} live births, and an NMR of "
            f"{kpis.get('neonatal_mortality_rate_per_1000_live_births') or 0:.1f} deaths per 1,000 live births."
        ),
        "reliability": (
            f"Data quality review found {high_count:,} high-severity issues. "
            f"The selected mode excluded {resolution_summary.get('excluded_rows', 0):,} unresolved conflict rows."
            if high_count
            else "No high-severity issues were detected in this run."
        ),
        "geography": (
            f"{top_province['name']} contributed the largest delivery volume ({top_province['deliveries']:,.0f}), "
            f"while {high_nmr_province['name']} had the highest provincial NMR "
            f"({high_nmr_province['nmr']:.1f} per 1,000 live births)."
            if top_province and high_nmr_province
            else "Province-level comparisons are unavailable for this run."
        ),
        "priority": (
            f"{top_priority_name} is the highest-ranked intervention facility, with a priority score of "
            f"{float(top_priority['priority_score']):.1f}. The ranking combines mortality, volume, and vulnerability."
            if top_priority
            else "Priority ranking is unavailable in this run."
        ),
        "early_late": (
            f"Early neonatal mortality is {early:.1f} per 1,000 live births and late neonatal mortality is {late:.1f} per 1,000 live births."
            if early is not None and late is not None
            else "Early versus late neonatal mortality metrics are unavailable for this run."
        ),
        "recommendations": _action_recommendations(priority, issues, mode, facility_labels),
    }


def _action_recommendations(
    priority: pd.DataFrame,
    issues: pd.DataFrame,
    mode: AnalysisMode,
    facility_labels: dict[str, str],
) -> dict[str, list[str]]:
    recommendations: dict[str, list[str]] = {
        "immediate": [],
        "validation": [],
        "facility_support": [],
        "program": [],
        "monitoring": [],
    }
    if mode == AnalysisMode.RAW:
        recommendations["validation"].append("Use raw mode only for audit/debugging; do not use it for operational decisions.")
    if not issues.empty and (issues["issue_type"] == "conflicting_facility_month_submission").any():
        recommendations["validation"].append("Reconcile January and March conflicting facility-month submissions before full-year interpretation.")
    if not priority.empty:
        top = priority.head(3)
        names = [facility_labels.get(str(row["facility_id"]), str(row["facility_id"])) for _, row in top.iterrows()]
        recommendations["immediate"].append(
            "Prioritize immediate review at " + ", ".join(names)
            + " based on combined mortality, volume, and vulnerability signals."
        )
        first = top.iloc[0]
        recommendations["facility_support"].append(
            f"Deploy a rapid support package for {facility_labels.get(str(first['facility_id']), str(first['facility_id']))}: clinical audit, staffing review, and readiness gap check."
        )
    recommendations["program"].append("Use province and facility charts to focus supervision where mortality, volume, and readiness gaps overlap.")
    recommendations["monitoring"].append("Track the same priority facilities in the next bulletin and compare NMR, readiness, and vulnerability movement.")
    recommendations["validation"].append("Use the Excel metric trace and clinical resolution sheets for source-field audit before publication.")
    return recommendations


def _facility_labels(manifest: UploadBatchManifest) -> dict[str, str]:
    facilities = manifest.datasets[DatasetKind.FACILITIES].frame
    labels: dict[str, str] = {}
    for _, row in facilities.iterrows():
        facility_id = str(row["facility_id"])
        name = str(row.get("facility_name") or facility_id)
        labels[facility_id] = f"{name} ({facility_id})" if name != facility_id else facility_id
    return labels


def _add_facility_display(frame: pd.DataFrame, labels: dict[str, str]) -> pd.DataFrame:
    if frame.empty or "facility_id" not in frame:
        return frame
    updated = frame.copy()
    updated["facility_display"] = updated["facility_id"].map(lambda value: labels.get(str(value), str(value)))
    return updated


def _national_metric(metrics: pd.DataFrame, name: str) -> float | None:
    rows = metrics[
        (metrics["geography_level"] == "national")
        & (metrics["geography_id"] == "national")
        & (metrics["metric_name"] == name)
    ]
    if rows.empty or pd.isna(rows.iloc[0]["metric_value"]):
        return None
    return float(rows.iloc[0]["metric_value"])


def _qoq_table(metrics: pd.DataFrame) -> pd.DataFrame:
    names = [
        ("Deliveries", "total_deliveries", "lower"),
        ("Live births", "live_births", "lower"),
        ("Neonatal deaths", "neonatal_deaths_total", "higher"),
        ("Stillbirths", "stillbirths", "higher"),
    ]
    rows: list[dict[str, object]] = []
    for label, metric_name, unfavorable in names:
        current = _national_current_value(metrics, metric_name)
        absolute = _national_metric(metrics, f"{metric_name}_absolute_change")
        pct = _national_metric(metrics, f"{metric_name}_pct_change")
        if current is None or absolute is None:
            continue
        previous = current - absolute
        direction = "better" if (
            (unfavorable == "higher" and absolute < 0)
            or (unfavorable == "lower" and absolute > 0)
        ) else "worse" if absolute else "flat"
        rows.append(
            {
                "indicator": label,
                "previous": previous,
                "current": current,
                "pct_change": pct,
                "signal": direction,
            }
        )
    return pd.DataFrame(rows)


def _national_current_value(metrics: pd.DataFrame, metric_name: str) -> float | None:
    if metric_name == "neonatal_deaths_total":
        early = _national_metric(metrics, "neonatal_deaths_0_7d")
        late = _national_metric(metrics, "neonatal_deaths_8_28d")
        return None if early is None or late is None else early + late
    return _national_metric(metrics, metric_name)


def _cause_share_table(metrics: pd.DataFrame) -> pd.DataFrame:
    rows = metrics[
        (metrics["geography_level"] == "national")
        & (metrics["metric_name"].str.startswith("death_"))
        & (metrics["metric_name"].str.endswith("_share_pct"))
    ].copy()
    if rows.empty:
        return pd.DataFrame(columns=["cause", "share_pct"])
    rows["cause"] = rows["metric_name"].str.replace("death_", "", regex=False).str.replace("_share_pct", "", regex=False).str.replace("_", " ").str.title()
    rows = rows.rename(columns={"metric_value": "share_pct"})
    return rows[["cause", "share_pct"]].sort_values("share_pct", ascending=False)


def _special_facility_groups(metrics: pd.DataFrame, labels: dict[str, str]) -> dict[str, list[dict[str, object]]]:
    from sand_bulletin.dashboard.data import facility_metric_table

    table = facility_metric_table(
        metrics,
        [
            "total_deliveries",
            "neonatal_mortality_rate_per_1000_live_births",
            "neonatal_readiness_score",
            "facility_vulnerability_score",
        ],
    )
    if table.empty:
        return {"high_volume_high_risk": [], "high_mortality_low_readiness": [], "high_readiness_poor_outcomes": [], "unusually_low_nmr": []}
    for column in table.columns:
        if column != "facility_id":
            table[column] = pd.to_numeric(table[column], errors="coerce")
    volume_cutoff = table["total_deliveries"].quantile(0.75)
    nmr_high = table["neonatal_mortality_rate_per_1000_live_births"].quantile(0.85)
    nmr_low = table["neonatal_mortality_rate_per_1000_live_births"].quantile(0.05)
    groups = {
        "high_volume_high_risk": table[
            (table["total_deliveries"] >= volume_cutoff)
            & (table["facility_vulnerability_score"] >= 60)
        ].sort_values("facility_vulnerability_score", ascending=False).head(6),
        "high_mortality_low_readiness": table[
            (table["neonatal_mortality_rate_per_1000_live_births"] >= nmr_high)
            & (table["neonatal_readiness_score"] < 60)
        ].sort_values("neonatal_mortality_rate_per_1000_live_births", ascending=False).head(6),
        "high_readiness_poor_outcomes": table[
            (table["neonatal_readiness_score"] >= 60)
            & (table["neonatal_mortality_rate_per_1000_live_births"] >= nmr_high)
        ].sort_values("neonatal_mortality_rate_per_1000_live_births", ascending=False).head(6),
        "unusually_low_nmr": table[
            table["neonatal_mortality_rate_per_1000_live_births"] <= nmr_low
        ].sort_values("neonatal_mortality_rate_per_1000_live_births").head(6),
    }
    return {
        name: _records(_add_facility_display(frame, labels))
        for name, frame in groups.items()
    }
