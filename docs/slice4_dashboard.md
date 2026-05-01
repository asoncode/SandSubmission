# Slice 4 Dashboard

Status: implemented.

The dashboard is a Streamlit operational bulletin interface backed by the existing ingestion, data quality, and report-ready metrics layers.

## Entry Point

```bash
streamlit run src/sand_bulletin/dashboard/app.py --server.port 8501
```

## Pages

- Overview: national KPI cards and province delivery chart.
- Facilities: top facilities by deliveries, neonatal mortality rate, and facility performance score.
- Quality: severity counts and issue table with filtering by issue type.
- Trends: district-level percent-change metrics.
- Map: facility GPS map and facility list.
- Report: downstream report generation placeholder, disabled when analytics are blocked.

## Data Flow

- The dashboard loads the five MVP CSVs through the ingestion layer.
- It runs the data quality copilot.
- It builds metrics only through `build_report_ready_metrics`.
- It does not feed charts directly from raw CSVs.

## Quality Gate

The dashboard shows a blocked state by default because the provided sample data contains high-severity data quality issues.

Users can check `Use explicit DQ override` to preview the report-ready metrics after review. This mirrors the CLI behavior and keeps the quality gate visible.

## Current Sample Behavior

With the unmodified sample data:

- Data quality issues: 550
- High severity: 486
- Metrics blocked by default
- Explicit override preview: 4,393 report-ready metric records

This is expected until the duplicate January and March clinical facility-month rows are corrected or explicitly overridden.
