# Slice 3 Analytics Engine and Report-Ready Metrics

Status: implemented.

The analytics engine computes traceable `report_ready_metrics` records from standardized input data. It is intentionally separate from dashboard, PDF, Excel, and AI narrative code.

## Data Quality Gate

Analytics generation calls or accepts a `DataQualitySummary`.

- If high-severity issues exist, analytics are blocked by default.
- `--allow-high-severity` is available only as an explicit override path.
- This preserves the design rule that downstream outputs should not silently use dirty data.

For the provided sample files, analytics are blocked by default because `clinical_neonatal.csv` has duplicate facility-month rows for January and March 2024.

## Current Reporting Window

The engine selects the latest available three reporting months as the current window.

For the provided sample data:

- Current period: September 2024 through November 2024.
- Previous comparison period: June 2024 through August 2024.

## Metrics Implemented

Clinical aggregate metrics:

- Total deliveries
- Live births
- Early neonatal deaths
- Late neonatal deaths
- Stillbirths
- Cause-specific neonatal deaths
- Preterm births
- Low Apgar count
- Low birth weight count

Rate metrics:

- Neonatal mortality rate per 1,000 live births
- Early neonatal mortality rate per 1,000 live births
- Late neonatal mortality rate per 1,000 live births
- Stillbirth rate per 1,000 deliveries
- Preterm birth rate
- Low birth weight rate
- Low Apgar rate
- Cause-of-death shares

Trend metrics:

- Absolute and percent change versus previous period for deliveries, live births, stillbirths, and total neonatal deaths.
- Trend metrics are calculated at national, province, and district levels.

Facility metrics:

- Facility-level clinical aggregates and rates.
- Top 10 facility volume ranks.
- Initial facility performance score using reporting completeness, death audit completion, staff protocol training, protocol compliance, infection prevention, referral feedback, and quality improvement activity.

## Traceability

Each metric includes:

- Tenant and country scope.
- Reporting period.
- Geography level and ID.
- Optional facility ID.
- Metric name, value, unit, numerator, and denominator.
- Source table.
- Source fields.
- Calculation rule.
- Trace payload.

These records are the common metrics layer for future dashboard, PDF, Excel, and LLM narrative slices.

## CLI

Default blocked behavior:

```bash
python -m sand_bulletin.cli build-metrics --data-dir docs/data --tenant-id sand --country-code RWA
```

Explicit override preview:

```bash
python -m sand_bulletin.cli build-metrics --data-dir docs/data --tenant-id sand --country-code RWA --allow-high-severity
```

Persisting metrics to PostgreSQL:

```bash
python -m sand_bulletin.cli build-metrics --data-dir docs/data --tenant-id sand --country-code RWA --allow-high-severity --persist
```

Only use `--allow-high-severity` after a data quality review or documented override.
