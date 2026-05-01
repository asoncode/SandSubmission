"""Read MVP source files into standardized data frames."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from sand_bulletin.ingestion.datasets import DATASET_SPECS, DatasetKind, infer_dataset_kind
from sand_bulletin.ingestion.standardize import coerce_frame, require_columns, standardize_columns


@dataclass(frozen=True)
class LoadedDataset:
    """A standardized source dataset plus trace metadata for later DB loading."""

    kind: DatasetKind
    source_path: Path
    row_count: int
    raw_frame: pd.DataFrame
    frame: pd.DataFrame


def load_dataset(path: Path, kind: Optional[DatasetKind] = None) -> LoadedDataset:
    """Load one known CSV file and apply column/type standardization."""

    resolved_kind = kind or infer_dataset_kind(path)
    spec = DATASET_SPECS[resolved_kind]
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    standardized = standardize_columns(raw)
    require_columns(standardized, spec)
    coerced = coerce_frame(standardized, spec)
    return LoadedDataset(
        kind=resolved_kind,
        source_path=path,
        row_count=len(coerced),
        raw_frame=standardized,
        frame=coerced,
    )


def load_mvp_directory(data_dir: Path) -> dict[DatasetKind, LoadedDataset]:
    """Load the five required MVP CSVs from a data directory."""

    loaded: dict[DatasetKind, LoadedDataset] = {}
    for kind, spec in DATASET_SPECS.items():
        path = data_dir / spec.filename
        if not path.exists():
            raise FileNotFoundError(f"Required MVP data file not found: {path}")
        loaded[kind] = load_dataset(path, kind)
    return loaded
