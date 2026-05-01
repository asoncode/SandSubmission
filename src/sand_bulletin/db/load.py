"""Database insertion routines for slice 1 ingestion."""

from __future__ import annotations

import json
from typing import Any

from sand_bulletin.analytics import ReportMetric
from sand_bulletin.data_quality import DataQualityIssue, DataQualitySummary
from sand_bulletin.ingestion.batches import UploadBatchManifest, normalized_records, staging_records


def insert_upload_batch(
    connection: Any,
    manifest: UploadBatchManifest,
    summary: DataQualitySummary | None = None,
    load_normalized: bool = True,
) -> None:
    """Insert one complete standardized upload batch into PostgreSQL.

    The connection is expected to be a psycopg 3 connection. Imports are kept out
    of this module so local CSV tests can run even before database dependencies
    are installed.
    """

    with connection.cursor() as cursor:
        _insert_upload_metadata(cursor, manifest)
        _insert_staging_rows(cursor, staging_records(manifest))
        if summary is not None:
            _insert_data_quality_issue_rows(cursor, summary.issues)
        if load_normalized:
            _insert_normalized_rows(cursor, normalized_records(manifest))
    connection.commit()


def insert_data_quality_issues(connection: Any, issues: list[DataQualityIssue]) -> None:
    """Insert structured validation issues into PostgreSQL."""

    with connection.cursor() as cursor:
        _insert_data_quality_issue_rows(cursor, issues)
    connection.commit()


def insert_report_ready_metrics(
    connection: Any,
    metrics: list[ReportMetric],
    bulletin_run_id: object | None = None,
) -> None:
    """Insert report-ready metrics into PostgreSQL."""

    with connection.cursor() as cursor:
        _insert_report_ready_metric_rows(cursor, metrics, bulletin_run_id)
    connection.commit()


def _insert_upload_metadata(cursor: Any, manifest: UploadBatchManifest) -> None:
    cursor.execute(
        """
        INSERT INTO upload_batches (
            id,
            tenant_id,
            country_code,
            reporting_period_start,
            reporting_period_end,
            status
        )
        VALUES (%s, %s, %s, %s, %s, 'standardized')
        """,
        (
            manifest.batch_id,
            manifest.tenant_id,
            manifest.country_code,
            manifest.reporting_period_start,
            manifest.reporting_period_end,
        ),
    )

    for upload in manifest.uploads.values():
        cursor.execute(
            """
            INSERT INTO uploads (
                id,
                batch_id,
                dataset_kind,
                source_filename,
                content_hash,
                row_count,
                status,
                stored_path
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'standardized', %s)
            """,
            (
                upload.upload_id,
                upload.batch_id,
                upload.kind.value,
                upload.source_path.name,
                upload.content_hash,
                upload.row_count,
                str(upload.source_path),
            ),
        )


def _insert_data_quality_issue_rows(cursor: Any, issues: list[DataQualityIssue]) -> None:
    for issue in issues:
        record = issue.as_record()
        cursor.execute(
            """
            INSERT INTO data_quality_issues (
                tenant_id,
                country_code,
                facility_id,
                reporting_month,
                dataset_kind,
                issue_type,
                severity,
                affected_column,
                observed_value,
                expected_rule,
                suggested_action,
                source_upload_id,
                source_row_number
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                record["tenant_id"],
                record["country_code"],
                record["facility_id"],
                record["reporting_month"],
                record["dataset_kind"],
                record["issue_type"],
                record["severity"],
                record["affected_column"],
                record["observed_value"],
                record["expected_rule"],
                record["suggested_action"],
                record["source_upload_id"],
                record["source_row_number"],
            ),
        )


def _insert_report_ready_metric_rows(
    cursor: Any,
    metrics: list[ReportMetric],
    bulletin_run_id: object | None,
) -> None:
    for metric in metrics:
        record = metric.as_record()
        cursor.execute(
            """
            INSERT INTO report_ready_metrics (
                bulletin_run_id,
                tenant_id,
                country_code,
                metric_version,
                reporting_period_start,
                reporting_period_end,
                geography_level,
                geography_id,
                facility_id,
                metric_name,
                metric_value,
                metric_unit,
                numerator,
                denominator,
                source_table,
                source_fields,
                calculation_rule,
                trace_payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                bulletin_run_id,
                record["tenant_id"],
                record["country_code"],
                record["metric_version"],
                record["reporting_period_start"],
                record["reporting_period_end"],
                record["geography_level"],
                record["geography_id"],
                record["facility_id"],
                record["metric_name"],
                record["metric_value"],
                record["metric_unit"],
                record["numerator"],
                record["denominator"],
                record["source_table"],
                record["source_fields"],
                record["calculation_rule"],
                json.dumps(record["trace_payload"], default=str),
            ),
        )


def _insert_staging_rows(cursor: Any, records: list[dict[str, object]]) -> None:
    for record in records:
        cursor.execute(
            """
            INSERT INTO staging_rows (
                upload_id,
                batch_id,
                tenant_id,
                country_code,
                dataset_kind,
                source_row_number,
                standardized_payload,
                raw_payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
            """,
            (
                record["upload_id"],
                record["batch_id"],
                record["tenant_id"],
                record["country_code"],
                record["dataset_kind"],
                record["source_row_number"],
                json.dumps(record["standardized_payload"], default=str),
                json.dumps(record["raw_payload"], default=str),
            ),
        )


def _insert_normalized_rows(cursor: Any, tables: dict[str, list[dict[str, object]]]) -> None:
    for record in tables["facilities"]:
        _insert_facility(cursor, record)
    for record in tables["clinical_neonatal_monthly"]:
        _insert_row(cursor, "clinical_neonatal_monthly", record)
    for record in tables["governance_facility"]:
        _insert_row(cursor, "governance_facility", record)
    for record in tables["workforce_facility"]:
        _insert_row(cursor, "workforce_facility", record)
    for record in tables["operations_facility"]:
        _insert_row(cursor, "operations_facility", record)


def _insert_facility(cursor: Any, record: dict[str, object]) -> None:
    columns = tuple(record.keys())
    placeholders = ", ".join(["%s"] * len(columns))
    column_sql = ", ".join(columns)
    values = tuple(record[column] for column in columns)
    cursor.execute(
        f"""
        INSERT INTO facilities ({column_sql})
        VALUES ({placeholders})
        ON CONFLICT (tenant_id, country_code, facility_id) DO UPDATE SET
            facility_name = EXCLUDED.facility_name,
            district = EXCLUDED.district,
            province = EXCLUDED.province,
            tier_level = EXCLUDED.tier_level,
            gps_lat = EXCLUDED.gps_lat,
            gps_lon = EXCLUDED.gps_lon,
            nicu_available = EXCLUDED.nicu_available,
            nicu_beds = EXCLUDED.nicu_beds,
            incubators_functional = EXCLUDED.incubators_functional,
            incubators_total = EXCLUDED.incubators_total,
            radiant_warmers = EXCLUDED.radiant_warmers,
            phototherapy_units = EXCLUDED.phototherapy_units,
            cpap_machines = EXCLUDED.cpap_machines,
            resuscitation_tables = EXCLUDED.resuscitation_tables,
            kangaroo_care_space = EXCLUDED.kangaroo_care_space,
            electricity_reliable = EXCLUDED.electricity_reliable,
            backup_generator = EXCLUDED.backup_generator,
            source_upload_id = EXCLUDED.source_upload_id,
            source_row_number = EXCLUDED.source_row_number,
            updated_at = now()
        """,
        values,
    )


def _insert_row(cursor: Any, table_name: str, record: dict[str, object]) -> None:
    columns = tuple(record.keys())
    placeholders = ", ".join(["%s"] * len(columns))
    column_sql = ", ".join(columns)
    values = tuple(record[column] for column in columns)
    cursor.execute(
        f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})",
        values,
    )
