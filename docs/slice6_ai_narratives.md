# Slice 6 AI Narrative Summaries

Status: implemented.

The narrative layer generates bulletin text from structured computed metrics only. It never receives raw CSV rows, staging payloads, or patient-level data.

## Data Flow

1. Ingestion standardizes the five MVP files.
2. The data quality copilot validates the batch.
3. The analytics engine computes `report_ready_metrics`.
4. `build_metric_package` extracts a compact Pydantic `MetricPackage`.
5. `generate_narrative` produces narrative sections by either:
   - deterministic fallback text, or
   - OpenAI Responses API with structured JSON output when `OPENAI_API_KEY` is configured.

## Guardrails

- The model input is a computed-only `MetricPackage`.
- Prompts instruct the model not to invent numbers or add external facts.
- OpenAI output is requested as strict JSON schema.
- Generated narrative retains metric references.
- If OpenAI is unavailable or errors, deterministic fallback text is used.
- Reports remain blocked by high-severity DQ issues unless explicitly overridden.

## Environment

```bash
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.2
```

`OPENAI_MODEL` defaults to `gpt-5.2`.

## CLI

Fallback/no API call:

```bash
python -m sand_bulletin.cli generate-narrative \
  --data-dir docs/data \
  --tenant-id sand \
  --country-code RWA \
  --allow-high-severity \
  --no-openai
```

OpenAI-enabled:

```bash
OPENAI_API_KEY=... python -m sand_bulletin.cli generate-narrative \
  --data-dir docs/data \
  --tenant-id sand \
  --country-code RWA \
  --allow-high-severity
```

Report generation includes narrative sections automatically:

```bash
python -m sand_bulletin.cli generate-reports \
  --data-dir docs/data \
  --tenant-id sand \
  --country-code RWA \
  --output-dir outputs \
  --allow-high-severity
```

Use `--no-openai` to force deterministic fallback.

## Generated Sections

- Executive summary
- Key findings
- Facility watchlist explanation
- Recommendations
- Metric references

## Notes

The current sample data still requires explicit override because of duplicate January and March clinical facility-month rows. The narrative text will state that high-severity DQ issues require review before final publication.
