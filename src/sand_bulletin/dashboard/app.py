"""Streamlit operational bulletin dashboard."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
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

    st.markdown(
        """
        <div class="app-hero">
          <div>
            <div class="eyebrow">Ministry Operations View</div>
            <h1>Sand Health Bulletin</h1>
            <p>Decision dashboard backed by validated report-ready metrics.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

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
        _map_tab(data_dir)

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


def _map_tab(data_dir: Path) -> None:
    st.subheader("Facility Map")
    manifest = build_upload_batch_manifest(data_dir)
    facilities = manifest.datasets[DatasetKind.FACILITIES].frame.copy()
    map_frame = facilities.rename(columns={"gps_lat": "lat", "gps_lon": "lon"})
    st.map(map_frame[["lat", "lon"]])
    st.dataframe(
        facilities[["facility_id", "facility_name", "district", "province", "tier_level"]],
        use_container_width=True,
        hide_index=True,
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
            _artifact_downloads(generated.html_path, generated.excel_path, generated.pdf_path, generated.pdf_status)
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
        _artifact_downloads(html, excel, pdf if pdf.exists() else None)
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
) -> None:
    cols = st.columns(3)
    if html_path.exists():
        cols[0].download_button(
            "Download HTML",
            html_path.read_bytes(),
            file_name=html_path.name,
            mime="text/html",
        )
    if excel_path.exists():
        cols[1].download_button(
            "Download Excel",
            excel_path.read_bytes(),
            file_name=excel_path.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if pdf_path and pdf_path.exists():
        cols[2].download_button(
            "Download PDF",
            pdf_path.read_bytes(),
            file_name=pdf_path.name,
            mime="application/pdf",
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


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.4rem; }
        .app-hero {
            background: linear-gradient(135deg, #0f3f4a 0%, #17695b 58%, #d9b45b 100%);
            border-radius: 8px;
            color: white;
            margin-bottom: 1rem;
            padding: 1.2rem 1.4rem;
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
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
