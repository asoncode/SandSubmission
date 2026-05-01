"""Structured data quality issue records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional
from uuid import UUID


class IssueSeverity(str, Enum):
    """Validation issue severity used by downstream report gating."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class DataQualityIssue:
    """A row-level or dataset-level validation finding."""

    tenant_id: str
    country_code: str
    issue_type: str
    severity: IssueSeverity
    expected_rule: str
    suggested_action: str
    dataset_kind: Optional[str] = None
    facility_id: Optional[str] = None
    reporting_month: Optional[date] = None
    affected_column: Optional[str] = None
    observed_value: Optional[str] = None
    source_upload_id: Optional[UUID] = None
    source_row_number: Optional[int] = None

    def as_record(self) -> dict[str, object]:
        """Return a database-ready issue dictionary."""

        return {
            "tenant_id": self.tenant_id,
            "country_code": self.country_code,
            "facility_id": self.facility_id,
            "reporting_month": self.reporting_month,
            "dataset_kind": self.dataset_kind,
            "issue_type": self.issue_type,
            "severity": self.severity.value,
            "affected_column": self.affected_column,
            "observed_value": self.observed_value,
            "expected_rule": self.expected_rule,
            "suggested_action": self.suggested_action,
            "source_upload_id": self.source_upload_id,
            "source_row_number": self.source_row_number,
        }
