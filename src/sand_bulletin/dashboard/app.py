"""Streamlit operational bulletin dashboard."""

from __future__ import annotations

import os
from textwrap import dedent
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from sand_bulletin.config import get_settings
from sand_bulletin.data_quality import AnalysisMode
from sand_bulletin.dashboard.data import (
    build_dashboard_dataset,
    driver_insights,
    facility_metric_table,
    geography_metric_table,
    national_kpis,
    priority_intervention_table,
    score_band,
    top_facilities_by_metric,
)
from sand_bulletin.ingestion import build_upload_batch_manifest
from sand_bulletin.ingestion.datasets import DatasetKind
from sand_bulletin.reports import generate_reports


def main() -> None:
    """Run the Streamlit dashboard."""

    st.set_page_config(page_title="Sand Health Bulletin", layout="wide")
    settings = get_settings()
    _inject_styles()

    st.markdown(_hero_markup(), unsafe_allow_html=True)

    with st.sidebar:
        st.header("Data")
        data_dir = Path(st.text_input("Data directory", value=str(settings.data_dir)))
        tenant_id = st.text_input("Tenant", value=settings.tenant_id)
        country_code = st.text_input("Country code", value=settings.country_code)
        analysis_mode = st.selectbox(
            "Analysis mode",
            [mode.value for mode in AnalysisMode],
            index=0,
            help="validated excludes unresolved duplicate facility-month records; best_effort selects when confidence is adequate; raw includes all rows.",
        )
        allow_high = st.checkbox("Use explicit DQ override", value=False)
        refresh = st.button("Refresh")

    dataset = _load_dashboard_dataset(data_dir, tenant_id, country_code, analysis_mode, allow_high, refresh)
    summary = dataset.quality_summary

    _reliability_banner(summary.high_count, summary.issue_count, allow_high)

    if dataset.analytics_blocked:
        st.error(dataset.block_reason)
        st.info("Resolve high-severity data quality issues or use an explicit override after review.")
    elif dataset.metrics:
        period_start = dataset.metrics[0].reporting_period_start
        period_end = dataset.metrics[0].reporting_period_end
        st.success(f"Report-ready metrics loaded for {period_start} to {period_end}.")

    tabs = st.tabs(["Command Center", "Facilities", "Quality", "Trends", "Map", "Report"])

    with tabs[0]:
        _overview_tab(dataset.metrics_frame, summary.high_count, summary.issue_count)

    with tabs[1]:
        _facilities_tab(dataset.metrics_frame)

    with tabs[2]:
        _quality_tab(dataset.issues_frame, dataset.resolution_frame)

    with tabs[3]:
        _trends_tab(dataset.metrics_frame)

    with tabs[4]:
        _map_tab(data_dir, dataset.metrics_frame)

    with tabs[5]:
        _report_tab(
            dataset,
            data_dir,
            tenant_id,
            country_code,
            settings.output_dir,
            allow_high,
        )


@st.cache_data(show_spinner=False)
def _load_dashboard_dataset(
    data_dir: Path,
    tenant_id: str,
    country_code: str,
    analysis_mode: str,
    allow_high_severity: bool,
    refresh: bool,
):
    _ = refresh
    manifest = build_upload_batch_manifest(data_dir, tenant_id, country_code)
    return build_dashboard_dataset(
        manifest,
        allow_high_severity=allow_high_severity,
        analysis_mode=analysis_mode,
    )


def _overview_tab(metrics: pd.DataFrame, high_count: int, issue_count: int) -> None:
    st.subheader("Command Center")
    if metrics.empty:
        st.warning("Metrics are unavailable while analytics are blocked.")
        return
    st.caption(f"Analysis mode: {metrics.iloc[0]['trace_payload'].get('analysis_mode', 'unknown')}")

    kpis = national_kpis(metrics)
    cols = st.columns(4)
    cols[0].metric("Deliveries", _format_number(kpis["total_deliveries"]))
    cols[1].metric("Live births", _format_number(kpis["live_births"]))
    cols[2].metric(
        "Neonatal mortality",
        f"{_format_number(kpis['neonatal_mortality_rate_per_1000_live_births'], 1)} / 1,000",
        help="Deaths per 1,000 live births",
    )
    cols[3].metric(
        "Data reliability",
        "Critical" if high_count else "Ready",
        f"{issue_count:,} issues",
    )
    cols = st.columns(3)
    cols[0].metric(
        "Stillbirth rate",
        f"{_format_number(kpis['stillbirth_rate_per_1000_deliveries'], 1)} / 1,000",
        help="Stillbirths per 1,000 deliveries",
    )
    cols[1].metric("Low birth weight", f"{_format_number(kpis['low_birth_weight_rate_pct'], 1)}%")
    cols[2].metric("Preterm birth", f"{_format_number(kpis['preterm_birth_rate_pct'], 1)}%")

    if high_count:
        st.warning(
            "Decision outputs are suppressed because high-severity data quality issues are present. "
            "Use the Quality tab to reconcile conflicting submissions before relying on facility priorities."
        )
    else:
        st.markdown("### This Week's Priority Facilities")
        priority = priority_intervention_table(metrics)
        st.dataframe(
            priority,
            use_container_width=True,
            hide_index=True,
            column_config={
                "priority_score": st.column_config.NumberColumn("Priority", format="%.1f"),
                "neonatal_mortality_rate_per_1000_live_births": st.column_config.NumberColumn(
                    "NMR / 1,000",
                    format="%.1f",
                ),
                "facility_vulnerability_score": st.column_config.NumberColumn("Vulnerability", format="%.1f"),
                "neonatal_readiness_score": st.column_config.NumberColumn("Readiness", format="%.1f"),
            },
        )

        insights = driver_insights(metrics)
        if insights:
            st.markdown("### Drivers to Investigate")
            for insight in insights:
                st.info(insight)

    province = geography_metric_table(
        metrics,
        "province",
        ["total_deliveries", "neonatal_mortality_rate_per_1000_live_births"],
    )
    if not province.empty:
        chart_cols = st.columns(2)
        with chart_cols[0]:
            st.markdown("### Delivery Volume by Province")
            st.bar_chart(province.set_index("geography_id")["total_deliveries"])
        with chart_cols[1]:
            st.markdown("### Neonatal Mortality by Province")
            st.bar_chart(
                province.set_index("geography_id")[
                    "neonatal_mortality_rate_per_1000_live_births"
                ]
            )


def _facilities_tab(metrics: pd.DataFrame) -> None:
    st.subheader("Facility Rankings")
    if metrics.empty:
        st.warning("Facility metrics are unavailable while analytics are blocked.")
        return

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Top Facilities by Deliveries**")
        st.dataframe(
            top_facilities_by_metric(metrics, "total_deliveries"),
            use_container_width=True,
            hide_index=True,
        )
    with col_b:
        st.markdown("**Highest Neonatal Mortality Rate**")
        st.dataframe(
            top_facilities_by_metric(
                metrics,
                "neonatal_mortality_rate_per_1000_live_births",
            ),
            use_container_width=True,
            hide_index=True,
        )

    score_table = facility_metric_table(
        metrics,
        [
            "facility_performance_score",
            "neonatal_readiness_score",
            "facility_vulnerability_score",
            "anomaly_flag_count",
        ],
    )
    if not score_table.empty:
        score_table["vulnerability_band"] = score_table["facility_vulnerability_score"].apply(score_band)
        st.markdown("**Score Bands and Signals**")
        st.dataframe(score_table, use_container_width=True, hide_index=True)

    col_c, col_d = st.columns(2)
    with col_c:
        st.markdown("**Highest Neonatal Readiness**")
        st.dataframe(
            top_facilities_by_metric(metrics, "neonatal_readiness_score"),
            use_container_width=True,
            hide_index=True,
        )
    with col_d:
        st.markdown("**Highest Vulnerability**")
        st.dataframe(
            top_facilities_by_metric(metrics, "facility_vulnerability_score"),
            use_container_width=True,
            hide_index=True,
        )

    col_e, col_f = st.columns(2)
    with col_e:
        st.markdown("**Expected Delivery Volume Next Month**")
        st.dataframe(
            top_facilities_by_metric(metrics, "nowcast_expected_delivery_volume_next_month"),
            use_container_width=True,
            hide_index=True,
        )
    with col_f:
        st.markdown("**Highest Estimated Facility Stress**")
        st.dataframe(
            top_facilities_by_metric(metrics, "nowcast_facility_stress_probability_next_month"),
            use_container_width=True,
            hide_index=True,
        )


def _quality_tab(issues: pd.DataFrame, resolution: pd.DataFrame) -> None:
    st.subheader("Data Quality")
    if issues.empty:
        st.success("No data quality issues detected.")
        return

    severity_counts = issues["severity"].value_counts().rename_axis("severity").reset_index(name="count")
    cols = st.columns(2)
    with cols[0]:
        st.bar_chart(severity_counts.set_index("severity")["count"])
    with cols[1]:
        issue_counts = issues["issue_type"].value_counts().head(8).rename_axis("issue_type").reset_index(name="count")
        st.bar_chart(issue_counts.set_index("issue_type")["count"])

    issue_type = st.selectbox("Issue type", ["All", *sorted(issues["issue_type"].unique())])
    filtered = issues if issue_type == "All" else issues[issues["issue_type"] == issue_type]
    display_columns = [
        "severity",
        "issue_type",
        "dataset_kind",
        "facility_id",
        "reporting_month",
        "affected_column",
        "observed_value",
        "suggested_action",
        "source_row_number",
    ]
    st.dataframe(filtered[display_columns], use_container_width=True, hide_index=True)
    if not resolution.empty:
        st.markdown("### Clinical Submission Resolution")
        st.dataframe(resolution, use_container_width=True, hide_index=True)


def _trends_tab(metrics: pd.DataFrame) -> None:
    st.subheader("Trends")
    if metrics.empty:
        st.warning("Trend metrics are unavailable while analytics are blocked.")
        return

    trend_names = [
        "total_deliveries_pct_change",
        "live_births_pct_change",
        "neonatal_deaths_total_pct_change",
        "stillbirths_pct_change",
    ]
    district = geography_metric_table(metrics, "district", trend_names)
    if district.empty:
        st.info("No trend metrics available.")
        return
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**District Trend Table**")
        st.dataframe(district, use_container_width=True, hide_index=True)
    with col_b:
        st.markdown("**Largest Neonatal Death Increases**")
        if "neonatal_deaths_total_pct_change" in district:
            st.bar_chart(
                district.sort_values("neonatal_deaths_total_pct_change", ascending=False)
                .head(10)
                .set_index("geography_id")["neonatal_deaths_total_pct_change"]
            )


def _map_tab(data_dir: Path, metrics: pd.DataFrame) -> None:
    st.subheader("Facility Map")
    manifest = build_upload_batch_manifest(data_dir)
    facilities = manifest.datasets[DatasetKind.FACILITIES].frame.copy()
    map_frame = _facility_map_frame(facilities, metrics)
    if map_frame.empty:
        st.warning("No facility coordinates are available for mapping.")
        return

    province_options = ["All", *sorted(map_frame["province"].dropna().unique())]
    risk_options = ["All", *sorted(map_frame["risk_band"].dropna().unique())]
    filters = st.columns(3)
    province = filters[0].selectbox("Province", province_options)
    risk_band = filters[1].selectbox("Risk band", risk_options)
    min_deliveries = filters[2].slider(
        "Minimum deliveries",
        min_value=0,
        max_value=int(map_frame["total_deliveries"].fillna(0).max()),
        value=0,
        step=25,
    )

    filtered = map_frame[map_frame["total_deliveries"].fillna(0) >= min_deliveries].copy()
    if province != "All":
        filtered = filtered[filtered["province"] == province]
    if risk_band != "All":
        filtered = filtered[filtered["risk_band"] == risk_band]

    if filtered.empty:
        st.info("No facilities match the selected map filters.")
        return

    _coordinate_quality_notice(filtered, province)

    fig = px.scatter_mapbox(
        filtered,
        lat="lat",
        lon="lon",
        color="risk_band",
        size="marker_size",
        hover_name="facility_label",
        hover_data={
            "facility_id": True,
            "district": True,
            "province": True,
            "tier_level": True,
            "total_deliveries": ":,.0f",
            "neonatal_mortality_rate_per_1000_live_births": ":.1f",
            "neonatal_readiness_score": ":.1f",
            "facility_vulnerability_score": ":.1f",
            "priority_score": ":.1f",
            "lat": False,
            "lon": False,
            "marker_size": False,
        },
        color_discrete_map={
            "Critical": "#b91c1c",
            "High": "#dc6b19",
            "Moderate": "#d6a21c",
            "Low": "#16865a",
            "Unknown": "#64748b",
        },
        zoom=7.2,
        height=620,
    )
    fig.update_layout(
        mapbox_style="carto-darkmatter",
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        legend_title_text="Vulnerability band",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Hover over a facility to see name, district, delivery volume, NMR, readiness, vulnerability, and priority score. "
        "Point size reflects delivery volume. Coordinates are plotted from the facility source file as provided."
    )

    st.markdown("### Facilities on Map")
    st.dataframe(
        filtered[
            [
                "facility_label",
                "district",
                "province",
                "tier_level",
                "total_deliveries",
                "neonatal_mortality_rate_per_1000_live_births",
                "neonatal_readiness_score",
                "facility_vulnerability_score",
                "priority_score",
                "risk_band",
            ]
        ].sort_values(["priority_score", "total_deliveries"], ascending=[False, False]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "facility_label": "Facility",
            "total_deliveries": st.column_config.NumberColumn("Deliveries", format="%.0f"),
            "neonatal_mortality_rate_per_1000_live_births": st.column_config.NumberColumn(
                "NMR / 1,000",
                format="%.1f",
            ),
            "neonatal_readiness_score": st.column_config.NumberColumn("Readiness", format="%.1f"),
            "facility_vulnerability_score": st.column_config.NumberColumn(
                "Vulnerability",
                format="%.1f",
            ),
            "priority_score": st.column_config.NumberColumn("Priority", format="%.1f"),
        },
    )


def _facility_map_frame(facilities: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    metric_names = [
        "total_deliveries",
        "neonatal_mortality_rate_per_1000_live_births",
        "neonatal_readiness_score",
        "facility_vulnerability_score",
    ]
    table = facility_metric_table(metrics, metric_names)
    frame = facilities.merge(table, on="facility_id", how="left")
    frame = frame.rename(columns={"gps_lat": "lat", "gps_lon": "lon"})
    frame = frame.dropna(subset=["lat", "lon"]).copy()
    if frame.empty:
        return frame

    frame["priority_score"] = _map_priority_score(frame)
    frame["facility_label"] = frame.apply(_facility_label, axis=1)
    frame["risk_band"] = frame["facility_vulnerability_score"].apply(score_band)
    volume = frame["total_deliveries"].fillna(0)
    max_volume = max(float(volume.max() or 1), 1.0)
    frame["marker_size"] = 8 + (volume / max_volume * 24)
    return frame


def _facility_label(row: pd.Series) -> str:
    name = row.get("facility_name")
    facility_id = row.get("facility_id")
    if pd.notna(name) and str(name).strip():
        return f"{name} ({facility_id})"
    return str(facility_id)


def _coordinate_quality_notice(frame: pd.DataFrame, selected_province: str) -> None:
    notes: list[str] = []
    scope = selected_province if selected_province != "All" else "the selected facilities"
    lat_span = float(frame["lat"].max() - frame["lat"].min())
    lon_span = float(frame["lon"].max() - frame["lon"].min())

    if selected_province == "Kigali City" and (lat_span > 0.45 or lon_span > 0.45):
        notes.append(
            "Kigali City facilities span a much larger area than expected for Kigali, which suggests "
            "the sample GPS coordinates are synthetic, approximate, or mismatched."
        )

    district_spread = (
        frame.groupby("district")
        .agg(lat_span=("lat", lambda values: float(values.max() - values.min())), lon_span=("lon", lambda values: float(values.max() - values.min())), n=("facility_id", "count"))
        .reset_index()
    )
    wide_districts = district_spread[
        (district_spread["n"] > 1)
        & ((district_spread["lat_span"] > 0.45) | (district_spread["lon_span"] > 0.45))
    ]
    if not wide_districts.empty:
        examples = ", ".join(wide_districts["district"].head(4).tolist())
        notes.append(
            f"Some districts have facilities spread across implausibly large distances for {scope}; examples: {examples}."
        )

    if notes:
        st.warning(
            "Map coordinate quality warning: "
            + " ".join(notes)
            + " Treat this map as illustrative until facility coordinates are validated against an authoritative facility registry."
        )


def _map_priority_score(frame: pd.DataFrame) -> pd.Series:
    max_deliveries = max(float(frame["total_deliveries"].fillna(0).max() or 1), 1.0)
    max_mortality = max(
        float(frame["neonatal_mortality_rate_per_1000_live_births"].fillna(0).max() or 1),
        1.0,
    )
    return (
        frame["neonatal_mortality_rate_per_1000_live_births"].fillna(0) / max_mortality * 40.0
        + frame["total_deliveries"].fillna(0) / max_deliveries * 30.0
        + frame["facility_vulnerability_score"].fillna(0) / 100.0 * 30.0
    )


def _report_tab(
    dataset,
    data_dir: Path,
    tenant_id: str,
    country_code: str,
    output_dir: Path,
    allow_high_severity: bool,
) -> None:
    st.subheader("Report Generation")
    if dataset.analytics_blocked:
        st.warning("PDF and Excel generation remain disabled until report-ready metrics are available.")
        return

    metric_count = len(dataset.metrics)
    kpis = national_kpis(dataset.metrics_frame)
    priority = priority_intervention_table(dataset.metrics_frame, limit=5)
    issue_counts = _issue_counts(dataset.issues_frame)

    st.info(f"{metric_count:,} report-ready metric records are available for downstream outputs.")
    _report_status_cards(dataset, kpis, issue_counts)

    st.markdown("### Bulletin Package")
    package_cols = st.columns(3)
    package_cols[0].markdown(
        """
        <div class="report-card">
          <div class="report-card-title">PDF bulletin</div>
          <div class="report-card-body">Official-style ministry report with cover, table of contents, charts, interpretation callouts, recommendations, methodology, and data-quality gating.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    package_cols[1].markdown(
        """
        <div class="report-card">
          <div class="report-card-title">HTML bulletin</div>
          <div class="report-card-body">Browser-readable version of the same bulletin, useful for review, sharing, and checking chart rendering before PDF export.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    package_cols[2].markdown(
        """
        <div class="report-card">
          <div class="report-card-title">Excel workbook</div>
          <div class="report-card-body">Metric trace, summary KPIs, rankings, trends, nowcasts, clinical resolution audit, and detailed data-quality issue tables.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### Report Contents")
    st.write(
        "The generated bulletin includes executive summary, national overview, monthly trend analysis, "
        "cause-of-death analysis, quarter-over-quarter comparison, provincial analysis, top delivery "
        "facilities, readiness and vulnerability analysis, priority intervention facilities, data quality, "
        "cross-facility anomalies, recommendations, methodology, and limitations."
    )

    if not priority.empty:
        st.markdown("### Priority Facilities Included in Report")
        st.dataframe(
            priority,
            use_container_width=True,
            hide_index=True,
            column_config={
                "priority_score": st.column_config.NumberColumn("Priority", format="%.1f"),
                "total_deliveries": st.column_config.NumberColumn("Deliveries", format="%.0f"),
                "neonatal_mortality_rate_per_1000_live_births": st.column_config.NumberColumn(
                    "NMR / 1,000",
                    format="%.1f",
                ),
                "facility_vulnerability_score": st.column_config.NumberColumn(
                    "Vulnerability",
                    format="%.1f",
                ),
                "neonatal_readiness_score": st.column_config.NumberColumn("Readiness", format="%.1f"),
            },
        )

    st.markdown("### Analysis Mode Impact")
    st.dataframe(
        dataset.mode_comparison_frame,
        use_container_width=True,
        hide_index=True,
        column_config={
            "total_deliveries": st.column_config.NumberColumn("Deliveries", format="%.0f"),
            "live_births": st.column_config.NumberColumn("Live births", format="%.0f"),
            "nmr_per_1000": st.column_config.NumberColumn("NMR / 1,000", format="%.1f"),
            "stillbirth_rate_per_1000": st.column_config.NumberColumn("Stillbirth / 1,000", format="%.1f"),
        },
    )
    if not dataset.mode_comparison_frame.empty:
        st.caption(
            "Headline KPIs can match across modes when duplicate-conflict months fall outside the current reporting quarter. "
            "Here, the known conflicts are in January and March 2024, while the current bulletin window is September-November 2024."
        )

    st.markdown("### Generate Files")
    st.write(
        "Generates the polished HTML bulletin, PDF bulletin, and Excel workbook from the same "
        "report-ready metrics used by the dashboard."
    )
    if st.button("Generate bulletin files", type="primary"):
        try:
            os.environ.setdefault("DYLD_FALLBACK_LIBRARY_PATH", "/opt/homebrew/lib")
            manifest = build_upload_batch_manifest(data_dir, tenant_id, country_code)
            generated = generate_reports(
                manifest,
                output_dir,
                allow_high_severity=allow_high_severity,
                use_openai=False,
                analysis_mode=dataset.analysis_mode,
            )
            st.success(f"Generated report run {generated.run_id}")
            _generated_report_summary(generated)
            _artifact_downloads(
                generated.html_path,
                generated.excel_path,
                generated.pdf_path,
                generated.pdf_status,
                key_prefix=f"generated-{generated.run_id}",
            )
            st.code(
                "\n".join(
                    [
                        f"html: {generated.html_path}",
                        f"excel: {generated.excel_path}",
                        f"pdf: {generated.pdf_path if generated.pdf_path else generated.pdf_status}",
                    ]
                )
            )
        except Exception as exc:
            st.error(f"Report generation failed: {exc}")

    latest = _latest_output_dir(output_dir)
    if latest:
        st.markdown("### Latest Generated Run")
        html = latest / "bulletin.html"
        excel = latest / "bulletin_workbook.xlsx"
        pdf = latest / "bulletin.pdf"
        _artifact_downloads(
            html,
            excel,
            pdf if pdf.exists() else None,
            key_prefix=f"latest-{latest.name}",
        )
        st.code(str(latest))


def _report_status_cards(dataset, kpis: dict[str, float | None], issue_counts: dict[str, int]) -> None:
    cols = st.columns(4)
    cols[0].metric("Analysis mode", dataset.analysis_mode.value)
    cols[1].metric("NMR / 1,000", _format_number(kpis.get("neonatal_mortality_rate_per_1000_live_births"), 1))
    cols[2].metric("Deliveries", _format_number(kpis.get("total_deliveries"), 0))
    cols[3].metric("High-severity DQ issues", f"{issue_counts.get('high', 0):,}")

    if issue_counts.get("high", 0):
        st.warning(
            "Publication status: preview only. Official publication should remain blocked until "
            "high-severity data quality issues are resolved or formally signed off."
        )
    else:
        st.success("Publication status: data quality gate is clear for this analysis mode.")


def _generated_report_summary(generated) -> None:
    st.markdown("### Generated Run Summary")
    cols = st.columns(4)
    cols[0].metric("Metrics exported", f"{generated.metrics_count:,}")
    cols[1].metric("DQ issues exported", f"{generated.issues_count:,}")
    cols[2].metric("PDF status", generated.pdf_status)
    cols[3].metric("Run ID", generated.run_id[:8])


def _artifact_downloads(
    html_path: Path,
    excel_path: Path,
    pdf_path: Path | None,
    pdf_status: str | None = None,
    key_prefix: str = "artifact",
) -> None:
    cols = st.columns(3)
    if html_path.exists():
        cols[0].download_button(
            "Download HTML",
            html_path.read_bytes(),
            file_name=html_path.name,
            mime="text/html",
            key=f"{key_prefix}-html-{html_path}",
        )
    if excel_path.exists():
        cols[1].download_button(
            "Download Excel",
            excel_path.read_bytes(),
            file_name=excel_path.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"{key_prefix}-excel-{excel_path}",
        )
    if pdf_path and pdf_path.exists():
        cols[2].download_button(
            "Download PDF",
            pdf_path.read_bytes(),
            file_name=pdf_path.name,
            mime="application/pdf",
            key=f"{key_prefix}-pdf-{pdf_path}",
        )
    else:
        cols[2].caption("PDF not available for this run.")
        if pdf_status:
            cols[2].caption(pdf_status)
        cols[2].caption(
            "On Streamlit Cloud, PDF export requires the repository's packages.txt system "
            "dependencies to be deployed, then the app must be rebooted."
        )


def _issue_counts(issues: pd.DataFrame) -> dict[str, int]:
    if issues.empty or "severity" not in issues:
        return {}
    counts = issues["severity"].value_counts()
    return {str(level): int(count) for level, count in counts.items()}


def _format_number(value: float | None, digits: int = 0) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    if digits == 0:
        return f"{float(value):,.0f}"
    return f"{float(value):,.{digits}f}"


def _latest_output_dir(output_dir: Path) -> Path | None:
    if not output_dir.exists():
        return None
    runs = [path for path in output_dir.glob("bulletin_*") if path.is_dir()]
    if not runs:
        return None
    return max(runs, key=lambda path: path.stat().st_mtime)


def _reliability_banner(high_count: int, issue_count: int, allow_high: bool) -> None:
    if high_count:
        mode = "Preview mode enabled" if allow_high else "Official outputs blocked"
        st.markdown(
            f"""
            <div class="dq-banner critical">
              <div class="dq-title">Data Reliability Status: Critical</div>
              <div>{high_count:,} high-severity issues out of {issue_count:,} total issues. {mode}.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div class="dq-banner ready">
              <div class="dq-title">Data Reliability Status: Ready</div>
              <div>No high-severity issues detected. {issue_count:,} total data quality notes.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _hero_markup() -> str:
    """Return the dashboard hero markup without Markdown code-block indentation."""

    return dedent(
        f"""
        <div class="app-hero">
          <div class="brand-block">
            {_sand_logo_svg()}
            <div>
              <div class="eyebrow">Ministry Operations View</div>
              <h1>Sand Health Bulletin</h1>
              <p>Decision dashboard backed by validated report-ready metrics.</p>
            </div>
          </div>
        </div>
        """
    ).strip()


def _sand_logo_svg() -> str:
    """Return an inline Sand Technologies-style page logo for the dashboard header."""

    return dedent(
        """
    <svg class="sand-logo" viewBox="0 0 640 300" role="img" aria-label="Sand Technologies">
      <defs>
        <linearGradient id="sand-a-gradient" x1="132" y1="210" x2="302" y2="50" gradientUnits="userSpaceOnUse">
          <stop offset="0" stop-color="#16e1cf"/>
          <stop offset="0.52" stop-color="#24bfd3"/>
          <stop offset="1" stop-color="#4330a0"/>
        </linearGradient>
        <linearGradient id="sand-a-tail-gradient" x1="205" y1="205" x2="315" y2="160" gradientUnits="userSpaceOnUse">
          <stop offset="0" stop-color="#16e1cf"/>
          <stop offset="1" stop-color="#8636aa"/>
        </linearGradient>
      </defs>
      <text x="0" y="205" class="sand-logo-word sand-logo-s">S</text>
      <path d="M142 177 L202 65 C214 42 249 42 262 65 L309 153 C323 180 303 212 273 212 L176 212 C147 212 128 184 142 177 Z" fill="url(#sand-a-gradient)"/>
      <path d="M198 184 C229 151 266 140 292 161 C314 178 312 212 276 212 L176 212 C180 202 188 193 198 184 Z" fill="url(#sand-a-tail-gradient)"/>
      <text x="326" y="205" class="sand-logo-word">ND</text>
      <text x="2" y="288" class="sand-logo-sub">TECHNOLOGIES</text>
    </svg>
    """
    ).strip()


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.4rem; }
        .app-hero {
            background: linear-gradient(135deg, #0f3f4a 0%, #17695b 58%, #d9b45b 100%);
            border-radius: 8px;
            color: white;
            margin: .45rem 0 1rem;
            overflow: hidden;
            padding: 1.2rem 1.4rem;
        }
        .brand-block {
            align-items: center;
            display: flex;
            gap: 1.25rem;
        }
        .sand-logo {
            background: rgba(255,255,255,.92);
            border-radius: 8px;
            box-shadow: 0 12px 32px rgba(0,0,0,.18);
            flex: 0 0 210px;
            height: auto;
            max-width: 210px;
            padding: .6rem .75rem;
        }
        .sand-logo-word {
            fill: #080b29;
            font-family: Arial, Helvetica, sans-serif;
            font-size: 220px;
            font-weight: 900;
            letter-spacing: 2px;
        }
        .sand-logo-s {
            letter-spacing: 0;
        }
        .sand-logo-sub {
            fill: #080b29;
            font-family: Arial, Helvetica, sans-serif;
            font-size: 58px;
            font-weight: 900;
            letter-spacing: 13px;
        }
        .app-hero h1 {
            color: white;
            font-size: 2rem;
            margin: 0.1rem 0;
        }
        .app-hero p {
            color: rgba(255,255,255,.88);
            margin: 0;
        }
        .eyebrow {
            color: rgba(255,255,255,.78);
            font-size: .76rem;
            font-weight: 700;
            letter-spacing: .08em;
            text-transform: uppercase;
        }
        .dq-banner {
            border-left: 8px solid #17695b;
            border-radius: 6px;
            margin: 0.5rem 0 1rem;
            padding: .9rem 1rem;
        }
        .dq-banner.critical {
            background: #fff2ea;
            border-left-color: #b64000;
        }
        .dq-banner.ready {
            background: #eef8f3;
        }
        .dq-title {
            color: #123c69;
            font-weight: 800;
            margin-bottom: .15rem;
        }
        .report-card {
            background: #f8fafc;
            border: 1px solid #d9e2ec;
            border-radius: 8px;
            min-height: 128px;
            padding: 1rem;
        }
        .report-card-title {
            color: #123c69;
            font-size: 1rem;
            font-weight: 800;
            margin-bottom: .4rem;
        }
        .report-card-body {
            color: #314052;
            font-size: .92rem;
            line-height: 1.45;
        }
        @media (max-width: 720px) {
            .brand-block {
                align-items: flex-start;
                flex-direction: column;
                gap: .9rem;
            }
            .sand-logo {
                max-width: 180px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
