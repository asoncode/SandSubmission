"""Column and value standardization for MVP CSV inputs."""

from __future__ import annotations

from datetime import date
import re
from typing import Any, Optional

import pandas as pd

from sand_bulletin.ingestion.datasets import DatasetSpec


_MISSING_STRINGS = {"", "na", "n/a", "null", "none"}
_NEVER_STRINGS = {"never"}
_TRUE_STRINGS = {"yes", "true", "1"}
_FALSE_STRINGS = {"no", "false", "0"}
_AVAILABILITY_YES = {"yes", "full", "true", "1"}
_AVAILABILITY_PARTIAL = {"partial"}
_AVAILABILITY_NO = {"no", "none", "false", "0"}
_FREQUENCY_VALUES = {"always", "usually", "rarely", "never"}


def standardize_column_name(name: str) -> str:
    """Convert source headers into lower snake case."""

    normalized = name.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized


def standardize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with standardized column names."""

    renamed = {column: standardize_column_name(str(column)) for column in frame.columns}
    return frame.rename(columns=renamed)


def require_columns(frame: pd.DataFrame, spec: DatasetSpec) -> None:
    """Raise a clear error when a source file does not match its expected contract."""

    missing = sorted(set(spec.required_columns).difference(frame.columns))
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"{spec.kind.value} is missing required columns: {joined}")


def coerce_frame(frame: pd.DataFrame, spec: DatasetSpec) -> pd.DataFrame:
    """Coerce known columns into normalized Python/pandas values."""

    coerced = frame.copy()
    for column in coerced.columns:
        if coerced[column].dtype == object:
            coerced[column] = coerced[column].map(_strip_or_none)

    for column in spec.integer_columns:
        coerced[column] = pd.to_numeric(coerced[column], errors="coerce").astype("Int64")

    for column in spec.float_columns:
        coerced[column] = pd.to_numeric(coerced[column], errors="coerce")

    for column in spec.percent_columns:
        coerced[column] = coerced[column].map(parse_percent)

    for column in spec.boolean_columns:
        coerced[column] = coerced[column].map(parse_boolean)

    for column in spec.availability_columns:
        coerced[column] = coerced[column].map(parse_availability_status)

    for column in spec.frequency_columns:
        coerced[column] = coerced[column].map(parse_availability_frequency)

    for column in spec.date_columns:
        coerced[column] = coerced[column].map(parse_date)

    for column in spec.month_columns:
        coerced[column] = coerced[column].map(parse_month)

    return coerced


def _strip_or_none(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if stripped.lower() in _MISSING_STRINGS:
        return None
    return stripped


def parse_boolean(value: Any) -> Optional[bool]:
    """Parse explicit yes/no values without coercing partial categorical responses."""

    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in _TRUE_STRINGS:
        return True
    if normalized in _FALSE_STRINGS:
        return False
    return None


def parse_availability_status(value: Any) -> str:
    """Parse yes/no/partial-style fields into the database enum vocabulary."""

    if value is None or pd.isna(value):
        return "unknown"
    normalized = str(value).strip().lower()
    if normalized in _AVAILABILITY_YES:
        return "yes"
    if normalized in _AVAILABILITY_PARTIAL:
        return "partial"
    if normalized in _AVAILABILITY_NO:
        return "no"
    if normalized in _MISSING_STRINGS:
        return "unknown"
    return "unknown"


def parse_availability_frequency(value: Any) -> str:
    """Parse operational availability frequency values into enum vocabulary."""

    if value is None or pd.isna(value):
        return "unknown"
    normalized = str(value).strip().lower()
    if normalized in _FREQUENCY_VALUES:
        return normalized
    return "unknown"


def parse_percent(value: Any) -> Optional[float]:
    """Parse percent strings as fractions between 0 and 1."""

    if value is None or pd.isna(value):
        return None
    normalized = str(value).strip()
    if normalized.lower() in _MISSING_STRINGS:
        return None
    number = normalized[:-1] if normalized.endswith("%") else normalized
    parsed = pd.to_numeric(number, errors="coerce")
    if pd.isna(parsed):
        return None
    return float(parsed) / 100.0


def parse_date(value: Any) -> Optional[date]:
    """Parse YYYY-MM dates as first-of-month dates and preserve Never as missing."""

    if value is None or pd.isna(value):
        return None
    normalized = str(value).strip()
    if normalized.lower() in _MISSING_STRINGS | _NEVER_STRINGS:
        return None
    parsed = pd.to_datetime(normalized, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def parse_month(value: Any) -> Optional[date]:
    """Parse reporting month values into first-of-month dates."""

    parsed = parse_date(value)
    if parsed is None:
        return None
    return date(parsed.year, parsed.month, 1)
