# Slice 8 Nowcasting Prototype

Status: implemented.

Slice 8 adds a transparent nowcasting prototype that produces facility-level planning estimates from the same validated clinical history used by the rest of the bulletin. The prototype does not generate official mortality predictions and does not emit a nowcast unless a simple model beats the last-observed-value baseline during rolling-origin backtesting.

## Implemented Outputs

- `nowcast_expected_delivery_volume_next_month`
- `nowcast_expected_live_births_next_month`
- `nowcast_expected_high_risk_births_next_month`
- `nowcast_facility_stress_probability_next_month`

All nowcast records are stored as report-ready metrics with `metric_version = slice8_nowcast_v1`. They include trace payloads with the selected model, baseline MAE, model MAE, backtest period count, and an explicit label that the value is an estimate, not official reported data.

## Model Approach

- Baseline: last observed monthly value.
- Candidate 1: trailing three-month mean.
- Candidate 2: three-month trend projection.
- Selection: choose the candidate with the lowest MAE across historical rolling-origin tests.
- Shipping rule: emit the metric only when the selected candidate has lower MAE than the baseline and at least two backtest periods.

The high-risk burden nowcast uses a transparent proxy: 28-32 week preterm births plus 32-37 week preterm births plus low-birth-weight births. This can double count newborns who appear in more than one category, so it is intentionally labeled as burden rather than unique newborn count.

## Data Quality Gate

Nowcasting uses the same data quality gate as analytics. High-severity issues block nowcasts unless the caller provides an explicit override.

```bash
python -m sand_bulletin.cli build-nowcasts --data-dir docs/data --tenant-id sand --country-code RWA
python -m sand_bulletin.cli build-nowcasts --data-dir docs/data --tenant-id sand --country-code RWA --allow-high-severity
```

## Integration

- Analytics: nowcasts are appended to `build_report_ready_metrics`.
- Dashboard: facility tab displays expected delivery volume and highest estimated stress.
- PDF/HTML bulletin: includes a nowcasting prototype section.
- Excel workbook: adds a `nowcasts` sheet.

## Guardrails

- No deep learning or opaque ML.
- No raw CSV access by outputs.
- No LLM-generated numerical values.
- No mortality prediction metrics.
- No model is presented as useful unless it beats the last-value baseline.
