"""Rule-based validation checks for standardized MVP data."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

import pandas as pd

from sand_bulletin.data_quality.issues import DataQualityIssue, IssueSeverity
from sand_bulletin.ingestion.batches import UploadBatchManifest
from sand_bulletin.ingestion.datasets import DatasetKind


CLINICAL_REQUIRED_COLUMNS = (
    "facility_id",
    "reporting_month",
    "total_deliveries",
    "live_births",
    "neonatal_deaths_0_7d",
    "neonatal_deaths_8_28d",
    "stillbirths",
    "preterm_births_28_32w",
    "preterm_births_32_37w",
    "apgar_less_7_at_5min",
    "birth_weight_less_2500g",
)

FACILITY_REQUIRED_COLUMNS = (
    "facility_id",
    "facility_name",
    "district",
    "province",
    "gps_lat",
    "gps_lon",
)

OPERATIONS_REQUIRED_COLUMNS = (
    "facility_id",
    "avg_referral_time_hrs",
    "oxygen_cylinders_available",
    "oxygen_concentrators",
    "essential_drugs_stockouts_days",
    "referral_feedback_rate",
)

PERCENT_COLUMNS_BY_KIND = {
    DatasetKind.GOVERNANCE: (
        "death_audits_conducted_pct",
        "staff_trained_on_protocol_pct",
        "hmis_reporting_completeness",
        "bag_mask_ventilation_competency",
        "thermal_care_protocol_compliance",
        "infection_prevention_score",
    ),
    DatasetKind.OPERATIONS: ("referral_feedback_rate",),
}

STATIC_SNAPSHOT_DATE_COLUMNS_BY_KIND = {
    DatasetKind.GOVERNANCE: ("protocol_last_updated",),
    DatasetKind.HEALTHCARE_WORKERS: ("last_neonatal_training_date",),
}

CLINICAL_REPORT_VALUE_COLUMNS = tuple(
    column
    for column in (
        "total_deliveries",
        "live_births",
        "neonatal_deaths_0_7d",
        "neonatal_deaths_8_28d",
        "stillbirths",
        "death_birth_asphyxia",
        "death_prematurity",
        "death_sepsis",
        "death_congenital",
        "death_other",
        "avg_gestational_age",
        "preterm_births_28_32w",
        "preterm_births_32_37w",
        "apgar_less_7_at_5min",
        "birth_weight_less_2500g",
    )
)


@dataclass(frozen=True)
class DataQualitySummary:
    """Aggregate validation result for one upload batch."""

    issues: list[DataQualityIssue]

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def high_count(self) -> int:
        return self.count_by_severity(IssueSeverity.HIGH)

    @property
    def medium_count(self) -> int:
        return self.count_by_severity(IssueSeverity.MEDIUM)

    @property
    def low_count(self) -> int:
        return self.count_by_severity(IssueSeverity.LOW)

    @property
    def can_generate_report(self) -> bool:
        """High severity issues require correction or explicit override."""

        return self.high_count == 0

    def count_by_severity(self, severity: IssueSeverity) -> int:
        return sum(1 for issue in self.issues if issue.severity == severity)

    def counts_by_type(self) -> dict[str, int]:
        return dict(Counter(issue.issue_type for issue in self.issues))


def validate_upload_batch(manifest: UploadBatchManifest) -> DataQualitySummary:
    """Run all MVP data quality checks against one standardized upload batch."""

    issues: list[DataQualityIssue] = []
    issues.extend(_check_referential_integrity(manifest))
    issues.extend(_check_missingness(manifest))
    issues.extend(_check_duplicate_clinical_months(manifest))
    issues.extend(_check_logical_consistency(manifest))
    issues.extend(_check_percentage_ranges(manifest))
    issues.extend(_check_static_snapshot_dates(manifest))
    issues.extend(_check_reporting_quality(manifest))
    issues.extend(_check_outliers(manifest))
    return DataQualitySummary(issues=issues)


def _check_referential_integrity(manifest: UploadBatchManifest) -> list[DataQualityIssue]:
    facilities = manifest.datasets[DatasetKind.FACILITIES].frame
    known_facilities = set(facilities["facility_id"].dropna())
    issues: list[DataQualityIssue] = []

    for kind, dataset in manifest.datasets.items():
        if kind == DatasetKind.FACILITIES or "facility_id" not in dataset.frame:
            continue
        upload = manifest.uploads[kind]
        for row_number, row in _iter_rows(dataset.frame):
            facility_id = _optional_str(row.get("facility_id"))
            if facility_id and facility_id not in known_facilities:
                issues.append(
                    _issue(
                        manifest,
                        kind,
                        upload.upload_id,
                        row_number,
                        "unknown_facility_id",
                        IssueSeverity.HIGH,
                        "facility_id",
                        facility_id,
                        "Every non-facility row must reference a facility in facilities.csv.",
                        "Add the facility to facilities.csv or correct the facility_id.",
                        facility_id=facility_id,
                        reporting_month=_optional_date(row.get("reporting_month")),
                    )
                )
    return issues


def _check_missingness(manifest: UploadBatchManifest) -> list[DataQualityIssue]:
    checks = {
        DatasetKind.CLINICAL_NEONATAL: CLINICAL_REQUIRED_COLUMNS,
        DatasetKind.FACILITIES: FACILITY_REQUIRED_COLUMNS,
        DatasetKind.OPERATIONS: OPERATIONS_REQUIRED_COLUMNS,
    }
    issues: list[DataQualityIssue] = []

    for kind, columns in checks.items():
        dataset = manifest.datasets[kind]
        upload = manifest.uploads[kind]
        for row_number, row in _iter_rows(dataset.frame):
            for column in columns:
                if _is_missing(row.get(column)):
                    severity = IssueSeverity.HIGH if column in {"facility_id", "reporting_month"} else IssueSeverity.MEDIUM
                    issues.append(
                        _issue(
                            manifest,
                            kind,
                            upload.upload_id,
                            row_number,
                            "missing_value",
                            severity,
                            column,
                            None,
                            f"{column} must be present for reliable bulletin generation.",
                            "Fill the missing value in the source file or document an override.",
                            facility_id=_optional_str(row.get("facility_id")),
                            reporting_month=_optional_date(row.get("reporting_month")),
                        )
                    )
    return issues


def _check_duplicate_clinical_months(manifest: UploadBatchManifest) -> list[DataQualityIssue]:
    dataset = manifest.datasets[DatasetKind.CLINICAL_NEONATAL]
    upload = manifest.uploads[DatasetKind.CLINICAL_NEONATAL]
    frame = dataset.frame
    issues: list[DataQualityIssue] = []

    for (facility_id, reporting_month), group in frame.groupby(["facility_id", "reporting_month"]):
        if len(group) <= 1:
            continue
        unique_reports = group.drop_duplicates(list(CLINICAL_REPORT_VALUE_COLUMNS))
        is_exact_duplicate = len(unique_reports) == 1
        issue_type = (
            "duplicate_facility_month"
            if is_exact_duplicate
            else "conflicting_facility_month_submission"
        )
        severity = IssueSeverity.MEDIUM if is_exact_duplicate else IssueSeverity.HIGH
        expected_rule = (
            "Repeated rows with the same facility, month, and clinical values should resolve to one final report."
            if is_exact_duplicate
            else "A facility-month can have only one final clinical submission for a given data set/form."
        )
        suggested_action = (
            "Keep one copy of the repeated facility-month report before final publication."
            if is_exact_duplicate
            else "Reconcile the conflicting facility-month submissions and select the final approved report."
        )
        for row_number, row in _iter_rows(group):
            issues.append(
                _issue(
                    manifest,
                    DatasetKind.CLINICAL_NEONATAL,
                    upload.upload_id,
                    row_number,
                    issue_type,
                    severity,
                    "facility_id,reporting_month,clinical_values",
                    f"{facility_id} {reporting_month}",
                    expected_rule,
                    suggested_action,
                    facility_id=_optional_str(row.get("facility_id")),
                    reporting_month=_optional_date(row.get("reporting_month")),
                )
            )
    return issues


def _check_logical_consistency(manifest: UploadBatchManifest) -> list[DataQualityIssue]:
    clinical = manifest.datasets[DatasetKind.CLINICAL_NEONATAL]
    facilities = manifest.datasets[DatasetKind.FACILITIES]
    issues: list[DataQualityIssue] = []
    clinical_upload = manifest.uploads[DatasetKind.CLINICAL_NEONATAL]
    facility_upload = manifest.uploads[DatasetKind.FACILITIES]

    for row_number, row in _iter_rows(clinical.frame):
        total_deaths = _number(row.get("neonatal_deaths_0_7d")) + _number(row.get("neonatal_deaths_8_28d"))
        live_births = _number(row.get("live_births"))
        total_deliveries = _number(row.get("total_deliveries"))
        stillbirths = _number(row.get("stillbirths"))
        preterm = _number(row.get("preterm_births_28_32w")) + _number(row.get("preterm_births_32_37w"))
        cause_deaths = sum(
            _number(row.get(column))
            for column in (
                "death_birth_asphyxia",
                "death_prematurity",
                "death_sepsis",
                "death_congenital",
                "death_other",
            )
        )

        checks = (
            (
                total_deaths > live_births,
                "neonatal_deaths_exceed_live_births",
                "neonatal_deaths_0_7d,neonatal_deaths_8_28d,live_births",
                f"{total_deaths} deaths / {live_births} live births",
                IssueSeverity.HIGH,
                "Total neonatal deaths should not exceed live births.",
            ),
            (
                stillbirths > total_deliveries,
                "stillbirths_exceed_deliveries",
                "stillbirths,total_deliveries",
                f"{stillbirths} stillbirths / {total_deliveries} deliveries",
                IssueSeverity.HIGH,
                "Stillbirths should not exceed total deliveries.",
            ),
            (
                preterm > live_births,
                "preterm_births_exceed_live_births",
                "preterm_births_28_32w,preterm_births_32_37w,live_births",
                f"{preterm} preterm births / {live_births} live births",
                IssueSeverity.HIGH,
                "Preterm births should not exceed live births.",
            ),
            (
                cause_deaths != total_deaths,
                "cause_deaths_do_not_sum_to_total_deaths",
                "death_*",
                f"{cause_deaths} cause deaths / {total_deaths} total deaths",
                IssueSeverity.MEDIUM,
                "Cause-specific neonatal deaths should sum to early plus late neonatal deaths.",
            ),
        )

        for failed, issue_type, column, observed, severity, expected in checks:
            if failed:
                issues.append(
                    _issue(
                        manifest,
                        DatasetKind.CLINICAL_NEONATAL,
                        clinical_upload.upload_id,
                        row_number,
                        issue_type,
                        severity,
                        column,
                        observed,
                        expected,
                        "Review and correct the clinical source row or document an override.",
                        facility_id=_optional_str(row.get("facility_id")),
                        reporting_month=_optional_date(row.get("reporting_month")),
                    )
                )

    for row_number, row in _iter_rows(facilities.frame):
        functional = _number(row.get("incubators_functional"))
        total = _number(row.get("incubators_total"))
        if functional > total:
            issues.append(
                _issue(
                    manifest,
                    DatasetKind.FACILITIES,
                    facility_upload.upload_id,
                    row_number,
                    "functional_equipment_exceeds_total",
                    IssueSeverity.HIGH,
                    "incubators_functional,incubators_total",
                    f"{functional} functional / {total} total",
                    "Functional incubators should not exceed total incubators.",
                    "Correct equipment totals in facilities.csv or document an override.",
                    facility_id=_optional_str(row.get("facility_id")),
                )
            )
    return issues


def _check_percentage_ranges(manifest: UploadBatchManifest) -> list[DataQualityIssue]:
    issues: list[DataQualityIssue] = []
    for kind, columns in PERCENT_COLUMNS_BY_KIND.items():
        dataset = manifest.datasets[kind]
        upload = manifest.uploads[kind]
        for row_number, row in _iter_rows(dataset.frame):
            for column in columns:
                value = row.get(column)
                if not _is_missing(value) and not 0 <= float(value) <= 1:
                    issues.append(
                        _issue(
                            manifest,
                            kind,
                            upload.upload_id,
                            row_number,
                            "percentage_out_of_range",
                            IssueSeverity.HIGH,
                            column,
                            str(value),
                            "Normalized percentage values must be fractions between 0 and 1.",
                            "Correct the percentage in the source file.",
                            facility_id=_optional_str(row.get("facility_id")),
                        )
                    )
    return issues


def _check_static_snapshot_dates(manifest: UploadBatchManifest) -> list[DataQualityIssue]:
    """Flag static facility context rows dated after the clinical reporting period."""

    period_end = manifest.reporting_period_end
    if period_end is None:
        return []

    issues: list[DataQualityIssue] = []
    for kind, columns in STATIC_SNAPSHOT_DATE_COLUMNS_BY_KIND.items():
        dataset = manifest.datasets[kind]
        upload = manifest.uploads[kind]
        for row_number, row in _iter_rows(dataset.frame):
            for column in columns:
                value = _optional_date(row.get(column))
                if value is None or value <= period_end:
                    continue
                issues.append(
                    _issue(
                        manifest,
                        kind,
                        upload.upload_id,
                        row_number,
                        "future_static_snapshot_date",
                        IssueSeverity.MEDIUM,
                        column,
                        value.isoformat(),
                        "Static facility context dates should not be after the clinical bulletin end date when used for period interpretation.",
                        "Confirm whether the static file is a current snapshot. If so, interpret readiness and governance scores as latest-available context, not strictly period-valid values.",
                        facility_id=_optional_str(row.get("facility_id")),
                    )
                )
    return issues


def _check_reporting_quality(manifest: UploadBatchManifest) -> list[DataQualityIssue]:
    dataset = manifest.datasets[DatasetKind.GOVERNANCE]
    upload = manifest.uploads[DatasetKind.GOVERNANCE]
    issues: list[DataQualityIssue] = []

    for row_number, row in _iter_rows(dataset.frame):
        completeness = row.get("hmis_reporting_completeness")
        if _is_missing(completeness):
            continue
        value = float(completeness)
        if value < 0.80:
            severity = IssueSeverity.HIGH if value < 0.60 else IssueSeverity.MEDIUM
            issues.append(
                _issue(
                    manifest,
                    DatasetKind.GOVERNANCE,
                    upload.upload_id,
                    row_number,
                    "low_reporting_completeness",
                    severity,
                    "hmis_reporting_completeness",
                    f"{value:.2f}",
                    "HMIS reporting completeness should be at least 80% for bulletin confidence.",
                    "Review reporting completeness with the facility before final publication.",
                    facility_id=_optional_str(row.get("facility_id")),
                )
            )
    return issues


def _check_outliers(manifest: UploadBatchManifest) -> list[DataQualityIssue]:
    dataset = manifest.datasets[DatasetKind.CLINICAL_NEONATAL]
    upload = manifest.uploads[DatasetKind.CLINICAL_NEONATAL]
    frame = dataset.frame.sort_values(["facility_id", "reporting_month"])
    issues: list[DataQualityIssue] = []

    for facility_id, facility_frame in frame.groupby("facility_id"):
        previous_deliveries: Optional[float] = None
        previous_deaths: Optional[float] = None
        zero_death_streak = 0

        for row_number, row in _iter_rows(facility_frame):
            deliveries = _number(row.get("total_deliveries"))
            deaths = _number(row.get("neonatal_deaths_0_7d")) + _number(row.get("neonatal_deaths_8_28d"))

            if previous_deliveries and previous_deliveries >= 20:
                change = (deliveries - previous_deliveries) / previous_deliveries
                if change <= -0.90:
                    issues.append(
                        _issue(
                            manifest,
                            DatasetKind.CLINICAL_NEONATAL,
                            upload.upload_id,
                            row_number,
                            "sharp_drop_in_deliveries",
                            IssueSeverity.MEDIUM,
                            "total_deliveries",
                            f"{previous_deliveries:g} to {deliveries:g}",
                            "Deliveries should not drop by 90% or more without review.",
                            "Confirm whether this reflects a true service disruption or a reporting error.",
                            facility_id=str(facility_id),
                            reporting_month=_optional_date(row.get("reporting_month")),
                        )
                    )

            if previous_deaths is not None and previous_deaths >= 1 and deaths >= max(10, previous_deaths * 3):
                issues.append(
                    _issue(
                        manifest,
                        DatasetKind.CLINICAL_NEONATAL,
                        upload.upload_id,
                        row_number,
                        "sharp_spike_in_neonatal_deaths",
                        IssueSeverity.MEDIUM,
                        "neonatal_deaths_0_7d,neonatal_deaths_8_28d",
                        f"{previous_deaths:g} to {deaths:g}",
                        "Large mortality spikes should be reviewed before interpretation.",
                        "Confirm whether the spike reflects a true event or a data entry issue.",
                        facility_id=str(facility_id),
                        reporting_month=_optional_date(row.get("reporting_month")),
                    )
                )

            if deaths == 0:
                zero_death_streak += 1
            else:
                zero_death_streak = 0
            if zero_death_streak >= 6 and deliveries >= 50:
                issues.append(
                    _issue(
                        manifest,
                        DatasetKind.CLINICAL_NEONATAL,
                        upload.upload_id,
                        row_number,
                        "extended_zero_death_reporting",
                        IssueSeverity.LOW,
                        "neonatal_deaths_0_7d,neonatal_deaths_8_28d",
                        f"{zero_death_streak} consecutive months with zero deaths",
                        "Extended zero mortality after meaningful delivery volume should be reviewed.",
                        "Confirm zero-death reporting with the facility if prior mortality was expected.",
                        facility_id=str(facility_id),
                        reporting_month=_optional_date(row.get("reporting_month")),
                    )
                )

            previous_deliveries = deliveries
            previous_deaths = deaths

    return issues


def _issue(
    manifest: UploadBatchManifest,
    kind: DatasetKind,
    upload_id: object,
    row_number: int,
    issue_type: str,
    severity: IssueSeverity,
    affected_column: Optional[str],
    observed_value: Optional[str],
    expected_rule: str,
    suggested_action: str,
    facility_id: Optional[str] = None,
    reporting_month: Optional[date] = None,
) -> DataQualityIssue:
    return DataQualityIssue(
        tenant_id=manifest.tenant_id,
        country_code=manifest.country_code,
        dataset_kind=kind.value,
        issue_type=issue_type,
        severity=severity,
        affected_column=affected_column,
        observed_value=observed_value,
        expected_rule=expected_rule,
        suggested_action=suggested_action,
        source_upload_id=upload_id,  # type: ignore[arg-type]
        source_row_number=row_number,
        facility_id=facility_id,
        reporting_month=reporting_month,
    )


def _iter_rows(frame: pd.DataFrame) -> Iterable[tuple[int, pd.Series]]:
    for index, row in frame.iterrows():
        yield int(index) + 1, row


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except TypeError:
        return False


def _number(value: object) -> float:
    if _is_missing(value):
        return 0.0
    return float(value)  # type: ignore[arg-type]


def _optional_str(value: object) -> Optional[str]:
    if _is_missing(value):
        return None
    return str(value)


def _optional_date(value: object) -> Optional[date]:
    if _is_missing(value):
        return None
    if isinstance(value, date):
        return value
    return None
