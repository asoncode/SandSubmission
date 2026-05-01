Technical Design Document
AI-Enhanced Automated Quarterly Health Bulletin MVP
1. Project Overview
The Ministry of Health currently spends about 40 hours per month manually compiling a Quarterly Health Bulletin from DHIS2-style Excel exports. The goal of this MVP is to replace that manual workflow with a repeatable system that ingests structured health data, validates it, computes indicators, generates charts and insights, and produces three outputs: a web dashboard, a PDF bulletin, and an Excel summary workbook.
The project should not be treated as a full national health operating system yet. The MVP should be small enough to run on the five provided files, but designed in a way that would later support live DHIS2 integration, more facilities, additional health programs, and Sand’s existing products like Health Atlas, Health Outcome Tracker, Health Insight Engine, Analytics Template Toolkit, and HealthOS Data Models.
The uploaded ministry bulletins show that the final product needs to feel like an official public-health publication, not just a dashboard export. The Nigeria NHMIS bulletin emphasizes reporting rates, facility attendance, maternal health charts, and clear month-to-month visuals.  The Cameroon RMNCAH bulletin has a more formal quarterly structure with an executive summary, completeness/timeliness section, maternal health, neonatal health, recommendations, and narrative interpretation.  The Uganda mortality surveillance bulletin shows a compact surveillance style with highlights, maps, KPI blocks, and mortality breakdowns. 
The MVP should combine those three patterns: official report structure, strong visuals, automated interpretation, and operational decision support.

2. Product Goal
The core product is an Automated Quarterly Health Bulletin System.
It should allow a Ministry user to upload or refresh DHIS2-like files and automatically generate:


A web-based operational bulletin/dashboard.


A polished PDF bulletin.


An Excel factsheet/workbook.


Data quality flags.


Facility rankings, risk scores, and trend summaries.


AI-assisted narrative sections grounded in computed metrics.


The key transformation is:
Manual retrospective reporting → automated, repeatable, AI-enhanced health intelligence workflow.

3. MVP Scope
The MVP will use the five provided files:


clinical_neonatal.csv


facilities.csv


governance.csv


healthcare_workers.csv


operations.csv


These files are enough to build a serious prototype because they cover clinical outcomes, facility readiness, governance quality, workforce capacity, and operational constraints.
The system will support cumulative monthly data across multiple reporting periods. This matters because the system should not only produce a one-off monthly report; it should compare across months and quarters, detect changes over time, and generate trend analysis.
The MVP will focus on two product layers:
Layer 1: Bulletin Automation
This directly solves the original MoH problem. It automates ingestion, validation, indicator calculation, charts, narrative writing, PDF generation, dashboard creation, and Excel summary output.
Layer 2: Operational Intelligence Enhancements
This adds facility vulnerability scoring, neonatal readiness scoring, watchlists, anomaly detection, AI summaries, and optional nowcasting. These enhancements are still tied to the bulletin, not a separate product.
The MVP will not include a full digital twin, real-time national streaming infrastructure, advanced causal simulation, or production-grade EMR integration.

4. User Personas
Ministry Data Officer
This user currently spends hours cleaning Excel exports, calculating indicators, copying charts into reports, and writing summaries. For them, the system should reduce manual work, make data quality issues visible, and produce downloadable outputs quickly.
Ministry Program Manager
This user cares less about raw data processing and more about what the data means. They need to know which facilities are underperforming, where neonatal outcomes are worsening, and what interventions should be prioritized.
Country Director / Solutions Manager
This user needs a high-level picture of whether the health system is improving. They care about trends, facility performance, operational gaps, and whether the system can scale beyond the MVP.
Facility or District Decision-Maker
This user needs actionable facility-level intelligence: which indicators are worsening, whether reporting is incomplete, whether staff or equipment gaps are linked to poor outcomes, and what should be investigated.

5. Data Sources
clinical_neonatal.csv
This is the outcome layer. It contains facility-month clinical indicators such as total deliveries, live births, neonatal deaths in 0–7 days, neonatal deaths in 8–28 days, stillbirths, cause-specific neonatal deaths, average gestational age, preterm births, low Apgar scores, and low birth weight.
This file answers: What is happening to newborns clinically?
It powers neonatal mortality rates, stillbirth rates, cause-of-death breakdowns, prematurity burden, low birth weight analysis, and facility outcome trends.
facilities.csv
This is the facility infrastructure layer. It contains facility location, district, province, tier level, NICU availability, NICU beds, incubators, radiant warmers, phototherapy units, CPAP machines, resuscitation tables, kangaroo care space, electricity reliability, and backup generator availability.
This file answers: What capacity does each facility have?
It powers Health Atlas mapping, facility readiness scoring, equipment gap detection, and geographic visualization.
governance.csv
This is the quality and governance layer. It includes protocol existence, protocol update recency, death audit completion, staff training on protocol, quality improvement activity, supervision visits, HMIS reporting completeness, bag-mask ventilation competency, thermal care protocol compliance, and infection prevention score.
This file answers: How well is the facility governed and following quality standards?
It powers reporting performance, data quality scoring, governance risk, and quality-of-care analysis.
healthcare_workers.csv
This is the workforce layer. It includes nurses, neonatal-trained nurses, midwives, obstetricians, pediatricians, neonatologists, anesthetists, last neonatal training date, staff per delivery, and night-shift coverage.
This file answers: Does the facility have enough trained people to handle its delivery and neonatal burden?
It powers workforce adequacy analysis, staffing risk, and vulnerability scoring.
operations.csv
This is the operational systems layer. It includes referral time, referrals in/out, oxygen availability, oxygen plant, ambulance availability, kangaroo care practice, essential drug stockout days, antibiotics availability, surfactant availability, and referral feedback rate.
This file answers: Can the facility operationally respond to neonatal risk?
It powers referral bottleneck detection, oxygen readiness, stockout analysis, operational risk scoring, and intervention prioritization.

6. System Architecture
The MVP architecture should be centered around a clean database. Excel files should not feed charts, PDFs, or LLMs directly. Everything should pass through ingestion, validation, standardization, and analytics first.
The system flow is:
Raw CSV/Excel files enter the ingestion layer. The ingestion layer reads the files, standardizes column names, parses dates, validates basic types, and stores the rows in staging tables. The data quality copilot then checks the staged data for missing values, impossible values, duplicates, outliers, and suspicious trends. Cleaned and validated data is written into normalized database tables. The analytics engine computes KPIs, rankings, trends, scores, and report-ready tables. The AI insight layer generates grounded narrative summaries and watchlist explanations using only computed metrics. Finally, the output layer produces the dashboard, PDF bulletin, and Excel workbook.
The database is the center of the system. Superset, the web app, the PDF generator, the Excel generator, and the LLM should all read from the same validated report-ready data.

7. Component 1: Data Ingestion Layer
The ingestion layer is responsible for taking raw uploaded files and converting them into standardized staging data.
It should accept CSV files for the MVP, but the structure should also support Excel files later because the original MoH workflow is based on DHIS2 Excel exports.
The ingestion layer does four things.
First, it identifies the file type and maps it to a known dataset category: clinical, facilities, governance, workforce, or operations.
Second, it standardizes column names. For example, if one future export uses Facility ID and another uses facility_id, the system should map both into the same internal field.
Third, it converts data types. Dates should become dates, numeric fields should become numbers, boolean fields should become booleans, and facility IDs should become strings.
Fourth, it loads the raw and standardized rows into staging tables. The staging layer should preserve the original upload so that the system has an audit trail.
For the MVP, ingestion can be built using Python, pandas, and a FastAPI upload endpoint. Each uploaded file gets a unique upload ID, timestamp, file type, and validation status.
This component should be simple, but robust. It should not try to “fix” everything. Its job is to read and standardize. The data quality copilot handles deeper checks.

8. Component 2: Data Quality Copilot
The data quality copilot sits immediately after ingestion and before analytics.
This is important. The system should not generate charts or AI summaries from dirty data. It should first inspect the data and produce a structured list of issues.
The copilot should be rule-based in the MVP. Calling it a “copilot” does not mean the first version needs a complex LLM agent. It means the system behaves like an assistant that checks the data, explains issues, and tells the user what may need review.
It should check for five categories of issues.
Missingness
The system should flag missing facility IDs, missing reporting months, missing clinical indicators, missing GPS coordinates, missing district/province fields, and missing key operational data.
Duplicates
The system should flag duplicate facility-month records. For example, if the same facility has two clinical neonatal rows for the same reporting month, that should be flagged before aggregations happen.
Logical Inconsistencies
The system should flag impossible or suspicious relationships. Examples include neonatal deaths greater than live births, stillbirths greater than total deliveries, preterm births greater than live births, incubators functional greater than incubators total, or reporting completeness above reasonable thresholds.
Outliers
The system should flag unusually large changes compared with a facility’s own historical values. For example, a sudden 90% drop in deliveries, a sudden spike in neonatal deaths, or a facility reporting zero deaths for many months after previously reporting consistent mortality.
Reporting Quality
The system should use governance fields like HMIS reporting completeness and timeliness-related indicators where available. Since real bulletins often include reporting completeness and timeliness sections, this should become a visible section in the PDF and dashboard. The Cameroon bulletin, for example, explicitly includes completeness and timeliness of monthly activity reports as a major section. 
Each issue should be stored in a data_quality_issues table with facility ID, reporting month, issue type, severity, affected column, observed value, expected rule, and suggested action.
The copilot should not block report generation for every issue. Instead, issues should be categorized:
Low severity issues allow the report to continue. Medium severity issues appear as warnings. High severity issues require either correction or explicit user override.

9. Component 3: Standardized Health Data Model
The HealthOS-style data model is the normalized schema that turns messy source files into consistent tables.
For the MVP, the data model should be relational and facility-centered. The facility is the core entity, and most other tables join to it by facility_id.
The main normalized tables should be:
facilities
This table contains one row per facility. It includes facility name, district, province, tier level, coordinates, NICU availability, equipment availability, electricity reliability, and backup generator status.
clinical_neonatal_monthly
This table contains facility-month clinical outcome data. It includes deliveries, live births, neonatal deaths, stillbirths, cause-specific deaths, preterm births, low Apgar counts, and low birth weight counts.
governance_monthly_or_static
This table contains quality and governance indicators. Some fields may be static for a quarter, while others may change over time. For the MVP, if no month column exists, these can be treated as current facility attributes.
workforce_monthly_or_static
This table contains staffing information. Like governance, some fields may not change monthly in the sample data. The model should still allow future time-varying workforce data.
operations_monthly_or_static
This table contains referral, oxygen, ambulance, drug availability, and stockout indicators.
data_quality_issues
This table stores validation outputs.
bulletin_runs
This table stores each generated bulletin run, including reporting period, timestamp, input files used, generated PDF path, generated Excel path, and status.
report_ready_metrics
This is not raw data. It contains computed KPIs prepared for the dashboard, PDF, Excel output, and LLM summary generation.
The MVP should use PostgreSQL because it is lightweight, easy to deploy, compatible with Superset, and enough for several hundred rows or even millions later. BigQuery can be mentioned as a future production option, but for MVP PostgreSQL is better.

10. Component 4: Analytics Engine
The analytics engine computes all required indicators and intelligence outputs from the standardized database.
It should not be mixed into dashboard logic or PDF generation. This separation matters because the same metrics must feed multiple outputs.
The analytics engine should calculate the original required bulletin metrics:
Top 10 facilities by patient volume, maternal or neonatal health indicators, facility performance scores, reporting completeness, reporting timeliness if available, and trend analysis versus previous quarters.
Because the available sample data is neonatal-focused, the MVP should adapt the maternal-health requirement into a neonatal/maternal-adjacent bulletin while preserving the same structure. For example, total deliveries, live births, neonatal deaths, stillbirths, preterm births, and low birth weight are directly relevant to maternal and newborn health.
The analytics engine should also calculate enhanced metrics:
Neonatal mortality rate, early neonatal mortality rate, late neonatal mortality rate, stillbirth rate, cause-of-death distribution, preterm birth burden, low birth weight rate, low Apgar rate, equipment readiness, workforce readiness, governance readiness, operations readiness, facility vulnerability score, neonatal readiness score, and watchlist ranking.
The key design principle is that every metric should be traceable. If the PDF says “Facility X is high risk,” the system should be able to show which underlying fields contributed to that score.

11. Component 5: Facility Performance Score
The original prompt requires facility performance scoring. For this MVP, the score should combine reporting performance, governance quality, and operational readiness.
A simple scoring model is better than a black-box model.
The facility performance score should be a 0–100 score. It can include HMIS reporting completeness, death audit completion, staff protocol training, quality improvement activity, supervision visits, infection prevention score, and protocol compliance.
A facility with high reporting completeness, recent protocols, strong staff training, active quality improvement, and strong infection prevention should score highly. A facility with poor reporting, no active quality improvement, low training, and weak audit practices should score low.
This score answers: How well is the facility performing as a reporting and quality system?
It should be displayed in the dashboard and PDF as a ranked table, district comparison, and trend where time data exists.

12. Component 6: Neonatal Readiness Score
The neonatal readiness score is one of the strongest enhancements because the sample data directly supports it.
This score should measure whether a facility is ready to handle neonatal risk. It should combine equipment, workforce, operations, and governance.
Inputs can include NICU availability, NICU beds, functional incubators, CPAP machines, resuscitation tables, radiant warmers, phototherapy units, kangaroo care space, electricity reliability, backup generator availability, neonatal-trained nurses, pediatricians, neonatologists, oxygen availability, antibiotics availability, surfactant availability, ambulance availability, and infection prevention score.
The output is a 0–100 readiness score.
This score answers: If a newborn is at risk, how prepared is this facility to respond?
The readiness score should be broken into sub-scores so users can see why a facility is weak. For example, a facility may have decent staff but poor equipment, or decent equipment but weak referral systems.
This makes the score actionable.

13. Component 7: Facility Vulnerability Index
The vulnerability index is different from readiness.
Readiness asks: How prepared is the facility?
Vulnerability asks: Which facilities are most concerning given their outcomes, workload, and capacity gaps?
A high-volume hospital with rising neonatal deaths, long referral times, low staff per delivery, frequent drug stockouts, and limited CPAP access should rank as highly vulnerable.
The vulnerability index should combine outcome burden, capacity gaps, workforce pressure, operational weakness, and governance weakness.
This can be implemented as a transparent weighted heuristic for MVP. Later it can become an ML model.
The purpose is to create a “Top 10 facilities requiring follow-up” list. This is more useful than only ranking facilities by patient volume.
The watchlist should explain why each facility appears.
Example: “Facility A is flagged because neonatal deaths increased compared with the previous quarter, referral time is above the national median, stockout days are high, and neonatal-trained nurse coverage is low.”
This is a direct decision-support feature.

14. Component 8: Trend Analysis
Trend analysis should compare each reporting period against previous periods.
Because the data spans months, the system should support both monthly and quarterly aggregation.
For each facility, district, province, and national level, the system should compute current period value, previous period value, absolute change, percentage change, and direction.
Trend analysis should apply to deliveries, live births, neonatal deaths, stillbirths, low birth weight, preterm births, referral times, stockout days, reporting completeness, and performance scores.
The PDF should include only the most important trends. The dashboard can expose more detailed trend charts.
Trend analysis should also power the LLM narrative. The model should not invent interpretation; it should receive structured trend data and convert it into readable language.
The Cameroon bulletin is a good example of narrative trend interpretation, where charts are followed by paragraphs explaining changes, disparities, and recommended action. 

15. Component 9: Anomaly Detection
The anomaly detection module should identify facilities, districts, or indicators that changed unexpectedly.
For MVP, use simple statistical detection rather than advanced ML.
Good methods include z-score, interquartile range, rolling average deviation, and percentage-change thresholds.
Examples of anomalies:
A facility reports a sharp fall in deliveries. A district has a sudden spike in neonatal deaths. A facility reports zero stockouts after months of high stockouts. A facility reports more functional incubators than total incubators. A facility has high neonatal deaths but no recorded complications or cause-of-death distribution.
Anomaly detection should feed three places:
The dashboard, where anomalies appear as alerts.
The PDF bulletin, where major anomalies appear in a “Data Quality and Unusual Trends” section.
The data quality copilot, where anomalies that may reflect reporting errors are stored as issues.
There should be a distinction between a true health anomaly and a likely data quality anomaly. For MVP this distinction can be heuristic.

16. Component 10: AI Executive Summary Generator
The AI executive summary generator should create official-sounding narrative sections for the bulletin.
The LLM should not analyze raw data directly. It should receive a structured metrics package generated by the analytics engine.
The input should include the reporting period, national KPIs, top changes, highest-risk facilities, strongest-performing facilities, reporting completeness, major anomalies, and recommended follow-up areas.
The output should include an executive summary, key findings, facility watchlist explanation, and recommendations.
The system must use guardrails:
All numbers must come from computed metrics. The prompt should instruct the LLM not to create new figures. The generated summary should include a citation-like internal reference to the metric source, even if the final PDF does not expose raw JSON. The user should be able to regenerate the summary from the same metrics.
This component is valuable because official bulletins are narrative documents. The Jamaica Vitals bulletin, for instance, includes editorial and explanatory public-health text alongside visuals.  The AI generator helps produce that type of narrative quickly while keeping the numbers grounded.

17. Component 11: Nowcasting Prototype
Nowcasting should be included as an optional Phase 2 module, not as the main product.
The original idea was to estimate the current state despite a 2–3 week DHIS2 delay. With the available data, nowcasting can predict near-current facility delivery volume, live births, expected neonatal burden, or stockout risk using prior months and facility attributes.
The MVP should avoid predicting exact maternal or neonatal deaths as official values. Mortality is too sensitive and often too sparse. Instead, the nowcasting module should produce risk estimates or expected ranges.
Good initial targets include expected delivery volume, expected live births, expected high-risk burden, and probability of facility stress.
Inputs can include previous monthly values, facility tier, district, province, equipment readiness, workforce capacity, stockout days, referral times, and seasonality.
Models should be simple: seasonal baseline, rolling average, linear regression, random forest, or gradient-boosted trees if enough data exists.
The output should be labeled clearly:
“Estimated current value based on historical reporting patterns; not official reported data.”
This feature is useful, but it should not dominate the MVP. The bigger value is automation and operational intelligence.

18. Component 12: Dashboard / Web Application
The web dashboard is the live operational version of the bulletin.
It should allow users to upload data, select reporting periods, view KPIs, inspect facility rankings, review data quality issues, and generate outputs.
The dashboard can be built in two possible ways.
The fastest MVP is Streamlit because it is easy to build, deploy, and connect to Python analytics. The more enterprise-like option is FastAPI plus React or Apache Superset.
Given this is an MVP, the best approach is:
Use FastAPI for backend APIs, PostgreSQL for data, and either Streamlit or Superset for the first dashboard. If the goal is speed, Streamlit is easiest. If the goal is alignment with Sand’s Analytics Template Toolkit and Apache Superset, Superset is more realistic.
The dashboard should include:
A national overview page with KPI cards.
A facility ranking page showing top facilities by volume, performance score, readiness score, and vulnerability.
A data quality page showing missingness, duplicates, logical issues, and anomalies.
A trend page showing month-over-month and quarter-over-quarter changes.
A map page using facility GPS coordinates to show hotspots, readiness gaps, and vulnerable facilities.
A report generation page where users can generate PDF and Excel outputs.
The dashboard should not be overly complex. Its job is to expose the same metrics used by the bulletin, but interactively.

19. Component 13: PDF Bulletin Generator
The PDF generator is one of the most important components because the original problem is bulletin automation.
The PDF should be generated from report-ready metrics, charts, and AI-written narrative text.
The recommended approach is HTML-to-PDF generation using Jinja2 templates and WeasyPrint. This allows the bulletin to be designed like a webpage with consistent typography, section headers, charts, tables, and official formatting.
The PDF should follow this structure:
Cover page.
Table of contents.
Executive summary.
Data source and reporting completeness.
National overview.
Facility reporting and performance.
Maternal/neonatal health indicators.
Neonatal outcomes and cause-of-death breakdown.
Facility readiness and vulnerability.
Trend analysis versus previous quarters.
Top 10 facilities by patient volume.
Top 10 facilities requiring follow-up.
Data quality notes.
Recommendations.
Appendix tables.
Charts should be generated with Python and saved as image assets before being embedded in the PDF template. Tables should be rendered directly from the report-ready database tables.
The PDF should feel like a ministry publication. The Nigeria example is visual and indicator-focused, the Cameroon example is formal and narrative-heavy, and the Uganda example is surveillance-focused with strong KPI blocks and maps. The MVP should borrow from all three.   

20. Component 14: Excel Summary Workbook
The Excel output should serve users who still need tabular summaries for internal review, sharing, or further manual analysis.
It should be generated from the same report-ready metrics as the PDF and dashboard.
The workbook should include sheets for summary KPIs, facility rankings, district trends, clinical indicators, readiness scores, vulnerability watchlist, and data quality issues.
This can be built using pandas and openpyxl.
The Excel workbook is important because ministries often continue to rely on Excel even when dashboards and PDFs exist. This output makes the system easier to adopt.

21. Component 15: Backend API
The backend should expose a small set of API endpoints.
The upload endpoint accepts CSV or Excel files and creates an upload record.
The validation endpoint runs data quality checks and stores issues.
The metrics endpoint returns national, district, facility, and trend KPIs.
The watchlist endpoint returns ranked high-risk facilities with explanations.
The dashboard endpoints serve filtered data to the frontend or Superset.
The report endpoint generates a new bulletin run.
The export endpoint downloads PDF and Excel outputs.
The backend should be stateless where possible. Persistent state should live in PostgreSQL and file storage.
For MVP, local file storage is acceptable. For a later deployment, generated reports can be stored in cloud object storage.

22. Component 16: Storage and Database Choice
The MVP should use PostgreSQL.
PostgreSQL is the right choice because the data is relational, facility-centered, and small enough to run locally. It integrates well with Python, FastAPI, Superset, and Docker Compose.
The system should not “code a database from scratch.” It should define schemas, transformations, and queries on top of a standard database.
BigQuery is a good future production option if Sand or MoH wants cloud-scale analytics, managed infrastructure, and larger national datasets. But using BigQuery in the MVP may add unnecessary setup complexity.
So the MVP decision is:
PostgreSQL for MVP.
BigQuery-compatible schema design for future scale.

23. Component 17: Report Run and Auditability
Every generated bulletin should be reproducible.
The system should store a bulletin_run record containing the reporting period, input files used, upload IDs, validation status, generated metrics version, generated PDF path, generated Excel path, AI summary version, and timestamp.
This matters because official health reports need traceability. If someone asks why a number appears in the PDF, the team should be able to identify which file, row, and metric calculation produced it.
The MVP does not need full enterprise audit infrastructure, but it should preserve enough metadata to make the system credible.

24. Training and Modeling Strategy
Because the dataset has only several hundred rows per file, the MVP should not rely on deep learning.
The first version should use transparent heuristics and simple classical models.
The facility performance score, readiness score, and vulnerability score should be weighted formulas. The weights should be documented and adjustable.
Anomaly detection should use simple statistical rules.
Nowcasting can use rolling averages, seasonal baselines, linear regression, or random forest if enough months exist.
The most important ML principle here is baseline comparison. Any predictive model should be compared against simple baselines like last month’s value, previous quarter’s value, or same quarter from the previous year if available.
If the model does not beat these baselines, it should not be presented as an improvement.

25. Deployment Design
The MVP should be deployable with Docker Compose.
The services should include:
The application service running FastAPI and the report generator.
The PostgreSQL database.
The dashboard service, either Streamlit or Superset.
Optionally, a worker service for report generation if PDF generation becomes slow.
The user should be able to run the whole system locally with one command.
For a lightweight hosted deployment, the app can be deployed on Render, Railway, Fly.io, or GCP Cloud Run, with PostgreSQL managed by the same platform.
The MVP does not need Kubernetes.

26. Security and Privacy
Even though the sample files may not contain direct patient identifiers, the system should be designed with health-data sensitivity in mind.
The MVP should avoid storing patient-level identifiers unless absolutely required. Facility-level aggregate data is safer.
Access should be role-based in future versions, but MVP can start with a simple authenticated admin user.
Generated reports should not expose raw data quality details that could embarrass specific facilities unless intended for internal use. There may need to be two PDF modes later: internal operational bulletin and public-facing bulletin.
LLM prompts should not include unnecessary sensitive data. For this MVP, the LLM should only receive aggregate metrics and facility-level summaries.

27. Failure Modes and Mitigations
The first major risk is dirty data. The mitigation is the data quality copilot and clear validation reports.
The second risk is hallucinated AI summaries. The mitigation is metrics-grounded prompting and never allowing the LLM to invent numbers.
The third risk is overengineering. The mitigation is keeping the MVP centered on bulletin automation, with intelligence features as enhancements.
The fourth risk is model weakness due to small data. The mitigation is using transparent scores and simple baselines instead of deep learning.
The fifth risk is report inconsistency. The mitigation is using one report-ready metrics layer for all outputs.

28. End-to-End User Flow
A Ministry data officer logs into the web app and uploads the five DHIS2-like files. The system reads the files, standardizes their columns, and stores them in staging tables. The data quality copilot runs validation checks and shows a summary of issues. The user reviews warnings and either corrects the data or proceeds with flagged issues.
The system then transforms the data into standardized tables and computes all bulletin metrics. The dashboard updates with national KPIs, facility rankings, readiness scores, vulnerability scores, trends, maps, and data quality summaries.
The user clicks “Generate Bulletin.” The system creates charts, prepares tables, sends structured metrics to the AI summary generator, renders the HTML bulletin template, exports it to PDF, and saves the bulletin run. The user can also download an Excel workbook containing the same facts and tables.
The final result is a bulletin process that takes minutes instead of 40 hours per month.

29. MVP Success Criteria
The MVP is successful if it can ingest the five provided files, validate the data, compute key indicators, generate a dashboard, produce a PDF bulletin, export an Excel workbook, and create grounded AI summaries.
The business success metric is reducing bulletin compilation from 40 hours per month to under 30 minutes of user review time.
The technical success metrics are reproducible report generation, consistent metrics across dashboard/PDF/Excel, visible data quality flags, and successful deployment from a clean environment.
The product success metric is that a Ministry user can understand not only what happened, but which facilities need attention and why.

30. Recommended Build Order
Start with the data model and ingestion pipeline. Without clean data, everything else is fake.
Then build the data quality copilot because this protects every downstream output.
Then build the analytics engine and report-ready tables.
Then build the dashboard.
Then build the PDF and Excel generators.
Then add AI narrative summaries.
Then add vulnerability scoring, readiness scoring, watchlists, anomaly detection, and optional nowcasting.
This order keeps the project grounded and prevents AI features from being built on unstable data.

31. Final System Definition
This MVP is an automated health bulletin generation platform with an operational intelligence layer.
It is not merely “Excel to PDF.”
It is:
A data ingestion system, a data quality copilot, a standardized health data model, an analytics engine, a facility intelligence layer, an AI-assisted narrative generator, a dashboard, a PDF bulletin generator, and an Excel reporting tool.
That is still aligned with the original problem because every advanced feature grows out of the bulletin workflow. The system first solves the manual reporting burden, then turns the same workflow into a decision-support product.