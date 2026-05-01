from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from sand_bulletin.dashboard.data import (
    build_dashboard_dataset,
    geography_metric_table,
    national_kpis,
    top_facilities_by_metric,
)
from sand_bulletin.ingestion import build_upload_batch_manifest
from sand_bulletin.ingestion.datasets import DatasetKind


DATA_DIR = Path(__file__).resolve().parents[1] / "docs" / "data"


class DashboardDataTests(unittest.TestCase):
    def test_dashboard_dataset_blocks_raw_mode_when_high_severity_exists(self) -> None:
        manifest = build_upload_batch_manifest(DATA_DIR, tenant_id="sand", country_code="RWA")
        dataset = build_dashboard_dataset(manifest, analysis_mode="raw")

        self.assertTrue(dataset.analytics_blocked)
        self.assertEqual(len(dataset.metrics), 0)
        self.assertTrue(dataset.metrics_frame.empty)
        self.assertFalse(dataset.issues_frame.empty)
        self.assertGreater(dataset.quality_summary.high_count, 0)

    def test_dashboard_dataset_uses_validated_mode_by_default(self) -> None:
        manifest = build_upload_batch_manifest(DATA_DIR, tenant_id="sand", country_code="RWA")
        dataset = build_dashboard_dataset(manifest)

        self.assertFalse(dataset.analytics_blocked)
        self.assertGreater(len(dataset.metrics), 100)
        self.assertFalse(dataset.resolution_frame.empty)

    def test_dashboard_dataset_can_preview_metrics_with_explicit_override(self) -> None:
        manifest = build_upload_batch_manifest(DATA_DIR, tenant_id="sand", country_code="RWA")
        dataset = build_dashboard_dataset(manifest, allow_high_severity=True)

        self.assertFalse(dataset.analytics_blocked)
        self.assertGreater(len(dataset.metrics), 100)
        self.assertFalse(dataset.metrics_frame.empty)
        self.assertFalse(dataset.issues_frame.empty)

    def test_national_kpis_and_rankings_from_cleaned_manifest(self) -> None:
        dataset = build_dashboard_dataset(_clean_manifest())
        kpis = national_kpis(dataset.metrics_frame)

        self.assertFalse(dataset.analytics_blocked)
        self.assertIsNotNone(kpis["total_deliveries"])
        self.assertIsNotNone(kpis["neonatal_mortality_rate_per_1000_live_births"])

        top = top_facilities_by_metric(dataset.metrics_frame, "total_deliveries", limit=5)
        self.assertEqual(len(top), 5)
        self.assertIn("facility_id", top.columns)
        self.assertIn("metric_value", top.columns)

    def test_geography_metric_table_pivots_district_metrics(self) -> None:
        dataset = build_dashboard_dataset(_clean_manifest())
        table = geography_metric_table(
            dataset.metrics_frame,
            "district",
            ["total_deliveries", "live_births"],
        )

        self.assertFalse(table.empty)
        self.assertIn("geography_id", table.columns)
        self.assertIn("total_deliveries", table.columns)
        self.assertIn("live_births", table.columns)


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


if __name__ == "__main__":
    unittest.main()
