"""Generate bulletin artifacts from report-ready metrics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sand_bulletin.analytics import AnalyticsBlockedError, build_report_ready_metrics
from sand_bulletin.data_quality import (
    AnalysisMode,
    resolution_frame,
    resolve_clinical_submissions,
    validate_upload_batch,
)
from sand_bulletin.dashboard.data import issue_frame, metric_frame
from sand_bulletin.ingestion.batches import UploadBatchManifest
from sand_bulletin.ingestion.datasets import DatasetKind
from sand_bulletin.narrative import build_metric_package, generate_narrative
from sand_bulletin.reports.html import render_bulletin_html
from sand_bulletin.reports.workbook import write_excel_workbook


@dataclass(frozen=True)
class GeneratedReports:
    """Paths and status for generated bulletin artifacts."""

    run_id: str
    output_dir: Path
    html_path: Path
    excel_path: Path
    pdf_path: Path | None
    metrics_count: int
    issues_count: int
    pdf_status: str


def generate_reports(
    manifest: UploadBatchManifest,
    output_root: Path,
    allow_high_severity: bool = False,
    openai_api_key: str | None = None,
    openai_model: str = "gpt-5.2",
    use_openai: bool = True,
    analysis_mode: AnalysisMode | str = AnalysisMode.VALIDATED,
) -> GeneratedReports:
    """Generate HTML, Excel, and optional PDF outputs for one bulletin run."""

    summary = validate_upload_batch(manifest)
    mode = AnalysisMode(analysis_mode)
    resolution = resolve_clinical_submissions(
        manifest.datasets[DatasetKind.CLINICAL_NEONATAL].frame,
        mode,
    )
    metrics = build_report_ready_metrics(
        manifest,
        summary,
        allow_high_severity=allow_high_severity,
        analysis_mode=mode,
    )
    if not metrics:
        raise AnalyticsBlockedError("No report-ready metrics were generated.")

    run_id = str(uuid4())
    period = f"{metrics[0].reporting_period_start}_{metrics[0].reporting_period_end}"
    output_dir = output_root / f"bulletin_{period}_{run_id[:8]}"
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics_df = metric_frame(metrics)
    issues_df = issue_frame(summary)
    package = build_metric_package(metrics_df, summary)
    narrative = generate_narrative(
        package,
        api_key=openai_api_key,
        model=openai_model,
        use_openai=use_openai,
    )

    resolution_df = resolution_frame(resolution)
    html = render_bulletin_html(
        metrics_df,
        issues_df,
        manifest,
        run_id,
        narrative=narrative,
        resolution=resolution_df,
        analysis_mode=mode,
    )
    html_path = output_dir / "bulletin.html"
    html_path.write_text(html, encoding="utf-8")

    excel_path = output_dir / "bulletin_workbook.xlsx"
    write_excel_workbook(excel_path, metrics_df, issues_df, manifest, resolution_df)

    pdf_path, pdf_status = _write_pdf_if_available(html, output_dir / "bulletin.pdf")

    return GeneratedReports(
        run_id=run_id,
        output_dir=output_dir,
        html_path=html_path,
        excel_path=excel_path,
        pdf_path=pdf_path,
        metrics_count=len(metrics),
        issues_count=summary.issue_count,
        pdf_status=pdf_status,
    )


def _write_pdf_if_available(html: str, pdf_path: Path) -> tuple[Path | None, str]:
    try:
        from weasyprint import HTML
    except ImportError:
        return None, "skipped: WeasyPrint is not installed"
    except OSError:
        return None, "skipped: WeasyPrint system dependencies are not available"

    try:
        HTML(string=html, base_url=str(pdf_path.parent)).write_pdf(pdf_path)
    except OSError:
        return None, "skipped: WeasyPrint system dependencies are not available"
    return pdf_path, "generated"
