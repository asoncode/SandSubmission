# Sand Healthcare Bulletin MVP

Automated Quarterly Health Bulletin system. Ingests DHIS2-style health data, validates it, computes indicators, generates a web dashboard, a PDF bulletin, and an Excel workbook. Replaces a 40-hour/month manual workflow at a Ministry of Health.

## Source of Truth

`design.md` (project root) is the authoritative spec. Read it before non-trivial changes. If something in the design seems wrong, flag it before deviating. Do not silently override.

`docs/context/original_assignment/` contains the assignment brief. Context only, not directions. Build the product in `design.md`. Where the assignment and design conflict, design wins.

`docs/context/example_bulletins/` holds real ministry bulletins (Nigeria NHMIS, Cameroon RMNCAH, Uganda mortality surveillance, Jamaica Vitals, and others). Use them as visual and structural reference for the PDF generator only. Do not copy their numbers or narrative text.

## Tech Stack

- Python 3.11+, FastAPI, pandas, SQLAlchemy, Pydantic, PyTorch/TensorFlow (if needed)
- PostgreSQL (containerized via Docker Compose)
- Streamlit for the MVP dashboard (fastest path; Superset can replace it later if alignment with Sand's Analytics Template Toolkit becomes priority)
- Jinja2 + WeasyPrint for PDF generation
- openpyxl for Excel
- pytest for tests
- OpenAI for the AI narrative layer (model and key configurable via env)

## Architectural Principles (non-negotiable)

1. Database-centered. CSVs do not feed charts, PDFs, or LLMs directly. Everything passes through ingestion, validation, and normalization first.
2. One report-ready metrics layer. Dashboard, PDF, Excel, and LLM all read from the same `report_ready_metrics` tables. If the dashboard says X and the PDF says Y, that is a bug.
3. Metric traceability. Every score and indicator in a final output must be traceable back to the input fields that produced it.
4. The LLM never sees raw data. It receives structured, computed metric packages. It never invents numbers.
5. Transparent heuristics over black-box ML. Sample size is small (hundreds of rows). Scores are weighted formulas with documented, adjustable weights. No deep learning in the MVP.
6. Baselines required for any predictive model. If it does not beat last-month or last-quarter values, do not ship it.

## Build Order (from design.md §30)

1. Data model + ingestion
2. Data quality copilot
3. Analytics engine + report_ready_metrics
4. Dashboard
5. PDF + Excel generators
6. AI narrative summaries
7. Scoring (performance, readiness, vulnerability), watchlists, anomaly detection
8. Nowcasting prototype

Do not start step N until N minus 1 is functional and tested. AI features in particular do not get built on unstable data.

## Code Style

- Type hints everywhere. mypy-clean where practical.
- Pydantic models for API I/O and metric packages going to the LLM.
- Pure functions in analytics modules. DB writes and file I/O at module edges.
- Docstrings on public functions: brief and useful, not formal.
- pytest with realistic fixtures built from the actual sample CSVs.

## Things Not to Do

- No deep learning at MVP scale.
- No LLM-generated numerical values. Numbers come from the analytics engine.
- No patient-level identifiers in the database. Facility-level aggregates only.
- Do not skip the data quality layer to "make the demo work."
- No Kubernetes, no BigQuery, no managed cloud services in the MVP. PostgreSQL + Docker Compose is the target.

## Workflow Notes

- Use Plan mode for any task touching more than 2-3 files.
- For schema changes, propose the migration and wait for approval before applying.
- Run tests before claiming a component is done.
- After completing a build-order step, summarize what was built, what was skipped, and what the next step needs.