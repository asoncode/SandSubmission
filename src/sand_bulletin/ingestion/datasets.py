"""Known MVP dataset contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class DatasetKind(str, Enum):
    """Known input file categories for the MVP."""

    CLINICAL_NEONATAL = "clinical_neonatal"
    FACILITIES = "facilities"
    GOVERNANCE = "governance"
    HEALTHCARE_WORKERS = "healthcare_workers"
    OPERATIONS = "operations"


@dataclass(frozen=True)
class DatasetSpec:
    """Column contract and type hints for one source dataset."""

    kind: DatasetKind
    filename: str
    required_columns: tuple[str, ...]
    integer_columns: tuple[str, ...] = ()
    float_columns: tuple[str, ...] = ()
    percent_columns: tuple[str, ...] = ()
    boolean_columns: tuple[str, ...] = ()
    availability_columns: tuple[str, ...] = ()
    frequency_columns: tuple[str, ...] = ()
    date_columns: tuple[str, ...] = ()
    month_columns: tuple[str, ...] = ()


DATASET_SPECS: dict[DatasetKind, DatasetSpec] = {
    DatasetKind.CLINICAL_NEONATAL: DatasetSpec(
        kind=DatasetKind.CLINICAL_NEONATAL,
        filename="clinical_neonatal.csv",
        required_columns=(
            "facility_id",
            "reporting_month",
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
        ),
        integer_columns=(
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
            "preterm_births_28_32w",
            "preterm_births_32_37w",
            "apgar_less_7_at_5min",
            "birth_weight_less_2500g",
        ),
        float_columns=("avg_gestational_age",),
        month_columns=("reporting_month",),
    ),
    DatasetKind.FACILITIES: DatasetSpec(
        kind=DatasetKind.FACILITIES,
        filename="facilities.csv",
        required_columns=(
            "facility_id",
            "facility_name",
            "district",
            "province",
            "tier_level",
            "gps_lat",
            "gps_lon",
            "nicu_available",
            "nicu_beds",
            "incubators_functional",
            "incubators_total",
            "radiant_warmers",
            "phototherapy_units",
            "cpap_machines",
            "resuscitation_tables",
            "kangaroo_care_space",
            "electricity_reliable",
            "backup_generator",
        ),
        integer_columns=(
            "nicu_beds",
            "incubators_functional",
            "incubators_total",
            "radiant_warmers",
            "phototherapy_units",
            "cpap_machines",
            "resuscitation_tables",
        ),
        float_columns=("gps_lat", "gps_lon"),
        boolean_columns=("backup_generator",),
        availability_columns=("nicu_available", "kangaroo_care_space", "electricity_reliable"),
    ),
    DatasetKind.GOVERNANCE: DatasetSpec(
        kind=DatasetKind.GOVERNANCE,
        filename="governance.csv",
        required_columns=(
            "facility_id",
            "newborn_protocol_exists",
            "protocol_last_updated",
            "death_audits_conducted_pct",
            "staff_trained_on_protocol_pct",
            "quality_improvement_active",
            "supervision_visits_quarterly",
            "hmis_reporting_completeness",
            "bag_mask_ventilation_competency",
            "thermal_care_protocol_compliance",
            "infection_prevention_score",
        ),
        integer_columns=("supervision_visits_quarterly",),
        percent_columns=(
            "death_audits_conducted_pct",
            "staff_trained_on_protocol_pct",
            "hmis_reporting_completeness",
            "bag_mask_ventilation_competency",
            "thermal_care_protocol_compliance",
            "infection_prevention_score",
        ),
        boolean_columns=("newborn_protocol_exists", "quality_improvement_active"),
        date_columns=("protocol_last_updated",),
    ),
    DatasetKind.HEALTHCARE_WORKERS: DatasetSpec(
        kind=DatasetKind.HEALTHCARE_WORKERS,
        filename="healthcare_workers.csv",
        required_columns=(
            "facility_id",
            "total_nurses",
            "neonatal_trained_nurses",
            "midwives",
            "obstetricians",
            "pediatricians",
            "neonatologists",
            "anesthetists",
            "last_neonatal_training_date",
            "staff_per_delivery_2024",
            "night_shift_coverage",
        ),
        integer_columns=(
            "total_nurses",
            "neonatal_trained_nurses",
            "midwives",
            "obstetricians",
            "pediatricians",
            "neonatologists",
            "anesthetists",
        ),
        float_columns=("staff_per_delivery_2024",),
        availability_columns=("night_shift_coverage",),
        date_columns=("last_neonatal_training_date",),
    ),
    DatasetKind.OPERATIONS: DatasetSpec(
        kind=DatasetKind.OPERATIONS,
        filename="operations.csv",
        required_columns=(
            "facility_id",
            "avg_referral_time_hrs",
            "referrals_out_monthly",
            "referrals_in_monthly",
            "oxygen_cylinders_available",
            "oxygen_concentrators",
            "oxygen_plant",
            "ambulance_available",
            "kangaroo_care_practiced",
            "essential_drugs_stockouts_days",
            "antibiotics_available",
            "surfactant_available",
            "referral_feedback_rate",
        ),
        integer_columns=(
            "referrals_out_monthly",
            "referrals_in_monthly",
            "oxygen_cylinders_available",
            "oxygen_concentrators",
            "essential_drugs_stockouts_days",
        ),
        float_columns=("avg_referral_time_hrs",),
        percent_columns=("referral_feedback_rate",),
        boolean_columns=("oxygen_plant", "ambulance_available", "surfactant_available"),
        availability_columns=("kangaroo_care_practiced",),
        frequency_columns=("antibiotics_available",),
    ),
}


def get_dataset_spec(kind: DatasetKind) -> DatasetSpec:
    """Return the column contract for a known dataset."""

    return DATASET_SPECS[kind]


def infer_dataset_kind(path: Path) -> DatasetKind:
    """Infer a dataset kind from a known MVP filename."""

    normalized_name = path.name.lower()
    for spec in DATASET_SPECS.values():
        if spec.filename == normalized_name:
            return spec.kind
    raise ValueError(f"Unknown dataset filename: {path.name}")
