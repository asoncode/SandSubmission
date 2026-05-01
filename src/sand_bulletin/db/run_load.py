"""CLI-facing helper for loading the MVP CSV directory into PostgreSQL."""

from __future__ import annotations

from pathlib import Path

from sand_bulletin.data_quality import validate_upload_batch
from sand_bulletin.ingestion import build_upload_batch_manifest


def load_directory_to_database(
    database_url: str,
    data_dir: Path,
    tenant_id: str = "default",
    country_code: str = "RWA",
    validate: bool = True,
    allow_high_severity: bool = False,
) -> None:
    """Load a complete MVP data directory into the configured PostgreSQL database."""

    import psycopg

    manifest = build_upload_batch_manifest(data_dir, tenant_id=tenant_id, country_code=country_code)
    summary = validate_upload_batch(manifest) if validate else None
    load_normalized = summary is None or summary.can_generate_report or allow_high_severity

    from sand_bulletin.db import insert_upload_batch

    with psycopg.connect(database_url) as connection:
        insert_upload_batch(
            connection,
            manifest,
            summary=summary,
            load_normalized=load_normalized,
        )
