from __future__ import annotations

from datetime import date
from pathlib import Path
import unittest

from sand_bulletin.ingestion import (
    DatasetKind,
    build_upload_batch_manifest,
    load_dataset,
    load_mvp_directory,
    normalized_records,
    staging_records,
)
from sand_bulletin.ingestion.standardize import (
    parse_availability_frequency,
    parse_availability_status,
    parse_boolean,
    parse_date,
    parse_month,
    parse_percent,
    standardize_column_name,
)


DATA_DIR = Path(__file__).resolve().parents[1] / "docs" / "data"


class StandardizationTests(unittest.TestCase):
    def test_standardize_column_name(self) -> None:
        self.assertEqual(standardize_column_name("Facility ID"), "facility_id")
        self.assertEqual(standardize_column_name("Apgar Less 7 at 5min"), "apgar_less_7_at_5min")

    def test_value_parsers(self) -> None:
        self.assertEqual(parse_percent("89%"), 0.89)
        self.assertEqual(parse_percent("70"), 0.70)
        self.assertEqual(parse_boolean("Yes"), True)
        self.assertEqual(parse_boolean("No"), False)
        self.assertIsNone(parse_boolean("Partial"))
        self.assertEqual(parse_availability_status("Yes"), "yes")
        self.assertEqual(parse_availability_status("Full"), "yes")
        self.assertEqual(parse_availability_status("Partial"), "partial")
        self.assertEqual(parse_availability_status("None"), "no")
        self.assertEqual(parse_availability_frequency("Usually"), "usually")
        self.assertEqual(parse_date("2025-03"), date(2025, 3, 1))
        self.assertIsNone(parse_date("Never"))
        self.assertEqual(parse_month("2024-11"), date(2024, 11, 1))


class MvpDataLoadTests(unittest.TestCase):
    def test_loads_all_mvp_files(self) -> None:
        loaded = load_mvp_directory(DATA_DIR)

        self.assertEqual(set(loaded), set(DatasetKind))
        self.assertEqual(loaded[DatasetKind.CLINICAL_NEONATAL].row_count, 1404)
        self.assertEqual(loaded[DatasetKind.FACILITIES].row_count, 117)
        self.assertEqual(loaded[DatasetKind.GOVERNANCE].row_count, 117)
        self.assertEqual(loaded[DatasetKind.HEALTHCARE_WORKERS].row_count, 117)
        self.assertEqual(loaded[DatasetKind.OPERATIONS].row_count, 117)

    def test_clinical_months_and_facilities_standardize(self) -> None:
        dataset = load_dataset(DATA_DIR / "clinical_neonatal.csv")

        self.assertEqual(dataset.kind, DatasetKind.CLINICAL_NEONATAL)
        self.assertEqual(dataset.frame["facility_id"].nunique(), 117)
        self.assertEqual(dataset.frame["reporting_month"].min(), date(2024, 1, 1))
        self.assertEqual(dataset.frame["reporting_month"].max(), date(2024, 11, 1))
        self.assertEqual(str(dataset.frame["total_deliveries"].dtype), "Int64")

    def test_governance_percentages_are_fractions(self) -> None:
        dataset = load_dataset(DATA_DIR / "governance.csv")
        first = dataset.frame.iloc[0]

        self.assertEqual(first["facility_id"], "NYA001")
        self.assertAlmostEqual(first["hmis_reporting_completeness"], 0.89)
        self.assertEqual(first["newborn_protocol_exists"], True)
        self.assertEqual(first["protocol_last_updated"], date(2025, 3, 1))

    def test_facility_availability_fields_are_enums(self) -> None:
        dataset = load_dataset(DATA_DIR / "facilities.csv")
        first = dataset.frame.iloc[0]

        self.assertEqual(first["nicu_available"], "partial")
        self.assertEqual(first["kangaroo_care_space"], "partial")
        self.assertEqual(first["electricity_reliable"], "yes")
        self.assertEqual(first["backup_generator"], True)

    def test_upload_batch_manifest_groups_all_files(self) -> None:
        manifest = build_upload_batch_manifest(DATA_DIR, tenant_id="sand", country_code="RWA")

        self.assertEqual(manifest.tenant_id, "sand")
        self.assertEqual(manifest.country_code, "RWA")
        self.assertEqual(manifest.reporting_period_start, date(2024, 1, 1))
        self.assertEqual(manifest.reporting_period_end, date(2024, 11, 1))
        self.assertEqual(set(manifest.uploads), set(DatasetKind))
        self.assertTrue(all(len(upload.content_hash) == 64 for upload in manifest.uploads.values()))

    def test_staging_and_normalized_records_include_scope_and_trace(self) -> None:
        manifest = build_upload_batch_manifest(DATA_DIR, tenant_id="sand", country_code="RWA")
        staged = staging_records(manifest)
        normalized = normalized_records(manifest)

        self.assertEqual(len(staged), 1872)
        self.assertEqual(staged[0]["tenant_id"], "sand")
        self.assertEqual(staged[0]["country_code"], "RWA")
        self.assertIn("standardized_payload", staged[0])
        self.assertIn("raw_payload", staged[0])

        facility = normalized["facilities"][0]
        self.assertEqual(facility["tenant_id"], "sand")
        self.assertEqual(facility["country_code"], "RWA")
        self.assertEqual(facility["source_row_number"], 1)
        self.assertEqual(facility["nicu_available"], "partial")


if __name__ == "__main__":
    unittest.main()
