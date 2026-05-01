from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from sand_bulletin.analytics import AnalyticsBlockedError, build_report_ready_metrics
from sand_bulletin.data_quality import validate_upload_batch
from sand_bulletin.dashboard.data import metric_frame
from sand_bulletin.ingestion import build_upload_batch_manifest
from sand_bulletin.ingestion.datasets import DatasetKind
from sand_bulletin.narrative import build_metric_package, generate_narrative
from sand_bulletin.reports import generate_reports


DATA_DIR = Path(__file__).resolve().parents[1] / "docs" / "data"


class NarrativeTests(unittest.TestCase):
    def test_metric_package_contains_computed_metrics_not_raw_rows(self) -> None:
        manifest = _clean_manifest()
        summary = validate_upload_batch(manifest)
        metrics = build_report_ready_metrics(manifest, summary)
        package = build_metric_package(metric_frame(metrics), summary)

        self.assertEqual(package.country_code, "RWA")
        self.assertGreater(len(package.national_kpis), 3)
        self.assertGreater(len(package.highest_volume_facilities), 0)
        self.assertGreater(len(package.highest_vulnerability_facilities), 0)
        dumped = package.model_dump()
        self.assertIn("national_kpis", dumped)
        self.assertNotIn("clinical_neonatal", dumped)
        self.assertNotIn("raw_payload", dumped)

    def test_fallback_narrative_is_grounded_and_structured(self) -> None:
        manifest = _clean_manifest()
        summary = validate_upload_batch(manifest)
        metrics = build_report_ready_metrics(manifest, summary)
        package = build_metric_package(metric_frame(metrics), summary)

        narrative = generate_narrative(package, api_key=None, use_openai=False)

        self.assertEqual(narrative.mode, "fallback")
        self.assertIn("RWA", narrative.executive_summary)
        self.assertGreaterEqual(len(narrative.key_findings), 3)
        self.assertGreaterEqual(len(narrative.recommendations), 2)
        self.assertIn("total_deliveries", narrative.metric_references)

    def test_narrative_generation_blocks_when_raw_metrics_block(self) -> None:
        manifest = build_upload_batch_manifest(DATA_DIR, tenant_id="sand", country_code="RWA")
        summary = validate_upload_batch(manifest)

        with self.assertRaises(AnalyticsBlockedError):
            build_report_ready_metrics(manifest, summary, analysis_mode="raw")

    def test_report_html_includes_narrative_text(self) -> None:
        manifest = _clean_manifest()

        with tempfile.TemporaryDirectory() as tmp:
            generated = generate_reports(manifest, Path(tmp), use_openai=False)
            html = generated.html_path.read_text(encoding="utf-8")

        self.assertIn("Narrative mode: fallback", html)
        self.assertIn("Metric references:", html)


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
