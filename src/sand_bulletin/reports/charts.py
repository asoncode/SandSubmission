"""Chart generation for bulletin-style PDF reports."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import base64
import os
from pathlib import Path

import pandas as pd

from sand_bulletin.data_quality import AnalysisMode, resolve_clinical_submissions
from sand_bulletin.dashboard.data import facility_metric_table, geography_metric_table
from sand_bulletin.ingestion.batches import UploadBatchManifest
from sand_bulletin.ingestion.datasets import DatasetKind


@dataclass(frozen=True)
class ChartAsset:
    """A rendered chart with a short data-grounded takeaway."""

    title: str
    image_uri: str
    takeaway: str
    caption: str


def build_chart_assets(
    metrics: pd.DataFrame,
    issues: pd.DataFrame,
    manifest: UploadBatchManifest,
    analysis_mode: AnalysisMode | str,
) -> dict[str, ChartAsset]:
    """Build all bulletin chart assets as base64 PNG images."""

    try:
        cache_dir = Path("/tmp/sand_bulletin_matplotlib")
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))
        os.environ.setdefault("XDG_CACHE_HOME", "/tmp")
        import matplotlib

        matplotlib.use("Agg")
        from matplotlib import pyplot as plt
    except Exception:
        return {}

    mode = AnalysisMode(analysis_mode)
    clinical = resolve_clinical_submissions(
        manifest.datasets[DatasetKind.CLINICAL_NEONATAL].frame,
        mode,
    ).frame
    charts: dict[str, ChartAsset] = {}

    current = _current_period_clinical(metrics, clinical)
    labels = _facility_labels(manifest)

    for key, chart in {
        "monthly_volume": _monthly_volume_chart(plt, clinical),
        "monthly_nmr": _monthly_nmr_chart(plt, clinical),
        "cause_of_death": _cause_of_death_chart(plt, current),
        "quarter_comparison": _quarter_comparison_chart(plt, metrics),
        "province_nmr": _province_nmr_chart(plt, metrics),
        "top_delivery_volume": _top_delivery_chart(plt, metrics, labels),
        "readiness_distribution": _readiness_distribution_chart(plt, metrics),
        "vulnerability_watchlist": _vulnerability_watchlist_chart(plt, metrics, labels),
        "data_quality": _quality_chart(plt, issues),
        "readiness_outcomes": _readiness_chart(plt, metrics),
    }.items():
        if chart:
            charts[key] = chart

    return charts


def _monthly_volume_chart(plt, clinical: pd.DataFrame) -> ChartAsset | None:
    if clinical.empty:
        return None
    monthly = clinical.groupby("reporting_month", as_index=False).agg(
        total_deliveries=("total_deliveries", "sum"),
        live_births=("live_births", "sum"),
    )
    if monthly.empty:
        return None
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    ax.plot(monthly["reporting_month"], monthly["total_deliveries"], color="#17695b", marker="o", linewidth=2.4, label="Deliveries")
    ax.plot(monthly["reporting_month"], monthly["live_births"], color="#2f68b7", marker="o", linewidth=2.0, label="Live births")
    ax.set_title("Monthly reported service volume", loc="left", fontsize=12, fontweight="bold")
    ax.set_ylabel("Count")
    ax.grid(axis="y", color="#d9e2e3", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncols=2, loc="upper left")
    fig.autofmt_xdate(rotation=30, ha="right")
    peak = monthly.loc[monthly["total_deliveries"].idxmax()]
    takeaway = (
        f"Reported deliveries peaked in {peak['reporting_month']} with "
        f"{float(peak['total_deliveries']):,.0f} deliveries after applying the selected analysis mode."
    )
    return ChartAsset(
        "Monthly reported service volume",
        _figure_uri(fig),
        takeaway,
        "Figure 1. Monthly deliveries and live births after applying the selected analysis mode.",
    )


def _monthly_nmr_chart(plt, clinical: pd.DataFrame) -> ChartAsset | None:
    if clinical.empty:
        return None
    monthly = clinical.groupby("reporting_month", as_index=False).agg(
        live_births=("live_births", "sum"),
        neonatal_deaths_0_7d=("neonatal_deaths_0_7d", "sum"),
        neonatal_deaths_8_28d=("neonatal_deaths_8_28d", "sum"),
    )
    monthly["nmr"] = (
        (monthly["neonatal_deaths_0_7d"] + monthly["neonatal_deaths_8_28d"])
        / monthly["live_births"].replace(0, pd.NA)
        * 1000.0
    )
    monthly = monthly.dropna(subset=["nmr"])
    if monthly.empty:
        return None
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    ax.plot(monthly["reporting_month"], monthly["nmr"], color="#b64000", marker="o", linewidth=2.4)
    ax.set_title("Monthly neonatal mortality rate", loc="left", fontsize=12, fontweight="bold")
    ax.set_ylabel("Deaths per 1,000 live births")
    ax.grid(axis="y", color="#eadbd4", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.autofmt_xdate(rotation=30, ha="right")
    highest = monthly.loc[monthly["nmr"].idxmax()]
    lowest = monthly.loc[monthly["nmr"].idxmin()]
    takeaway = (
        f"NMR was highest in {highest['reporting_month']} ({float(highest['nmr']):.1f}) "
        f"and lowest in {lowest['reporting_month']} ({float(lowest['nmr']):.1f}) per 1,000 live births."
    )
    return ChartAsset(
        "Monthly neonatal mortality rate",
        _figure_uri(fig),
        takeaway,
        "Figure 2. Monthly NMR calculated as neonatal deaths divided by live births, multiplied by 1,000.",
    )


def _cause_of_death_chart(plt, clinical: pd.DataFrame) -> ChartAsset | None:
    cause_columns = {
        "Birth asphyxia": "death_birth_asphyxia",
        "Prematurity": "death_prematurity",
        "Sepsis": "death_sepsis",
        "Congenital": "death_congenital",
        "Other": "death_other",
    }
    if clinical.empty or not set(cause_columns.values()) <= set(clinical.columns):
        return None
    values = pd.Series({label: float(clinical[column].sum()) for label, column in cause_columns.items()})
    if values.sum() <= 0:
        return None
    values = values.sort_values()
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    ax.barh(values.index, values.values, color="#2f68b7")
    ax.set_title("Cause of neonatal death distribution", loc="left", fontsize=12, fontweight="bold")
    ax.set_xlabel("Deaths")
    ax.grid(axis="x", color="#d9e2e3", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for index, value in enumerate(values.values):
        ax.text(value, index, f" {value:,.0f}", va="center", fontsize=8)
    leading = values.idxmax()
    share = values.max() / values.sum() * 100.0
    takeaway = f"{leading} is the leading reported cause, accounting for {share:.1f}% of cause-coded neonatal deaths."
    return ChartAsset(
        "Cause of neonatal death distribution",
        _figure_uri(fig),
        takeaway,
        "Figure 3. Reported cause-specific neonatal deaths for the bulletin reporting period.",
    )


def _quarter_comparison_chart(plt, metrics: pd.DataFrame) -> ChartAsset | None:
    national = metrics[
        (metrics["geography_level"] == "national") & (metrics["geography_id"] == "national")
    ]
    indicators = {
        "Deliveries": "total_deliveries",
        "Live births": "live_births",
        "Stillbirths": "stillbirths",
        "Neonatal deaths": "neonatal_deaths_total",
    }
    current: dict[str, float] = {}
    previous: dict[str, float] = {}
    for label, name in indicators.items():
        if name == "neonatal_deaths_total":
            early = national[national["metric_name"] == "neonatal_deaths_0_7d"]
            late = national[national["metric_name"] == "neonatal_deaths_8_28d"]
            current_row = pd.DataFrame()
            current_value = (
                float(early.iloc[0]["metric_value"]) + float(late.iloc[0]["metric_value"])
                if not early.empty and not late.empty
                else None
            )
        else:
            current_row = national[national["metric_name"] == name]
            current_value = float(current_row.iloc[0]["metric_value"]) if not current_row.empty else None
        change_row = national[national["metric_name"] == f"{name}_absolute_change"]
        if current_value is None or change_row.empty:
            continue
        change = float(change_row.iloc[0]["metric_value"])
        current[label] = current_value
        previous[label] = current_value - change
    if len(current) < 2:
        return None
    labels = list(current.keys())
    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    width = 0.36
    ax.bar([value - width / 2 for value in x], [previous[label] for label in labels], width=width, label="Previous period", color="#9db7d5")
    ax.bar([value + width / 2 for value in x], [current[label] for label in labels], width=width, label="Current period", color="#17695b")
    ax.set_title("Previous period versus current period", loc="left", fontsize=12, fontweight="bold")
    ax.set_ylabel("Count")
    ax.set_xticks(list(x), labels, rotation=15, ha="right")
    ax.grid(axis="y", color="#d9e2e3", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)
    delivery_change = (
        (current.get("Deliveries", 0.0) - previous.get("Deliveries", 0.0))
        / max(previous.get("Deliveries", 0.0), 1.0)
        * 100.0
    )
    takeaway = f"Deliveries changed by {delivery_change:+.1f}% versus the previous comparison period."
    return ChartAsset(
        "Previous period versus current period",
        _figure_uri(fig),
        takeaway,
        "Figure 4. Current reporting period indicators compared with the previous reporting window.",
    )


def _province_nmr_chart(plt, metrics: pd.DataFrame) -> ChartAsset | None:
    province = geography_metric_table(
        metrics,
        "province",
        ["neonatal_mortality_rate_per_1000_live_births"],
    )
    if province.empty:
        return None
    province = province.sort_values("neonatal_mortality_rate_per_1000_live_births", ascending=True)
    national = metrics[
        (metrics["geography_level"] == "national")
        & (metrics["geography_id"] == "national")
        & (metrics["metric_name"] == "neonatal_mortality_rate_per_1000_live_births")
    ]
    national_value = float(national.iloc[0]["metric_value"]) if not national.empty else None
    fig, ax = plt.subplots(figsize=(7.4, 3.2))
    bars = ax.barh(province["geography_id"], province["neonatal_mortality_rate_per_1000_live_births"], color="#b64000")
    if national_value is not None:
        ax.axvline(national_value, color="#123c69", linestyle="--", linewidth=1.5, label="National average")
        ax.legend(frameon=False)
    ax.set_title("Province neonatal mortality rate comparison", loc="left", fontsize=12, fontweight="bold")
    ax.set_xlabel("Deaths per 1,000 live births")
    ax.grid(axis="x", color="#d9e2e3", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for bar in bars:
        width = bar.get_width()
        ax.text(width, bar.get_y() + bar.get_height() / 2, f" {width:.1f}", va="center", fontsize=8)
    highest = province.loc[province["neonatal_mortality_rate_per_1000_live_births"].idxmax()]
    takeaway = (
        f"{highest['geography_id']} has the highest provincial neonatal mortality rate in the reporting window "
        f"at {float(highest['neonatal_mortality_rate_per_1000_live_births']):.1f} per 1,000 live births."
    )
    return ChartAsset(
        "Province neonatal mortality rate comparison",
        _figure_uri(fig),
        takeaway,
        "Figure 5. Provincial NMR compared with the national average line.",
    )


def _top_delivery_chart(plt, metrics: pd.DataFrame, labels: dict[str, str]) -> ChartAsset | None:
    top = metrics[
        (metrics["geography_level"] == "facility")
        & (metrics["metric_name"] == "total_deliveries")
    ].copy()
    if top.empty:
        return None
    top = top.sort_values("metric_value", ascending=True).tail(10)
    names = [labels.get(str(facility), str(facility)) for facility in top["facility_id"]]
    fig, ax = plt.subplots(figsize=(7.4, 3.4))
    bars = ax.barh(names, top["metric_value"], color="#17695b")
    ax.set_title("Top 10 facilities by delivery volume", loc="left", fontsize=12, fontweight="bold")
    ax.set_xlabel("Deliveries")
    ax.grid(axis="x", color="#d9e2e3", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    for bar in bars:
        width = bar.get_width()
        ax.text(width, bar.get_y() + bar.get_height() / 2, f" {width:,.0f}", va="center", fontsize=8)
    leader = top.iloc[-1]
    takeaway = f"{labels.get(str(leader['facility_id']), str(leader['facility_id']))} reported the highest delivery volume ({float(leader['metric_value']):,.0f})."
    return ChartAsset(
        "Top 10 facilities by delivery volume",
        _figure_uri(fig),
        takeaway,
        "Figure 6. Highest-volume facilities in the reporting period.",
    )


def _readiness_distribution_chart(plt, metrics: pd.DataFrame) -> ChartAsset | None:
    table = facility_metric_table(metrics, ["neonatal_readiness_score"])
    if table.empty or "neonatal_readiness_score" not in table:
        return None
    scores = table["neonatal_readiness_score"].dropna()
    if scores.empty:
        return None
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    ax.hist(scores, bins=[0, 20, 40, 60, 80, 100], color="#2f68b7", edgecolor="white")
    ax.set_title("Facility readiness score distribution", loc="left", fontsize=12, fontweight="bold")
    ax.set_xlabel("Readiness score")
    ax.set_ylabel("Facilities")
    ax.grid(axis="y", color="#d9e2e3", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    below = int((scores < 60).sum())
    takeaway = f"{below} facilities have readiness scores below 60, indicating moderate-to-high preparedness gaps."
    return ChartAsset(
        "Facility readiness score distribution",
        _figure_uri(fig),
        takeaway,
        "Figure 7. Distribution of neonatal readiness scores across facilities.",
    )


def _vulnerability_watchlist_chart(plt, metrics: pd.DataFrame, labels: dict[str, str]) -> ChartAsset | None:
    table = facility_metric_table(metrics, ["facility_vulnerability_score"])
    if table.empty:
        return None
    table = table.dropna(subset=["facility_vulnerability_score"]).sort_values("facility_vulnerability_score", ascending=True).tail(10)
    if table.empty:
        return None
    names = [labels.get(str(facility), str(facility)) for facility in table["facility_id"]]
    fig, ax = plt.subplots(figsize=(7.4, 3.4))
    ax.barh(names, table["facility_vulnerability_score"], color="#b64000")
    ax.set_title("Facility vulnerability watchlist", loc="left", fontsize=12, fontweight="bold")
    ax.set_xlabel("Vulnerability score")
    ax.set_xlim(0, 100)
    ax.grid(axis="x", color="#eadbd4", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    leader = table.iloc[-1]
    takeaway = f"{labels.get(str(leader['facility_id']), str(leader['facility_id']))} has the highest vulnerability score ({float(leader['facility_vulnerability_score']):.1f})."
    return ChartAsset(
        "Facility vulnerability watchlist",
        _figure_uri(fig),
        takeaway,
        "Figure 8. Facilities with the highest vulnerability scores.",
    )


def _readiness_chart(plt, metrics: pd.DataFrame) -> ChartAsset | None:
    table = facility_metric_table(
        metrics,
        [
            "neonatal_readiness_score",
            "facility_vulnerability_score",
            "neonatal_mortality_rate_per_1000_live_births",
            "total_deliveries",
        ],
    )
    required = {
        "neonatal_readiness_score",
        "facility_vulnerability_score",
        "neonatal_mortality_rate_per_1000_live_births",
        "total_deliveries",
    }
    if table.empty or not required <= set(table.columns):
        return None
    table = table.dropna(subset=list(required))
    if table.empty:
        return None
    fig, ax = plt.subplots(figsize=(7.4, 3.2))
    sizes = (table["total_deliveries"] / max(float(table["total_deliveries"].max()), 1.0) * 180) + 24
    scatter = ax.scatter(
        table["neonatal_readiness_score"],
        table["neonatal_mortality_rate_per_1000_live_births"],
        s=sizes,
        c=table["facility_vulnerability_score"],
        cmap="YlOrRd",
        alpha=0.76,
        edgecolors="#ffffff",
        linewidths=0.6,
    )
    ax.set_title("Facility readiness versus neonatal mortality", loc="left", fontsize=12, fontweight="bold")
    ax.set_xlabel("Readiness score")
    ax.set_ylabel("NMR per 1,000 live births")
    ax.grid(color="#d9e2e3", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    cbar = fig.colorbar(scatter, ax=ax, pad=0.02)
    cbar.set_label("Vulnerability score")
    low = table[table["neonatal_readiness_score"] < 60]
    high = table[table["neonatal_readiness_score"] >= 60]
    if not low.empty and not high.empty:
        takeaway = (
            f"Facilities below 60 readiness average {low['neonatal_mortality_rate_per_1000_live_births'].mean():.1f} "
            f"neonatal deaths per 1,000 live births, compared with "
            f"{high['neonatal_mortality_rate_per_1000_live_births'].mean():.1f} among facilities at or above 60."
        )
    else:
        takeaway = "Facility readiness and mortality are shown together to identify high-risk service gaps."
    return ChartAsset(
        "Facility readiness versus neonatal mortality",
        _figure_uri(fig),
        takeaway,
        "Figure 9. Readiness score versus facility NMR; point size reflects delivery volume and color reflects vulnerability.",
    )


def _quality_chart(plt, issues: pd.DataFrame) -> ChartAsset | None:
    if issues.empty:
        return None
    counts = issues["issue_type"].value_counts().head(8).sort_values()
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    ax.barh(counts.index, counts.values, color="#b64000")
    ax.set_title("Data quality issues by type", loc="left", fontsize=12, fontweight="bold")
    ax.set_xlabel("Issue records")
    ax.grid(axis="x", color="#eadbd4", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    top_type = issues["issue_type"].value_counts().idxmax()
    top_count = int(issues["issue_type"].value_counts().max())
    takeaway = f"The dominant data quality issue is {top_type}, with {top_count:,} records requiring review."
    return ChartAsset(
        "Data quality issues by type",
        _figure_uri(fig),
        takeaway,
        "Figure 10. Count of data quality issue records by type.",
    )


def _current_period_clinical(metrics: pd.DataFrame, clinical: pd.DataFrame) -> pd.DataFrame:
    if metrics.empty:
        return clinical
    start = metrics.iloc[0]["reporting_period_start"]
    end = metrics.iloc[0]["reporting_period_end"]
    return clinical[(clinical["reporting_month"] >= start) & (clinical["reporting_month"] <= end)].copy()


def _facility_labels(manifest: UploadBatchManifest) -> dict[str, str]:
    facilities = manifest.datasets[DatasetKind.FACILITIES].frame
    labels: dict[str, str] = {}
    for _, row in facilities.iterrows():
        facility_id = str(row["facility_id"])
        name = str(row.get("facility_name") or facility_id)
        labels[facility_id] = f"{name} ({facility_id})" if name != facility_id else facility_id
    return labels


def _figure_uri(fig) -> str:
    fig.tight_layout()
    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=170, bbox_inches="tight")
    fig.clear()
    import matplotlib.pyplot as plt

    plt.close(fig)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
