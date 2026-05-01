"""Command-line utilities for local ingestion checks."""

from __future__ import annotations

import argparse
from pathlib import Path

from sand_bulletin.analytics import AnalyticsBlockedError, build_report_ready_metrics
from sand_bulletin.config import get_settings
from sand_bulletin.data_quality import AnalysisMode, validate_upload_batch
from sand_bulletin.dashboard.data import metric_frame
from sand_bulletin.ingestion import build_upload_batch_manifest, load_mvp_directory
from sand_bulletin.narrative import build_metric_package, generate_narrative
from sand_bulletin.nowcasting import NowcastingBlockedError, build_nowcast_metrics


def main() -> None:
    """Run local ingestion utilities."""

    parser = argparse.ArgumentParser(prog="sand-bulletin")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect-data")
    inspect_parser.add_argument("--data-dir", type=Path, default=None)
    inspect_parser.add_argument("--tenant-id", type=str, default=None)
    inspect_parser.add_argument("--country-code", type=str, default=None)

    load_parser = subparsers.add_parser("load-data")
    load_parser.add_argument("--data-dir", type=Path, default=None)
    load_parser.add_argument("--tenant-id", type=str, default=None)
    load_parser.add_argument("--country-code", type=str, default=None)
    load_parser.add_argument("--database-url", type=str, default=None)
    load_parser.add_argument("--skip-validation", action="store_true")
    load_parser.add_argument("--allow-high-severity", action="store_true")

    validate_parser = subparsers.add_parser("validate-data")
    validate_parser.add_argument("--data-dir", type=Path, default=None)
    validate_parser.add_argument("--tenant-id", type=str, default=None)
    validate_parser.add_argument("--country-code", type=str, default=None)
    validate_parser.add_argument("--limit", type=int, default=20)

    metrics_parser = subparsers.add_parser("build-metrics")
    metrics_parser.add_argument("--data-dir", type=Path, default=None)
    metrics_parser.add_argument("--tenant-id", type=str, default=None)
    metrics_parser.add_argument("--country-code", type=str, default=None)
    metrics_parser.add_argument("--allow-high-severity", action="store_true")
    metrics_parser.add_argument("--analysis-mode", choices=[mode.value for mode in AnalysisMode], default=AnalysisMode.VALIDATED.value)
    metrics_parser.add_argument("--database-url", type=str, default=None)
    metrics_parser.add_argument("--persist", action="store_true")
    metrics_parser.add_argument("--limit", type=int, default=20)

    report_parser = subparsers.add_parser("generate-reports")
    report_parser.add_argument("--data-dir", type=Path, default=None)
    report_parser.add_argument("--tenant-id", type=str, default=None)
    report_parser.add_argument("--country-code", type=str, default=None)
    report_parser.add_argument("--output-dir", type=Path, default=None)
    report_parser.add_argument("--allow-high-severity", action="store_true")
    report_parser.add_argument("--analysis-mode", choices=[mode.value for mode in AnalysisMode], default=AnalysisMode.VALIDATED.value)
    report_parser.add_argument("--no-openai", action="store_true")

    narrative_parser = subparsers.add_parser("generate-narrative")
    narrative_parser.add_argument("--data-dir", type=Path, default=None)
    narrative_parser.add_argument("--tenant-id", type=str, default=None)
    narrative_parser.add_argument("--country-code", type=str, default=None)
    narrative_parser.add_argument("--allow-high-severity", action="store_true")
    narrative_parser.add_argument("--analysis-mode", choices=[mode.value for mode in AnalysisMode], default=AnalysisMode.VALIDATED.value)
    narrative_parser.add_argument("--no-openai", action="store_true")

    nowcast_parser = subparsers.add_parser("build-nowcasts")
    nowcast_parser.add_argument("--data-dir", type=Path, default=None)
    nowcast_parser.add_argument("--tenant-id", type=str, default=None)
    nowcast_parser.add_argument("--country-code", type=str, default=None)
    nowcast_parser.add_argument("--allow-high-severity", action="store_true")
    nowcast_parser.add_argument("--analysis-mode", choices=[mode.value for mode in AnalysisMode], default=AnalysisMode.VALIDATED.value)
    nowcast_parser.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()

    if args.command == "inspect-data":
        settings = get_settings()
        data_dir = args.data_dir or settings.data_dir
        tenant_id = args.tenant_id or settings.tenant_id
        country_code = args.country_code or settings.country_code
        manifest = build_upload_batch_manifest(data_dir, tenant_id, country_code)
        print(
            "batch: "
            f"{manifest.batch_id} tenant={manifest.tenant_id} country={manifest.country_code} "
            f"period={manifest.reporting_period_start}..{manifest.reporting_period_end}"
        )
        loaded = load_mvp_directory(data_dir)
        for kind, dataset in loaded.items():
            print(f"{kind.value}: {dataset.row_count} rows from {dataset.source_path}")
    elif args.command == "load-data":
        settings = get_settings()
        data_dir = args.data_dir or settings.data_dir
        tenant_id = args.tenant_id or settings.tenant_id
        country_code = args.country_code or settings.country_code
        database_url = args.database_url or settings.database_url

        from sand_bulletin.db.run_load import load_directory_to_database

        load_directory_to_database(
            database_url,
            data_dir,
            tenant_id,
            country_code,
            validate=not args.skip_validation,
            allow_high_severity=args.allow_high_severity,
        )
        print(f"loaded staged data from {data_dir} into {database_url} for {tenant_id}/{country_code}")
    elif args.command == "validate-data":
        settings = get_settings()
        data_dir = args.data_dir or settings.data_dir
        tenant_id = args.tenant_id or settings.tenant_id
        country_code = args.country_code or settings.country_code
        manifest = build_upload_batch_manifest(data_dir, tenant_id, country_code)
        summary = validate_upload_batch(manifest)

        print(
            "data quality: "
            f"{summary.issue_count} issues "
            f"({summary.high_count} high, {summary.medium_count} medium, {summary.low_count} low); "
            f"can_generate_report={summary.can_generate_report}"
        )
        for issue_type, count in sorted(summary.counts_by_type().items()):
            print(f"{issue_type}: {count}")

        for issue in summary.issues[: args.limit]:
            print(
                f"- {issue.severity.value} {issue.issue_type} "
                f"{issue.dataset_kind or 'dataset'} row={issue.source_row_number} "
                f"facility={issue.facility_id or '-'} month={issue.reporting_month or '-'} "
                f"column={issue.affected_column or '-'} observed={issue.observed_value or '-'}"
            )
    elif args.command == "build-metrics":
        settings = get_settings()
        data_dir = args.data_dir or settings.data_dir
        tenant_id = args.tenant_id or settings.tenant_id
        country_code = args.country_code or settings.country_code
        database_url = args.database_url or settings.database_url
        manifest = build_upload_batch_manifest(data_dir, tenant_id, country_code)
        summary = validate_upload_batch(manifest)
        try:
            metrics = build_report_ready_metrics(
                manifest,
                summary,
                allow_high_severity=args.allow_high_severity,
                analysis_mode=args.analysis_mode,
            )
        except AnalyticsBlockedError as exc:
            print(f"analytics blocked: {exc}")
            print("rerun with --allow-high-severity only after an explicit data quality override")
            return

        print(
            f"report_ready_metrics: {len(metrics)} records "
            f"period={metrics[0].reporting_period_start}..{metrics[0].reporting_period_end}"
        )
        by_level: dict[str, int] = {}
        for metric in metrics:
            by_level[metric.geography_level] = by_level.get(metric.geography_level, 0) + 1
        for level, count in sorted(by_level.items()):
            print(f"{level}: {count}")
        for metric in metrics[: args.limit]:
            print(
                f"- {metric.geography_level}:{metric.geography_id} "
                f"{metric.metric_name}={metric.metric_value} {metric.metric_unit or ''}"
            )
        if args.persist:
            import psycopg

            from sand_bulletin.db import insert_report_ready_metrics

            with psycopg.connect(database_url) as connection:
                insert_report_ready_metrics(connection, metrics)
            print(f"persisted {len(metrics)} report_ready_metrics rows")
    elif args.command == "generate-reports":
        settings = get_settings()
        data_dir = args.data_dir or settings.data_dir
        tenant_id = args.tenant_id or settings.tenant_id
        country_code = args.country_code or settings.country_code
        output_dir = args.output_dir or settings.output_dir
        manifest = build_upload_batch_manifest(data_dir, tenant_id, country_code)
        try:
            from sand_bulletin.reports import generate_reports

            generated = generate_reports(
                manifest,
                output_dir,
                allow_high_severity=args.allow_high_severity,
                openai_api_key=settings.openai_api_key,
                openai_model=settings.openai_model,
                use_openai=not args.no_openai,
                analysis_mode=args.analysis_mode,
            )
        except AnalyticsBlockedError as exc:
            print(f"report generation blocked: {exc}")
            print("rerun with --allow-high-severity only after an explicit data quality override")
            return
        print(f"run_id: {generated.run_id}")
        print(f"output_dir: {generated.output_dir}")
        print(f"html: {generated.html_path}")
        print(f"excel: {generated.excel_path}")
        print(f"pdf: {generated.pdf_path if generated.pdf_path else generated.pdf_status}")
        print(f"metrics: {generated.metrics_count}")
        print(f"issues: {generated.issues_count}")
    elif args.command == "generate-narrative":
        settings = get_settings()
        data_dir = args.data_dir or settings.data_dir
        tenant_id = args.tenant_id or settings.tenant_id
        country_code = args.country_code or settings.country_code
        manifest = build_upload_batch_manifest(data_dir, tenant_id, country_code)
        summary = validate_upload_batch(manifest)
        try:
            metrics = build_report_ready_metrics(
                manifest,
                summary,
                allow_high_severity=args.allow_high_severity,
                analysis_mode=args.analysis_mode,
            )
        except AnalyticsBlockedError as exc:
            print(f"narrative generation blocked: {exc}")
            print("rerun with --allow-high-severity only after an explicit data quality override")
            return
        package = build_metric_package(metric_frame(metrics), summary)
        narrative = generate_narrative(
            package,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            use_openai=not args.no_openai,
        )
        print(f"mode: {narrative.mode}")
        print(f"model: {narrative.model}")
        print(f"executive_summary: {narrative.executive_summary}")
        print("key_findings:")
        for finding in narrative.key_findings:
            print(f"- {finding}")
        print("recommendations:")
        for recommendation in narrative.recommendations:
            print(f"- {recommendation}")
    elif args.command == "build-nowcasts":
        settings = get_settings()
        data_dir = args.data_dir or settings.data_dir
        tenant_id = args.tenant_id or settings.tenant_id
        country_code = args.country_code or settings.country_code
        manifest = build_upload_batch_manifest(data_dir, tenant_id, country_code)
        summary = validate_upload_batch(manifest)
        try:
            metrics = build_nowcast_metrics(
                manifest,
                summary,
                allow_high_severity=args.allow_high_severity,
                analysis_mode=args.analysis_mode,
            )
        except NowcastingBlockedError as exc:
            print(f"nowcasting blocked: {exc}")
            print("rerun with --allow-high-severity only after an explicit data quality override")
            return
        print(f"nowcast_metrics: {len(metrics)} records")
        for metric in metrics[: args.limit]:
            print(
                f"- {metric.facility_id} {metric.metric_name}="
                f"{metric.metric_value} {metric.metric_unit} "
                f"model={metric.trace_payload.get('model')}"
            )


if __name__ == "__main__":
    main()
