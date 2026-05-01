# Slice 2 Data Quality Copilot

Status: implemented.

The data quality copilot is rule-based for the MVP. It runs after CSV standardization and staging metadata creation, and before normalized analytics tables should be trusted.

## Implemented Checks

- Referential integrity: non-facility files must reference known facilities.
- Missingness: key facility, clinical, and operations fields are flagged when absent.
- Facility-month reconciliation:
  - exact repeated clinical reports for the same `facility_id` + `reporting_month` are medium severity `duplicate_facility_month` issues and can be collapsed to one final report
  - conflicting clinical reports for the same `facility_id` + `reporting_month` are high severity `conflicting_facility_month_submission` issues
- Logical consistency: deaths greater than live births, stillbirths greater than deliveries, preterm births greater than live births, cause-death totals not matching total neonatal deaths, and functional incubators greater than total incubators are flagged.
- Percentage bounds: normalized percentage values must be fractions between `0` and `1`.
- Temporal snapshot checks: governance and workforce date fields after the clinical reporting period are flagged as `future_static_snapshot_date` because the MVP treats static facility context files as latest-available snapshots.
- Reporting quality: HMIS completeness below 80% is flagged; below 60% is high severity.
- Simple outliers: sharp delivery drops, sharp neonatal death spikes, and extended zero-death reporting are flagged.

## Severity Policy

- High severity issues block normalized loading unless an explicit override is passed.
- Medium severity issues are warnings and should appear in dashboard/PDF/Excel quality sections.
- Low severity issues are informational review prompts.

## Analysis Modes

The analytics layer now separates data validation from analysis-mode selection:

- `validated`: default official-quality mode. Exact repeated reports are collapsed, and unresolved conflicting facility-month submissions are excluded from analytics.
- `best_effort`: exploratory mode. Exact repeated reports are collapsed; conflicting submissions are scored with transparent rules and selected only when confidence is high or medium. Low-confidence conflicts are excluded.
- `raw`: audit/debug mode. All rows are used exactly as submitted. High-severity issues block this mode unless an explicit override is provided.

Duplicate rows are never summed. Conflicting rows are never averaged into fake reports.

Best-effort duplicate resolution records:

- selected row
- rejected row(s)
- resolution method
- confidence level
- reason

Confidence labels:

- `High`: one row violates hard health-data constraints and another does not, or rows are exact repeated reports.
- `Medium`: both are internally valid, but one aligns materially better with facility history and peer ratios.
- `Low`: both are plausible and the statistical separation is weak.
- `Unresolved`: no safe choice; rows are excluded from validated/best-effort analytics.

## Current Sample Data Result

Running:

```bash
python -m sand_bulletin.cli validate-data --data-dir docs/data --tenant-id sand --country-code RWA
```

Currently reports:

- 596 total issues
- 486 high
- 110 medium
- 0 low

The largest issue is conflicting clinical facility-month submissions:

- January 2024 has 234 rows instead of 117.
- March 2024 has 234 rows instead of 117.
- This produces 468 conflicting facility-month issue records.
- These are not exact repeated reports; the clinical values differ and must be reconciled before operational decisions are trusted.

In `validated` mode, these 468 January/March rows are excluded from analytics rather than corrupting the rest of the reporting period.

The sample data also includes 46 medium-severity `future_static_snapshot_date` issues. These are governance/workforce dates in 2025, while the latest clinical bulletin window is September-November 2024. They do not affect clinical delivery/death counts, but they mean readiness, governance, performance, and vulnerability context should be read as latest-available snapshot context rather than strictly period-valid context.

Because high severity issues exist, normalized loading should not proceed unless explicitly overridden. The upload/staging records and data quality issues can still be stored so the bad data is captured for review.
