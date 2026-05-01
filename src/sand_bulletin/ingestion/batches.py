"""Batch-level metadata for loading the five MVP files together."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

import pandas as pd

from sand_bulletin.ingestion.datasets import DatasetKind
from sand_bulletin.ingestion.loaders import LoadedDataset, load_mvp_directory


@dataclass(frozen=True)
class UploadManifest:
    """Metadata for one standardized source file in an upload batch."""

    upload_id: UUID
    batch_id: UUID
    kind: DatasetKind
    source_path: Path
    content_hash: str
    row_count: int


@dataclass(frozen=True)
class UploadBatchManifest:
    """Metadata that groups all files used for one bulletin input batch."""

    batch_id: UUID
    tenant_id: str
    country_code: str
    reporting_period_start: Optional[date]
    reporting_period_end: Optional[date]
    uploads: dict[DatasetKind, UploadManifest]
    datasets: dict[DatasetKind, LoadedDataset]


def build_upload_batch_manifest(
    data_dir: Path,
    tenant_id: str = "default",
    country_code: str = "RWA",
    batch_id: Optional[UUID] = None,
) -> UploadBatchManifest:
    """Load the five MVP files and create traceable batch/upload metadata."""

    resolved_batch_id = batch_id or uuid4()
    datasets = load_mvp_directory(data_dir)
    uploads = {
        kind: UploadManifest(
            upload_id=uuid4(),
            batch_id=resolved_batch_id,
            kind=kind,
            source_path=dataset.source_path,
            content_hash=file_sha256(dataset.source_path),
            row_count=dataset.row_count,
        )
        for kind, dataset in datasets.items()
    }
    period_start, period_end = infer_reporting_period(datasets[DatasetKind.CLINICAL_NEONATAL])
    return UploadBatchManifest(
        batch_id=resolved_batch_id,
        tenant_id=tenant_id,
        country_code=country_code,
        reporting_period_start=period_start,
        reporting_period_end=period_end,
        uploads=uploads,
        datasets=datasets,
    )


def file_sha256(path: Path) -> str:
    """Return a content hash for upload auditability."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_reporting_period(dataset: LoadedDataset) -> tuple[Optional[date], Optional[date]]:
    """Infer the clinical reporting window from the monthly clinical file."""

    if "reporting_month" not in dataset.frame:
        return None, None
    months = dataset.frame["reporting_month"].dropna()
    if months.empty:
        return None, None
    return months.min(), months.max()


def staging_records(manifest: UploadBatchManifest) -> list[dict[str, object]]:
    """Return row-level staging records ready for database insertion."""

    records: list[dict[str, object]] = []
    for kind, dataset in manifest.datasets.items():
        upload = manifest.uploads[kind]
        for row_number, (_, standardized_row) in enumerate(dataset.frame.iterrows(), start=1):
            raw_row = dataset.raw_frame.iloc[row_number - 1]
            records.append(
                {
                    "upload_id": upload.upload_id,
                    "batch_id": manifest.batch_id,
                    "tenant_id": manifest.tenant_id,
                    "country_code": manifest.country_code,
                    "dataset_kind": kind.value,
                    "source_row_number": row_number,
                    "standardized_payload": json_ready_dict(standardized_row.to_dict()),
                    "raw_payload": json_ready_dict(raw_row.to_dict()),
                }
            )
    return records


def normalized_records(manifest: UploadBatchManifest) -> dict[str, list[dict[str, object]]]:
    """Return normalized table rows derived from the standardized MVP files."""

    return {
        "facilities": _scoped_records(manifest, DatasetKind.FACILITIES),
        "clinical_neonatal_monthly": _scoped_records(manifest, DatasetKind.CLINICAL_NEONATAL),
        "governance_facility": _scoped_records(manifest, DatasetKind.GOVERNANCE),
        "workforce_facility": _scoped_records(manifest, DatasetKind.HEALTHCARE_WORKERS),
        "operations_facility": _scoped_records(manifest, DatasetKind.OPERATIONS),
    }


def _scoped_records(
    manifest: UploadBatchManifest,
    kind: DatasetKind,
) -> list[dict[str, object]]:
    dataset = manifest.datasets[kind]
    upload = manifest.uploads[kind]
    records: list[dict[str, object]] = []
    for row_number, (_, row) in enumerate(dataset.frame.iterrows(), start=1):
        payload = json_ready_dict(row.to_dict())
        payload.update(
            {
                "tenant_id": manifest.tenant_id,
                "country_code": manifest.country_code,
                "source_upload_id": upload.upload_id,
                "source_row_number": row_number,
            }
        )
        records.append(payload)
    return records


def json_ready_dict(values: dict[str, object]) -> dict[str, object]:
    """Convert pandas/numpy scalar values into JSON-compatible Python values."""

    converted: dict[str, object] = {}
    for key, value in values.items():
        if pd.isna(value):
            converted[key] = None
        elif hasattr(value, "item"):
            converted[key] = value.item()
        else:
            converted[key] = value
    return converted
