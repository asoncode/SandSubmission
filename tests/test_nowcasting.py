from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from sand_bulletin.analytics import build_report_ready_metrics
from sand_bulletin.data_quality import validate_upload_batch
from sand_bulletin.ingestion import build_upload_batch_manifest
from sand_bulletin.ingestion.datasets import DatasetKind
from sand_bulletin.nowcasting import NowcastingBlockedError, build_nowcast_metrics


DATA_DIR = Path(__file__).resolve().parents[1] / "docs" / "data"


class NowcastingTests(unittest.TestCase):
    def test_raw_mode_high_severity_quality_issues_block_nowcasting_by_default(self) -> None:
        manifest = build_upload_batch_manifest(DATA_DIR, tenant_id="sand", country_code="RWA")
        summary = validate_upload_batch(manifest)

        with self.assertRaises(NowcastingBlockedError):
            build_nowcast_metrics(manifest, summary, analysis_mode="raw")

    def test_nowcasts_are_backtested_and_labeled_as_estimates(self) -> None:
        manifest = _clean_manifest()
        summary = validate_upload_batch(manifest)
        metrics = build_nowcast_metrics(manifest, summary)

        self.assertGreater(len(metrics), 0)
        self.assertTrue(all(metric.metric_name.startswith("nowcast_") for metric in metrics))
        self.assertFalse(any("mortality" in metric.metric_name for metric in metrics))
        for metric in metrics:
            self.assertEqual(metric.metric_version, "slice8_nowcast_v1")
            self.assertEqual(metric.geography_level, "facility")
            self.assertIn("not official reported data", str(metric.trace_payload["label"]))
            self.assertLess(metric.trace_payload["model_mae"], metric.trace_payload["baseline_mae"])
            self.assertGreaterEqual(metric.trace_payload["backtest_periods"], 2)

    def test_report_ready_metrics_include_nowcasting_prototype_records(self) -> None:
        manifest = _clean_manifest()
        summary = validate_upload_batch(manifest)
        metrics = build_report_ready_metrics(manifest, summary)
        nowcasts = [metric for metric in metrics if metric.metric_name.startswith("nowcast_")]

        self.assertGreater(len(nowcasts), 0)
        self.assertTrue(
            any(
                metric.metric_name == "nowcast_expected_delivery_volume_next_month"
                for metric in nowcasts
            )
        )


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
