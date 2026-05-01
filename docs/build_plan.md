# Sand Healthcare Bulletin MVP Build Plan

Planning status: awaiting approval before implementation.

Source of truth: `docs/design.md`. Conventions and gated build order: `AGENTS.md`.

## Scope Read

The MVP is an automated quarterly health bulletin system that ingests five provided CSVs, validates and normalizes them, computes report-ready metrics, and generates three consistent outputs: a Streamlit dashboard, a polished PDF bulletin, and an Excel workbook. The database is the center of the system. CSVs must never directly feed charts, PDFs, Excel outputs, or LLM prompts.

The only MVP data sources are:

- `docs/data/clinical_neonatal.csv`
- `docs/data/facilities.csv`
- `docs/data/governance.csv`
- `docs/data/healthcare_workers.csv`
- `docs/data/operations.csv`

The example bulletins in `docs/context/example_bulletins/` are reference material for the PDF generator only. The original assignment is context only; where it conflicts with `docs/design.md`, the design wins.

## Non-Negotiable Architecture

- PostgreSQL is the center of the MVP.
- Raw uploads are preserved and standardized into staging before normalized tables are populated.
- Data quality checks run before analytics.
- Dashboard, PDF, Excel, and AI summaries all read from the same `report_ready_metrics` layer.
- Every output metric must be traceable back to input fields and calculation rules.
- AI receives only computed metric packages, never raw CSV rows.
- Scores and anomaly detection use transparent, documented heuristics.
- Predictive nowcasting must beat simple baselines before being presented as useful.

## Build Order

### 1. Data Model and Ingestion

Goal: establish the database-centered foundation.

Design sections: 5, 6, 7, 9, 21, 22, 23, 25.

Deliverables:

- Project scaffold for Python 3.11+, FastAPI, SQLAlchemy, Alembic or equivalent migrations, Pydantic, pandas, pytest, Docker Compose, and PostgreSQL.
- Database schema proposal for approval before migration is applied.
- Raw upload tracking table with upload ID, dataset type, source filename, checksum or content hash, timestamp, validation status, and preserved raw file path or raw payload reference.
- Staging tables for each dataset category.
- Normalized tables for facilities, clinical neonatal monthly data, governance, workforce, operations, data quality issues, bulletin runs, and report-ready metrics placeholders.
- CSV ingestion path for the five sample files.
- Column standardization and type coercion for dates, booleans, percentages, categorical values, numeric counts, rates, and facility IDs.
- Basic FastAPI endpoints or CLI commands for loading the five MVP files into staging and normalized tables.
- Tests using the actual sample CSVs as fixtures.

Stop condition:

- The five CSVs load reproducibly into staging and normalized tables.
- Facility joins are valid across all five datasets.
- Ingestion preserves enough metadata to trace normalized rows back to source uploads.
- Tests pass.

Approval gate:

- Schema migration must be proposed and approved before it is applied.

### 2. Data Quality Copilot

Goal: protect downstream metrics from dirty or suspicious data.

Design sections: 6, 8, 15, 21, 23, 26, 27, 28, 29.

Deliverables:

- Rule-based validation engine that runs after ingestion and before analytics.
- Checks for missing facility IDs, reporting months, coordinates, geography fields, key clinical indicators, and key operational fields.
- Duplicate checks for facility-month clinical records.
- Logical consistency checks such as deaths greater than live births, stillbirths greater than deliveries, preterm births greater than live births, functional equipment greater than total equipment, and invalid percentage/range values.
- Reporting quality checks using HMIS reporting completeness and any timeliness proxy approved for the MVP.
- Outlier and suspicious trend rules where enough history exists.
- `data_quality_issues` writes with facility ID, reporting month, issue type, severity, affected column, observed value, expected rule, suggested action, source upload, and row trace.
- Validation summary endpoint or CLI output.
- Tests for low, medium, and high severity issues.

Stop condition:

- Data quality issues are stored and queryable.
- High severity issues are distinguishable from warnings.
- Report generation policy for warnings versus blockers is explicit, even if override UI is implemented later.
- Tests pass.

### 3. Analytics Engine and Report-Ready Metrics

Goal: compute one trusted metrics layer for every output.

Design sections: 10, 11, 14, 23, 24, 27, 29.

Deliverables:

- Pure analytics functions separated from DB writes and UI/report code.
- National, province, district, and facility KPI calculations.
- Current period, previous period, absolute change, percentage change, and direction for supported metrics.
- Neonatal metrics: neonatal mortality rate, early neonatal mortality rate, late neonatal mortality rate, stillbirth rate, cause-of-death distribution, preterm burden, low birth weight rate, low Apgar rate, and volume rankings.
- Reporting completeness metrics and facility performance score.
- Initial readiness, vulnerability, watchlist, and anomaly placeholders only if needed for schema continuity; full scoring ships in slice 7.
- Traceability metadata for metrics, including source tables, source fields, calculation version, and reporting period.
- `report_ready_metrics` population job.
- Tests comparing calculations against hand-checked expected values from sample fixtures.

Stop condition:

- Dashboard/PDF/Excel can all query the same metrics tables later.
- Core bulletin KPIs are reproducible from normalized data.
- Tests pass.

### 4. Dashboard

Goal: provide the operational bulletin interface.

Design sections: 10, 14, 18, 21, 28, 29.

Deliverables:

- Streamlit MVP dashboard backed by PostgreSQL/report-ready metrics.
- Upload or refresh workflow, if not already available through backend-only endpoints.
- Reporting period selector.
- National overview KPI cards.
- Facility ranking views for volume, performance, and available readiness/vulnerability metrics.
- Data quality page for missingness, duplicates, logical issues, warnings, and blockers.
- Trend charts for month-over-month and quarter-over-quarter comparisons.
- Facility map using GPS coordinates.
- Report generation page stub or connected trigger depending on generator readiness.

Stop condition:

- Dashboard reads no CSVs directly.
- Dashboard numbers match `report_ready_metrics`.
- Key workflows work locally from a clean database.
- Tests or smoke checks pass.

### 5. PDF Bulletin and Excel Workbook

Goal: automate the official bulletin outputs from the same metrics layer.

Design sections: 10, 14, 19, 20, 23, 26, 27, 28, 29.

Deliverables:

- Jinja2 HTML bulletin template and WeasyPrint PDF generation.
- Chart generation from report-ready metrics, saved as assets and embedded in PDF.
- PDF structure: cover, contents, executive summary placeholder, data source/reporting completeness, national overview, facility reporting/performance, maternal-neonatal indicators, neonatal outcomes, readiness/vulnerability section placeholders, trend analysis, top 10 by volume, top 10 follow-up placeholder, data quality notes, recommendations placeholder, appendix tables.
- Excel workbook generated with pandas/openpyxl.
- Workbook sheets for summary KPIs, facility rankings, district trends, clinical indicators, data quality issues, and later readiness/vulnerability/watchlist data.
- `bulletin_runs` records with period, inputs, metrics version, generated paths, status, and timestamp.
- Visual structure informed by the ministry bulletin examples, without copying their numbers or narrative.
- Tests or golden-file smoke checks for generated PDF/Excel artifacts.

Stop condition:

- PDF and Excel outputs generate from the same report-ready metrics as the dashboard.
- Bulletin run metadata is stored.
- Generated outputs are reproducible.
- Tests or smoke checks pass.

### 6. AI Narrative Summaries

Goal: produce official-sounding narrative text grounded only in computed metrics.

Design sections: 10, 14, 16, 23, 26, 27, 28, 29.

Deliverables:

- Pydantic metric package models for LLM input.
- Prompt templates that forbid invented numbers and require use of supplied metrics only.
- Configurable OpenAI model and API key through environment variables.
- Executive summary, key findings, watchlist explanation placeholder, and recommendations generation.
- Internal metric references retained with generated text.
- Regeneration path from the same metrics package.
- Fallback behavior when no API key is present.
- Tests for package construction, prompt constraints, and no-raw-data guarantees.

Stop condition:

- LLM never receives raw CSV rows.
- Generated text can be tied to a metrics package and bulletin run.
- PDF can include generated sections when enabled.
- Tests pass.

### 7. Scoring, Watchlists, and Anomaly Detection

Goal: add operational intelligence after the core bulletin workflow is stable.

Design sections: 11, 12, 13, 14, 15, 18, 19, 20, 21, 23, 24, 27, 28, 29.

Deliverables:

- Documented, adjustable weights for facility performance, neonatal readiness, and vulnerability.
- Readiness sub-scores for equipment, workforce, operations, and governance.
- Vulnerability score combining outcome burden, capacity gaps, workforce pressure, operational weakness, and governance weakness.
- Top 10 facilities requiring follow-up with structured explanations.
- Statistical anomaly detection using simple thresholds, z-score/IQR, rolling deviation, or percentage-change rules where appropriate.
- Heuristic distinction between likely data quality anomalies and likely health/operations anomalies.
- Dashboard, PDF, Excel, and AI metric package integration.
- Tests for score ranges, ranking stability, weight behavior, and anomaly flags.

Stop condition:

- Watchlist explanations are traceable to input fields and computed metrics.
- Scoring is documented and adjustable.
- Outputs remain consistent across dashboard, PDF, Excel, and AI package.
- Tests pass.

### 8. Nowcasting Prototype

Goal: optional Phase 2 prototype, clearly labeled as estimates.

Design sections: 17, 23, 24, 27, 29, 30.

Deliverables:

- Baseline models for expected delivery volume, live births, high-risk burden, or facility stress.
- Simple modeling candidates such as last month, previous quarter, rolling average, seasonal baseline, linear regression, or random forest only if the data supports it.
- Baseline comparison before shipping any model result.
- Clear labels: estimated current value, not official reported data.
- Metrics storage and output integration only for models that beat baselines.
- Tests for baseline evaluation and labeling.

Stop condition:

- No mortality nowcast is presented as an official value.
- Models that do not beat baseline are not shipped as improvements.
- Tests pass.

## Cross-Cutting Work

- Maintain metric traceability from output number to calculation rule and source fields.
- Keep analytics functions pure, with DB/file I/O at module edges.
- Use Pydantic for API I/O and LLM metric packages.
- Keep scoring weights documented and configurable.
- Use realistic fixtures built from the five sample CSVs.
- Run tests before marking each slice complete.
- After each slice, summarize built work, skipped work, and prerequisites for the next slice.

## Ambiguities and Questions Before Building

### Data Model and Period Semantics

- Which reporting period should the first generated bulletin use by default: latest month, latest quarter, or a user-selected quarter?
- `clinical_neonatal.csv` is monthly, but governance, workforce, operations, and facilities appear facility-level/static. Should static tables be treated as current attributes for all months, or versioned as applying to the entire sample period?
- Should governance, workforce, and operations normalized tables include nullable `effective_start_month` / `effective_end_month`, a single `reporting_month`, or remain static until future data requires time variation?
- Should facility IDs be globally unique enough for all future data, or should future schemas include country/tenant/source-system dimensions?
- Should all five files be required for a valid bulletin run, or can a partial run proceed with missing domains flagged?

### Validation and Overrides

- What exact severity policy should block report generation? For example, should duplicate facility-month clinical rows always block, while missing GPS only warns?
- Who records an override, and what metadata is required: user name, timestamp, reason, issue IDs?
- Should the data quality layer write only issues, or should it also produce corrected/standardized values where parsing is unambiguous?
- What thresholds should define suspicious month-to-month changes for deliveries, deaths, stockouts, referral time, and reporting completeness?
- How should percentage strings like `89%` be stored: decimal fraction `0.89`, percentage points `89.0`, or both raw and normalized values?

### Metric Definitions

- What denominators should be used for neonatal mortality rates and stillbirth rates in the official bulletin: per 1,000 live births, per 1,000 total births, or another ministry convention?
- Should early and late neonatal mortality rates be reported separately and combined, and how should facilities with zero live births be handled?
- Should cause-specific neonatal deaths be validated against total neonatal deaths, and what tolerance is acceptable?
- How should top facilities by patient volume be defined for this neonatal-focused data: total deliveries, live births, referrals in/out, or a composite?
- What is the official definition of reporting timeliness? The sample files include completeness but no obvious timeliness field.

### Scores and Weights

- What default weights should be used for facility performance, neonatal readiness, and vulnerability?
- Should weights be global configuration, stored in the database with versioning, or hard-coded for the MVP with documented constants?
- Should lower-tier facilities be scored against the same readiness expectations as referral hospitals, or should readiness be tier-adjusted?
- Should high-volume facilities be penalized less for referral burden than low-tier facilities, or should workload pressure always increase vulnerability?
- What score bands should the UI and PDF use: high/medium/low, red/amber/green, quintiles, or numeric-only?

### Outputs and Audience

- Should the PDF be an internal operational bulletin, a public-facing bulletin, or support both modes later?
- Should facility-specific data quality issues appear in the PDF, or only in the dashboard/Excel to avoid public embarrassment?
- What ministry or Sand branding should be used in the PDF and dashboard?
- Should generated reports be monthly, quarterly, or both?
- Which example bulletin should dominate the first PDF visual style: Nigeria indicator-heavy, Cameroon formal quarterly narrative, or Uganda surveillance/KPI style?

### AI Narrative Layer

- Which OpenAI model should be the default, and should the MVP run without AI when no API key is configured?
- Should AI-generated recommendations be conservative templates grounded in rules, or can the LLM phrase recommendations freely as long as it uses computed inputs?
- Should generated narrative require human approval before being included in the final PDF?
- What level of metric citation/reference should be visible in the final bulletin versus retained internally?

### Deployment and Local Workflow

- Should the first implementation prioritize CLI-driven reproducibility, FastAPI endpoints, or dashboard-driven upload first?
- Is Docker Compose required in slice 1, or can it land after local schema and ingestion are working?
- Should report files be stored under a local `outputs/` directory, database-referenced local storage, or configurable storage root?
- What authentication, if any, is required for the MVP dashboard and API?

## Notes From Repository Inspection

- `docs/design.md` is 366 lines and was read in full.
- `AGENTS.md` was read and matches the gated build order above.
- The five CSVs are present under `docs/data/`.
- `clinical_neonatal.csv` has 1,404 data rows plus a header.
- `facilities.csv`, `governance.csv`, `healthcare_workers.csv`, and `operations.csv` each have 117 data rows plus a header.
- The original assignment PDF appears to be image-heavy; local text extraction tools were unavailable or ineffective in this environment. It should remain context only, and this plan intentionally follows `docs/design.md` where project direction is concerned.
