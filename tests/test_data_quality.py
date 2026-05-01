from __future__ import annotations

from datetime import date
from pathlib import Path
import unittest

from sand_bulletin.data_quality import IssueSeverity, validate_upload_batch
from sand_bulletin.db.load import insert_upload_batch
from sand_bulletin.ingestion import build_upload_batch_manifest
from sand_bulletin.ingestion.datasets import DatasetKind


DATA_DIR = Path(__file__).resolve().parents[1] / "docs" / "data"


class DataQualityTests(unittest.TestCase):
    def test_sample_data_validation_summary_is_structured(self) -> None:
        manifest = build_upload_batch_manifest(DATA_DIR, tenant_id="sand", country_code="RWA")
        summary = validate_upload_batch(manifest)

        self.assertGreater(summary.issue_count, 0)
        self.assertEqual(
            summary.issue_count,
            summary.high_count + summary.medium_count + summary.low_count,
        )
        self.assertIn("conflicting_facility_month_submission", summary.counts_by_type())
        self.assertIn("low_reporting_completeness", summary.counts_by_type())
        self.assertFalse(summary.can_generate_report)
        first_issue = summary.issues[0]
        self.assertEqual(first_issue.tenant_id, "sand")
        self.assertEqual(first_issue.country_code, "RWA")
        self.assertIsNotNone(first_issue.source_upload_id)
        self.assertIsNotNone(first_issue.source_row_number)

    def test_logical_inconsistencies_are_high_severity_issues(self) -> None:
        manifest = build_upload_batch_manifest(DATA_DIR, tenant_id="sand", country_code="RWA")
        clinical = manifest.datasets[DatasetKind.CLINICAL_NEONATAL].frame
        clinical.loc[0, "live_births"] = 1
        clinical.loc[0, "neonatal_deaths_0_7d"] = 5
        clinical.loc[0, "neonatal_deaths_8_28d"] = 2
        clinical.loc[1, "stillbirths"] = 999
        clinical.loc[2, "preterm_births_28_32w"] = 999
        clinical.loc[2, "preterm_births_32_37w"] = 999

        summary = validate_upload_batch(manifest)
        issue_types = {issue.issue_type for issue in summary.issues}

        self.assertIn("neonatal_deaths_exceed_live_births", issue_types)
        self.assertIn("stillbirths_exceed_deliveries", issue_types)
        self.assertIn("preterm_births_exceed_live_births", issue_types)
        self.assertTrue(
            any(
                issue.issue_type == "neonatal_deaths_exceed_live_births"
                and issue.severity == IssueSeverity.HIGH
                for issue in summary.issues
            )
        )

    def test_conflicting_facility_month_blocks_report_generation(self) -> None:
        manifest = build_upload_batch_manifest(DATA_DIR, tenant_id="sand", country_code="RWA")
        clinical = manifest.datasets[DatasetKind.CLINICAL_NEONATAL].frame
        clinical.loc[1, "facility_id"] = clinical.loc[0, "facility_id"]
        clinical.loc[1, "reporting_month"] = clinical.loc[0, "reporting_month"]
        clinical.loc[1, "total_deliveries"] = clinical.loc[0, "total_deliveries"] + 1

        summary = validate_upload_batch(manifest)

        self.assertFalse(summary.can_generate_report)
        self.assertTrue(
            any(
                issue.issue_type == "conflicting_facility_month_submission"
                and issue.severity == IssueSeverity.HIGH
                for issue in summary.issues
            )
        )

    def test_exact_duplicate_facility_month_is_medium_and_can_be_collapsed(self) -> None:
        manifest = build_upload_batch_manifest(DATA_DIR, tenant_id="sand", country_code="RWA")
        clinical = manifest.datasets[DatasetKind.CLINICAL_NEONATAL].frame
        clinical.loc[1] = clinical.loc[0]
        clinical.loc[0, "reporting_month"] = date(2024, 2, 1)
        clinical.loc[1, "reporting_month"] = date(2024, 2, 1)

        summary = validate_upload_batch(manifest)

        self.assertTrue(
            any(
                issue.issue_type == "duplicate_facility_month"
                and issue.severity == IssueSeverity.MEDIUM
                for issue in summary.issues
            )
        )

    def test_missingness_and_reporting_quality_are_flagged(self) -> None:
        manifest = build_upload_batch_manifest(DATA_DIR, tenant_id="sand", country_code="RWA")
        facilities = manifest.datasets[DatasetKind.FACILITIES].frame
        governance = manifest.datasets[DatasetKind.GOVERNANCE].frame
        facilities.loc[0, "gps_lat"] = None
        governance.loc[0, "hmis_reporting_completeness"] = 0.50

        summary = validate_upload_batch(manifest)

        self.assertTrue(
            any(
                issue.issue_type == "missing_value"
                and issue.affected_column == "gps_lat"
                for issue in summary.issues
            )
        )
        self.assertTrue(
            any(
                issue.issue_type == "low_reporting_completeness"
                and issue.severity == IssueSeverity.HIGH
                for issue in summary.issues
            )
        )

    def test_issue_records_are_database_ready(self) -> None:
        manifest = build_upload_batch_manifest(DATA_DIR, tenant_id="sand", country_code="RWA")
        summary = validate_upload_batch(manifest)
        record = summary.issues[0].as_record()

        self.assertEqual(record["tenant_id"], "sand")
        self.assertEqual(record["country_code"], "RWA")
        self.assertIn(record["severity"], {"low", "medium", "high"})
        self.assertIn("expected_rule", record)
        self.assertIn("suggested_action", record)
        self.assertTrue(record["reporting_month"] is None or isinstance(record["reporting_month"], date))

    def test_db_insert_can_stage_and_record_issues_without_normalized_load(self) -> None:
        manifest = build_upload_batch_manifest(DATA_DIR, tenant_id="sand", country_code="RWA")
        summary = validate_upload_batch(manifest)
        connection = FakeConnection()

        insert_upload_batch(
            connection,
            manifest,
            summary=summary,
            load_normalized=False,
        )

        combined_sql = "\n".join(connection.cursor_obj.statements)
        self.assertIn("INSERT INTO upload_batches", combined_sql)
        self.assertIn("INSERT INTO staging_rows", combined_sql)
        self.assertIn("INSERT INTO data_quality_issues", combined_sql)
        self.assertNotIn("INSERT INTO facilities", combined_sql)
        self.assertTrue(connection.committed)


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
