from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from sand_bulletin.analytics import AnalyticsBlockedError, build_report_ready_metrics
from sand_bulletin.data_quality import validate_upload_batch
from sand_bulletin.db.load import insert_report_ready_metrics
from sand_bulletin.ingestion import build_upload_batch_manifest
from sand_bulletin.ingestion.datasets import DatasetKind


DATA_DIR = Path(__file__).resolve().parents[1] / "docs" / "data"


class AnalyticsTests(unittest.TestCase):
    def test_raw_mode_blocks_high_severity_quality_issues_by_default(self) -> None:
        manifest = build_upload_batch_manifest(DATA_DIR, tenant_id="sand", country_code="RWA")
        summary = validate_upload_batch(manifest)

        with self.assertRaises(AnalyticsBlockedError):
            build_report_ready_metrics(manifest, summary, analysis_mode="raw")

    def test_validated_mode_excludes_conflicting_facility_months(self) -> None:
        manifest = build_upload_batch_manifest(DATA_DIR, tenant_id="sand", country_code="RWA")
        summary = validate_upload_batch(manifest)

        metrics = build_report_ready_metrics(manifest, summary)

        self.assertGreater(len(metrics), 0)
        self.assertTrue(
            all(metric.trace_payload.get("analysis_mode") == "validated" for metric in metrics)
        )
        self.assertTrue(
            any(metric.trace_payload.get("unresolved_conflict_groups") == 234 for metric in metrics)
        )

    def test_cleaned_sample_builds_traceable_report_metrics(self) -> None:
        manifest = _clean_manifest()
        summary = validate_upload_batch(manifest)

        self.assertEqual(summary.high_count, 0)
        metrics = build_report_ready_metrics(manifest, summary)
        records = [metric.as_record() for metric in metrics]

        self.assertGreater(len(metrics), 100)
        self.assertTrue(all(record["tenant_id"] == "sand" for record in records))
        self.assertTrue(all(record["country_code"] == "RWA" for record in records))
        self.assertTrue(all(record["source_table"] for record in records))
        self.assertTrue(all(record["source_fields"] for record in records))
        self.assertTrue(all(record["calculation_rule"] for record in records))

    def test_national_core_metrics_match_cleaned_sample_totals(self) -> None:
        manifest = _clean_manifest()
        summary = validate_upload_batch(manifest)
        metrics = build_report_ready_metrics(manifest, summary)
        national = {
            metric.metric_name: metric
            for metric in metrics
            if metric.geography_level == "national" and metric.geography_id == "national"
        }
        clinical = manifest.datasets[DatasetKind.CLINICAL_NEONATAL].frame
        current = clinical[
            (clinical["reporting_month"] >= national["total_deliveries"].reporting_period_start)
            & (clinical["reporting_month"] <= national["total_deliveries"].reporting_period_end)
        ]
        deliveries = float(current["total_deliveries"].sum())
        live_births = float(current["live_births"].sum())
        deaths = float(
            current["neonatal_deaths_0_7d"].sum() + current["neonatal_deaths_8_28d"].sum()
        )

        self.assertEqual(national["total_deliveries"].metric_value, deliveries)
        self.assertEqual(national["live_births"].metric_value, live_births)
        self.assertAlmostEqual(
            national["neonatal_mortality_rate_per_1000_live_births"].metric_value or 0,
            deaths / live_births * 1000,
        )

    def test_facility_performance_score_is_bounded(self) -> None:
        manifest = _clean_manifest()
        summary = validate_upload_batch(manifest)
        metrics = build_report_ready_metrics(manifest, summary)
        scores = [m.metric_value for m in metrics if m.metric_name == "facility_performance_score"]

        self.assertEqual(len(scores), 117)
        self.assertTrue(all(score is not None and 0 <= score <= 100 for score in scores))

    def test_readiness_and_vulnerability_scores_are_bounded_and_ranked(self) -> None:
        manifest = _clean_manifest()
        summary = validate_upload_batch(manifest)
        metrics = build_report_ready_metrics(manifest, summary)

        readiness = [m.metric_value for m in metrics if m.metric_name == "neonatal_readiness_score"]
        vulnerability = [m.metric_value for m in metrics if m.metric_name == "facility_vulnerability_score"]
        ranks = [m for m in metrics if m.metric_name == "vulnerability_watchlist_rank"]
        anomaly_counts = [m.metric_value for m in metrics if m.metric_name == "anomaly_flag_count"]

        self.assertEqual(len(readiness), 117)
        self.assertEqual(len(vulnerability), 117)
        self.assertEqual(len(ranks), 10)
        self.assertEqual(len(anomaly_counts), 117)
        self.assertTrue(all(score is not None and 0 <= score <= 100 for score in readiness))
        self.assertTrue(all(score is not None and 0 <= score <= 100 for score in vulnerability))
        self.assertEqual(sorted(int(rank.metric_value or 0) for rank in ranks), list(range(1, 11)))
        self.assertTrue(all("explanation" in rank.trace_payload for rank in ranks))

    def test_readiness_subscores_have_traceable_components(self) -> None:
        manifest = _clean_manifest()
        summary = validate_upload_batch(manifest)
        metrics = build_report_ready_metrics(manifest, summary)
        subscore_names = {
            "neonatal_readiness_equipment_subscore",
            "neonatal_readiness_workforce_subscore",
            "neonatal_readiness_operations_subscore",
            "neonatal_readiness_governance_subscore",
        }
        subscores = [m for m in metrics if m.metric_name in subscore_names]

        self.assertEqual(len(subscores), 117 * 4)
        self.assertTrue(all(m.source_fields for m in subscores))
        self.assertTrue(all("component" in m.trace_payload for m in subscores))

    def test_report_metrics_insert_uses_report_ready_table(self) -> None:
        manifest = _clean_manifest()
        summary = validate_upload_batch(manifest)
        metrics = build_report_ready_metrics(manifest, summary)[:3]
        connection = FakeConnection()

        insert_report_ready_metrics(connection, metrics)

        combined_sql = "\n".join(connection.cursor_obj.statements)
        self.assertIn("INSERT INTO report_ready_metrics", combined_sql)
        self.assertTrue(connection.committed)


def _clean_manifest():
    manifest = build_upload_batch_manifest(DATA_DIR, tenant_id="sand", country_code="RWA")
    clinical_dataset = manifest.datasets[DatasetKind.CLINICAL_NEONATAL]
    clean_clinical = clinical_dataset.frame.drop_duplicates(
        subset=["facility_id", "reporting_month"],
        keep="first",
    ).reset_index(drop=True)
    manifest.datasets[DatasetKind.CLINICAL_NEONATAL] = replace(
        clinical_dataset,
        frame=clean_clinical,
    )

    governance_dataset = manifest.datasets[DatasetKind.GOVERNANCE]
    clean_governance = governance_dataset.frame.copy()
    clean_governance["hmis_reporting_completeness"] = clean_governance[
        "hmis_reporting_completeness"
    ].clip(lower=0.80)
    manifest.datasets[DatasetKind.GOVERNANCE] = replace(
        governance_dataset,
        frame=clean_governance,
    )
    return manifest


class FakeCursor:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str, params: object = None) -> None:
        self.statements.append(statement)


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_obj = FakeCursor()
        self.committed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.committed = True


if __name__ == "__main__":
    unittest.main()
