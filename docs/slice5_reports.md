# Slice 5 PDF and Excel Generators

Status: implemented.

The report generators use the same report-ready metric records as the dashboard and analytics CLI. They do not read raw CSVs directly for output numbers.

## Outputs

The generator creates a bulletin run directory containing:

- `bulletin.html`
- `bulletin_workbook.xlsx`
- `bulletin.pdf` when WeasyPrint is installed

## CLI

Default behavior blocks on high-severity data quality issues:

```bash
python -m sand_bulletin.cli generate-reports --data-dir docs/data --tenant-id sand --country-code RWA --output-dir outputs
```

Explicit override preview:

```bash
python -m sand_bulletin.cli generate-reports --data-dir docs/data --tenant-id sand --country-code RWA --output-dir outputs --allow-high-severity
```

With the current sample data, override generation produced:

- 4,393 report-ready metric records
- 550 data quality issue records
- HTML bulletin
- Excel workbook
- PDF skipped because WeasyPrint is not installed in the current environment

## Excel Workbook

Workbook sheets:

- `summary_kpis`
- `facility_rankings`
- `district_trends`
- `clinical_indicators`
- `readiness_scores`
- `vulnerability_watchlist`
- `data_quality_issues`
- `metric_trace`
- `facilities`

`readiness_scores` and `vulnerability_watchlist` include explicit placeholders because full readiness/vulnerability scoring lands in slice 7.

## HTML/PDF Bulletin

The HTML bulletin follows an official-publication structure:

- Cover page
- Executive summary
- Data source and reporting completeness
- National overview
- Facility reporting and performance
- Maternal/neonatal health indicators
- Trend analysis
- Data quality notes
- Recommendations

The PDF generator uses WeasyPrint when available. Install report extras with:

```bash
python -m pip install -e ".[reports]"
```

Then rerun `generate-reports` to produce `bulletin.pdf`.

## Quality Gate

Reports are blocked by default if high-severity data quality issues exist. This is intentional because the current sample file has duplicate clinical facility-month rows for January and March 2024.
