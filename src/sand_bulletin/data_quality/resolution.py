"""Clinical facility-month submission resolution for analytics modes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class AnalysisMode(str, Enum):
    """How analytics should handle repeated facility-month clinical submissions."""

    VALIDATED = "validated"
    BEST_EFFORT = "best_effort"
    RAW = "raw"


@dataclass(frozen=True)
class ResolutionDecision:
    """Audit record for one repeated facility-month group."""

    facility_id: str
    reporting_month: object
    selected_row_number: int | None
    rejected_row_numbers: list[int]
    resolution_method: str
    confidence_level: str
    reason: str


@dataclass(frozen=True)
class ResolutionResult:
    """Resolved clinical frame plus an audit summary."""

    frame: pd.DataFrame
    decisions: list[ResolutionDecision]
    mode: AnalysisMode

    @property
    def exact_duplicate_groups(self) -> int:
        return sum(1 for decision in self.decisions if decision.resolution_method == "exact_duplicate")

    @property
    def selected_conflict_groups(self) -> int:
        return sum(1 for decision in self.decisions if decision.selected_row_number is not None and decision.resolution_method != "exact_duplicate")

    @property
    def unresolved_conflict_groups(self) -> int:
        return sum(1 for decision in self.decisions if decision.selected_row_number is None)

    @property
    def excluded_rows(self) -> int:
        return sum(len(decision.rejected_row_numbers) for decision in self.decisions)

    def trace_payload(self) -> dict[str, object]:
        """Return compact resolution metadata for report trace payloads."""

        return {
            "analysis_mode": self.mode.value,
            "resolution_decisions": len(self.decisions),
            "exact_duplicate_groups": self.exact_duplicate_groups,
            "selected_conflict_groups": self.selected_conflict_groups,
            "unresolved_conflict_groups": self.unresolved_conflict_groups,
            "excluded_rows": self.excluded_rows,
        }


CLINICAL_VALUE_COLUMNS = [
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
]


def resolve_clinical_submissions(
    clinical: pd.DataFrame,
    mode: AnalysisMode | str = AnalysisMode.VALIDATED,
) -> ResolutionResult:
    """Resolve repeated clinical facility-month submissions according to an analysis mode."""

    analysis_mode = AnalysisMode(mode)
    if analysis_mode == AnalysisMode.RAW:
        return ResolutionResult(frame=clinical.copy(), decisions=[], mode=analysis_mode)

    keep_indices: set[int] = set(clinical.index)
    decisions: list[ResolutionDecision] = []
    duplicate_groups = clinical.groupby(["facility_id", "reporting_month"], dropna=False)
    for (facility_id, reporting_month), group in duplicate_groups:
        if len(group) <= 1:
            continue
        row_numbers = [int(index) + 1 for index in group.index]
        value_columns = [column for column in CLINICAL_VALUE_COLUMNS if column in group]
        unique_reports = group.drop_duplicates(value_columns)
        if len(unique_reports) == 1:
            selected_index = int(group.index[0])
            rejected = [int(index) + 1 for index in group.index[1:]]
            keep_indices.difference_update(int(index) for index in group.index[1:])
            decisions.append(
                ResolutionDecision(
                    facility_id=str(facility_id),
                    reporting_month=reporting_month,
                    selected_row_number=selected_index + 1,
                    rejected_row_numbers=rejected,
                    resolution_method="exact_duplicate",
                    confidence_level="High",
                    reason="Rows contain identical clinical values; one copy retained.",
                )
            )
            continue

        if analysis_mode == AnalysisMode.VALIDATED:
            keep_indices.difference_update(int(index) for index in group.index)
            decisions.append(
                ResolutionDecision(
                    facility_id=str(facility_id),
                    reporting_month=reporting_month,
                    selected_row_number=None,
                    rejected_row_numbers=row_numbers,
                    resolution_method="excluded_conflict",
                    confidence_level="Unresolved",
                    reason="Conflicting submissions excluded because no final approved row is identifiable.",
                )
            )
            continue

        selected_index, confidence, reason = _best_effort_selection(clinical, group)
        if selected_index is None or confidence in {"Low", "Unresolved"}:
            keep_indices.difference_update(int(index) for index in group.index)
            decisions.append(
                ResolutionDecision(
                    facility_id=str(facility_id),
                    reporting_month=reporting_month,
                    selected_row_number=None,
                    rejected_row_numbers=row_numbers,
                    resolution_method="unresolved_best_effort",
                    confidence_level="Unresolved",
                    reason=reason,
                )
            )
        else:
            keep_indices.difference_update(int(index) for index in group.index if int(index) != selected_index)
            decisions.append(
                ResolutionDecision(
                    facility_id=str(facility_id),
                    reporting_month=reporting_month,
                    selected_row_number=selected_index + 1,
                    rejected_row_numbers=[int(index) + 1 for index in group.index if int(index) != selected_index],
                    resolution_method="best_effort_quality_score",
                    confidence_level=confidence,
                    reason=reason,
                )
            )

    resolved = clinical.loc[sorted(keep_indices)].copy().reset_index(drop=True)
    return ResolutionResult(frame=resolved, decisions=decisions, mode=analysis_mode)


def resolution_frame(result: ResolutionResult) -> pd.DataFrame:
    """Convert resolution decisions to a workbook/dashboard frame."""

    return pd.DataFrame(
        [
            {
                "facility_id": decision.facility_id,
                "reporting_month": decision.reporting_month,
                "selected_row": decision.selected_row_number,
                "rejected_rows": ", ".join(str(row) for row in decision.rejected_row_numbers),
                "resolution_method": decision.resolution_method,
                "confidence_level": decision.confidence_level,
                "reason": decision.reason,
            }
            for decision in result.decisions
        ]
    )


def _best_effort_selection(clinical: pd.DataFrame, group: pd.DataFrame) -> tuple[int | None, str, str]:
    scores = {
        int(index): _row_score(clinical, group, row)
        for index, row in group.iterrows()
    }
    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_index, best_score = sorted_scores[0]
    second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else best_score
    best_violations = _hard_violations(group.loc[best_index])
    other_violations = min(
        _hard_violations(row)
        for index, row in group.iterrows()
        if int(index) != best_index
    )
    if best_violations < other_violations:
        return best_index, "High", "Selected row has fewer hard health-data constraint violations."
    if best_violations:
        return None, "Unresolved", "All candidate rows violate hard health-data constraints."
    gap = best_score - second_score
    if gap >= 2.0:
        return best_index, "Medium", "Selected row aligns better with facility history and peer ratios."
    return None, "Low", "Both submissions are plausible; statistical separation is too weak to choose safely."


def _row_score(clinical: pd.DataFrame, group: pd.DataFrame, row: pd.Series) -> float:
    hard_penalty = _hard_violations(row) * 100.0
    facility_history = clinical[
        (clinical["facility_id"] == row["facility_id"])
        & (~clinical.index.isin(group.index))
    ]
    peer_history = clinical[
        (clinical["reporting_month"] == row["reporting_month"])
        & (~clinical.index.isin(group.index))
    ]
    return 20.0 - hard_penalty - _distance_penalty(row, facility_history) - (_distance_penalty(row, peer_history) * 0.5)


def _hard_violations(row: pd.Series) -> int:
    deaths = _number(row.get("neonatal_deaths_0_7d")) + _number(row.get("neonatal_deaths_8_28d"))
    live_births = _number(row.get("live_births"))
    deliveries = _number(row.get("total_deliveries"))
    stillbirths = _number(row.get("stillbirths"))
    preterm = _number(row.get("preterm_births_28_32w")) + _number(row.get("preterm_births_32_37w"))
    low_birth_weight = _number(row.get("birth_weight_less_2500g"))
    cause_deaths = sum(_number(row.get(column)) for column in (
        "death_birth_asphyxia",
        "death_prematurity",
        "death_sepsis",
        "death_congenital",
        "death_other",
    ))
    violations = 0
    violations += int(live_births + stillbirths > deliveries * 1.10)
    violations += int(deaths > live_births)
    violations += int(preterm > live_births)
    violations += int(low_birth_weight > live_births)
    violations += int(abs(cause_deaths - deaths) > max(2.0, deaths * 0.25))
    return violations


def _distance_penalty(row: pd.Series, reference: pd.DataFrame) -> float:
    if reference.empty:
        return 0.0
    penalties = [
        _robust_distance(_number(row.get("total_deliveries")), reference["total_deliveries"]),
        _robust_distance(_rate(row, "neonatal_deaths"), _reference_rate(reference, "neonatal_deaths")),
        _robust_distance(_rate(row, "stillbirths"), _reference_rate(reference, "stillbirths")),
        _robust_distance(_rate(row, "preterm"), _reference_rate(reference, "preterm")),
        _robust_distance(_rate(row, "birth_weight_less_2500g"), _reference_rate(reference, "birth_weight_less_2500g")),
    ]
    return sum(min(penalty, 5.0) for penalty in penalties)


def _robust_distance(value: float, reference: pd.Series) -> float:
    clean = pd.to_numeric(reference, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    median = float(clean.median())
    mad = float((clean - median).abs().median())
    scale = max(mad, 1.0)
    return abs(value - median) / scale


def _reference_rate(frame: pd.DataFrame, kind: str) -> pd.Series:
    live_births = frame["live_births"].replace(0, pd.NA)
    if kind == "neonatal_deaths":
        return (frame["neonatal_deaths_0_7d"] + frame["neonatal_deaths_8_28d"]) / live_births
    if kind == "stillbirths":
        return frame["stillbirths"] / frame["total_deliveries"].replace(0, pd.NA)
    if kind == "preterm":
        return (frame["preterm_births_28_32w"] + frame["preterm_births_32_37w"]) / live_births
    return frame[kind] / live_births


def _rate(row: pd.Series, kind: str) -> float:
    live_births = max(_number(row.get("live_births")), 1.0)
    if kind == "neonatal_deaths":
        return (_number(row.get("neonatal_deaths_0_7d")) + _number(row.get("neonatal_deaths_8_28d"))) / live_births
    if kind == "stillbirths":
        return _number(row.get("stillbirths")) / max(_number(row.get("total_deliveries")), 1.0)
    if kind == "preterm":
        return (_number(row.get("preterm_births_28_32w")) + _number(row.get("preterm_births_32_37w"))) / live_births
    return _number(row.get(kind)) / live_births


def _number(value: object) -> float:
    if value is None or pd.isna(value):
        return 0.0
    return float(value)
