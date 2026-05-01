"""AI-assisted narrative generation."""

from sand_bulletin.narrative.generator import generate_narrative
from sand_bulletin.narrative.models import MetricPackage, NarrativeSummary
from sand_bulletin.narrative.package import build_metric_package

__all__ = [
    "MetricPackage",
    "NarrativeSummary",
    "build_metric_package",
    "generate_narrative",
]
