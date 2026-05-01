# Slice 7 Scoring, Watchlists, and Anomaly Detection

Status: implemented.

Slice 7 adds transparent operational intelligence metrics to the existing `report_ready_metrics` layer. Dashboard, Excel, HTML/PDF reports, and AI narrative packages can all read the same computed scores.

## Neonatal Readiness Score

Metric names:

- `neonatal_readiness_score`
- `neonatal_readiness_equipment_subscore`
- `neonatal_readiness_workforce_subscore`
- `neonatal_readiness_operations_subscore`
- `neonatal_readiness_governance_subscore`

Formula:

- Equipment: 30%
- Workforce: 25%
- Operations: 25%
- Governance: 20%

Inputs include NICU availability, beds, functional incubators, CPAP, resuscitation tables, warmers, phototherapy, trained nurses, pediatricians, neonatologists, staff-per-delivery, night coverage, oxygen, ambulance, kangaroo care, stockouts, surfactant, antibiotics, infection prevention, protocol compliance, training, audits, and protocol existence.

All sub-scores and total scores are normalized to 0-100.

## Facility Vulnerability Score

Metric names:

- `facility_vulnerability_score`
- `vulnerability_watchlist_rank`

Formula:

- Outcome burden: 25%
- Recent mortality change: 15%
- Workload: 15%
- Readiness gap: 20%
- Workforce pressure: 10%
- Operational weakness: 10%
- Governance weakness: 5%

Each score includes a `trace_payload` with component values and a plain-language explanation. The top 10 ranked facilities become the follow-up watchlist.

## Anomaly Detection

Metric name:

- `anomaly_flag_count`

Current simple rules:

- Deliveries dropped by at least 50% compared with the previous period.
- Neonatal deaths doubled or exceeded 10 compared with the previous period.
- Zero neonatal deaths with high delivery volume.

These are report-ready anomaly metrics. The data quality copilot still owns row-level issue records.

## Output Integration

Dashboard:

- Facility page now shows readiness and vulnerability rankings.

Excel:

- `readiness_scores` now contains real readiness scores and sub-scores.
- `vulnerability_watchlist` now contains vulnerability score, watchlist rank, and anomaly count.

HTML/PDF:

- Adds a Facility Readiness and Vulnerability section.
- Adds the top 10 follow-up watchlist with explanations.

Narrative:

- The metric package now includes highest-vulnerability facilities.
- Fallback and AI narratives can describe the vulnerability watchlist from computed scores.

## Current Sample Behavior

With explicit DQ override, the current sample data produces:

- 5,222 report-ready metric records
- 117 neonatal readiness scores
- 117 vulnerability scores
- 10 watchlist ranks
- 117 anomaly flag counts

The default quality gate remains unchanged: high-severity duplicate facility-month records still block analytics and reports unless explicitly overridden.
