"""Report-ready metric records shared by dashboard, reports, exports, and LLM packages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class ReportMetric:
    """A traceable metric ready for the common reporting layer."""

    tenant_id: str
    country_code: str
    metric_version: str
    reporting_period_start: date
    reporting_period_end: date
    geography_level: str
    geography_id: str
    metric_name: str
    source_table: str
    source_fields: list[str]
    calculation_rule: str
    metric_value: Optional[float] = None
    metric_unit: Optional[str] = None
    numerator: Optional[float] = None
    denominator: Optional[float] = None
    facility_id: Optional[str] = None
    trace_payload: dict[str, object] = field(default_factory=dict)

    def as_record(self) -> dict[str, object]:
        """Return a database-ready report metric dictionary."""

        return {
            "tenant_id": self.tenant_id,
            "country_code": self.country_code,
            "metric_version": self.metric_version,
            "reporting_period_start": self.reporting_period_start,
            "reporting_period_end": self.reporting_period_end,
            "geography_level": self.geography_level,
            "geography_id": self.geography_id,
            "facility_id": self.facility_id,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "metric_unit": self.metric_unit,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "source_table": self.source_table,
            "source_fields": self.source_fields,
            "calculation_rule": self.calculation_rule,
            "trace_payload": self.trace_payload,
        }
