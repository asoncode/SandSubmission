-- Slice 1 schema proposal. Approval direction incorporated; not applied automatically.

CREATE TYPE dataset_kind AS ENUM (
    'clinical_neonatal',
    'facilities',
    'governance',
    'healthcare_workers',
    'operations'
);

CREATE TYPE upload_batch_status AS ENUM (
    'created',
    'standardized',
    'validated',
    'loaded',
    'failed'
);

CREATE TYPE upload_status AS ENUM (
    'received',
    'standardized',
    'validated',
    'loaded',
    'failed'
);

CREATE TYPE issue_severity AS ENUM (
    'low',
    'medium',
    'high'
);

CREATE TYPE availability_status AS ENUM (
    'yes',
    'partial',
    'no',
    'unknown'
);

CREATE TYPE availability_frequency AS ENUM (
    'always',
    'usually',
    'rarely',
    'never',
    'unknown'
);

CREATE TABLE upload_batches (
    id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    country_code CHAR(3) NOT NULL DEFAULT 'RWA',
    reporting_period_start DATE,
    reporting_period_end DATE,
    status upload_batch_status NOT NULL DEFAULT 'created',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    standardized_at TIMESTAMPTZ,
    validated_at TIMESTAMPTZ,
    loaded_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE INDEX ix_upload_batches_tenant_country_created_at
    ON upload_batches (tenant_id, country_code, created_at DESC);

CREATE TABLE uploads (
    id UUID PRIMARY KEY,
    batch_id UUID NOT NULL REFERENCES upload_batches(id) ON DELETE CASCADE,
    dataset_kind dataset_kind NOT NULL,
    source_filename TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    row_count INTEGER NOT NULL CHECK (row_count >= 0),
    status upload_status NOT NULL DEFAULT 'received',
    stored_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    standardized_at TIMESTAMPTZ,
    loaded_at TIMESTAMPTZ,
    error_message TEXT,
    UNIQUE (batch_id, dataset_kind)
);

CREATE INDEX ix_uploads_batch_id ON uploads (batch_id);
CREATE INDEX ix_uploads_dataset_kind_created_at ON uploads (dataset_kind, created_at DESC);

CREATE TABLE staging_rows (
    id BIGSERIAL PRIMARY KEY,
    upload_id UUID NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    batch_id UUID NOT NULL REFERENCES upload_batches(id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    country_code CHAR(3) NOT NULL,
    dataset_kind dataset_kind NOT NULL,
    source_row_number INTEGER NOT NULL CHECK (source_row_number >= 1),
    standardized_payload JSONB NOT NULL,
    raw_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (upload_id, source_row_number)
);

CREATE INDEX ix_staging_rows_batch_id ON staging_rows (batch_id);
CREATE INDEX ix_staging_rows_upload_id ON staging_rows (upload_id);
CREATE INDEX ix_staging_rows_dataset_kind ON staging_rows (dataset_kind);

CREATE TABLE facilities (
    tenant_id TEXT NOT NULL DEFAULT 'default',
    country_code CHAR(3) NOT NULL DEFAULT 'RWA',
    facility_id TEXT NOT NULL,
    facility_name TEXT NOT NULL,
    district TEXT NOT NULL,
    province TEXT NOT NULL,
    tier_level TEXT NOT NULL,
    gps_lat NUMERIC(9, 6),
    gps_lon NUMERIC(9, 6),
    nicu_available availability_status,
    nicu_beds INTEGER CHECK (nicu_beds IS NULL OR nicu_beds >= 0),
    incubators_functional INTEGER CHECK (incubators_functional IS NULL OR incubators_functional >= 0),
    incubators_total INTEGER CHECK (incubators_total IS NULL OR incubators_total >= 0),
    radiant_warmers INTEGER CHECK (radiant_warmers IS NULL OR radiant_warmers >= 0),
    phototherapy_units INTEGER CHECK (phototherapy_units IS NULL OR phototherapy_units >= 0),
    cpap_machines INTEGER CHECK (cpap_machines IS NULL OR cpap_machines >= 0),
    resuscitation_tables INTEGER CHECK (resuscitation_tables IS NULL OR resuscitation_tables >= 0),
    kangaroo_care_space availability_status,
    electricity_reliable availability_status,
    backup_generator BOOLEAN,
    source_upload_id UUID REFERENCES uploads(id),
    source_row_number INTEGER,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, country_code, facility_id)
);

CREATE TABLE clinical_neonatal_monthly (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    country_code CHAR(3) NOT NULL DEFAULT 'RWA',
    facility_id TEXT NOT NULL,
    reporting_month DATE NOT NULL,
    total_deliveries INTEGER CHECK (total_deliveries IS NULL OR total_deliveries >= 0),
    live_births INTEGER CHECK (live_births IS NULL OR live_births >= 0),
    neonatal_deaths_0_7d INTEGER CHECK (neonatal_deaths_0_7d IS NULL OR neonatal_deaths_0_7d >= 0),
    neonatal_deaths_8_28d INTEGER CHECK (neonatal_deaths_8_28d IS NULL OR neonatal_deaths_8_28d >= 0),
    stillbirths INTEGER CHECK (stillbirths IS NULL OR stillbirths >= 0),
    death_birth_asphyxia INTEGER CHECK (death_birth_asphyxia IS NULL OR death_birth_asphyxia >= 0),
    death_prematurity INTEGER CHECK (death_prematurity IS NULL OR death_prematurity >= 0),
    death_sepsis INTEGER CHECK (death_sepsis IS NULL OR death_sepsis >= 0),
    death_congenital INTEGER CHECK (death_congenital IS NULL OR death_congenital >= 0),
    death_other INTEGER CHECK (death_other IS NULL OR death_other >= 0),
    avg_gestational_age NUMERIC(4, 1),
    preterm_births_28_32w INTEGER CHECK (preterm_births_28_32w IS NULL OR preterm_births_28_32w >= 0),
    preterm_births_32_37w INTEGER CHECK (preterm_births_32_37w IS NULL OR preterm_births_32_37w >= 0),
    apgar_less_7_at_5min INTEGER CHECK (apgar_less_7_at_5min IS NULL OR apgar_less_7_at_5min >= 0),
    birth_weight_less_2500g INTEGER CHECK (birth_weight_less_2500g IS NULL OR birth_weight_less_2500g >= 0),
    source_upload_id UUID REFERENCES uploads(id),
    source_row_number INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, country_code, facility_id)
        REFERENCES facilities (tenant_id, country_code, facility_id),
    UNIQUE (tenant_id, country_code, facility_id, reporting_month)
);

CREATE INDEX ix_clinical_neonatal_monthly_reporting_month
    ON clinical_neonatal_monthly (reporting_month);

CREATE TABLE governance_facility (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    country_code CHAR(3) NOT NULL DEFAULT 'RWA',
    facility_id TEXT NOT NULL,
    effective_start_month DATE,
    effective_end_month DATE,
    newborn_protocol_exists BOOLEAN,
    protocol_last_updated DATE,
    death_audits_conducted_pct NUMERIC(6, 5) CHECK (death_audits_conducted_pct IS NULL OR death_audits_conducted_pct BETWEEN 0 AND 1),
    staff_trained_on_protocol_pct NUMERIC(6, 5) CHECK (staff_trained_on_protocol_pct IS NULL OR staff_trained_on_protocol_pct BETWEEN 0 AND 1),
    quality_improvement_active BOOLEAN,
    supervision_visits_quarterly INTEGER CHECK (supervision_visits_quarterly IS NULL OR supervision_visits_quarterly >= 0),
    hmis_reporting_completeness NUMERIC(6, 5) CHECK (hmis_reporting_completeness IS NULL OR hmis_reporting_completeness BETWEEN 0 AND 1),
    bag_mask_ventilation_competency NUMERIC(6, 5) CHECK (bag_mask_ventilation_competency IS NULL OR bag_mask_ventilation_competency BETWEEN 0 AND 1),
    thermal_care_protocol_compliance NUMERIC(6, 5) CHECK (thermal_care_protocol_compliance IS NULL OR thermal_care_protocol_compliance BETWEEN 0 AND 1),
    infection_prevention_score NUMERIC(6, 5) CHECK (infection_prevention_score IS NULL OR infection_prevention_score BETWEEN 0 AND 1),
    source_upload_id UUID REFERENCES uploads(id),
    source_row_number INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, country_code, facility_id)
        REFERENCES facilities (tenant_id, country_code, facility_id),
    UNIQUE (tenant_id, country_code, facility_id, effective_start_month, effective_end_month)
);

CREATE TABLE workforce_facility (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    country_code CHAR(3) NOT NULL DEFAULT 'RWA',
    facility_id TEXT NOT NULL,
    effective_start_month DATE,
    effective_end_month DATE,
    total_nurses INTEGER CHECK (total_nurses IS NULL OR total_nurses >= 0),
    neonatal_trained_nurses INTEGER CHECK (neonatal_trained_nurses IS NULL OR neonatal_trained_nurses >= 0),
    midwives INTEGER CHECK (midwives IS NULL OR midwives >= 0),
    obstetricians INTEGER CHECK (obstetricians IS NULL OR obstetricians >= 0),
    pediatricians INTEGER CHECK (pediatricians IS NULL OR pediatricians >= 0),
    neonatologists INTEGER CHECK (neonatologists IS NULL OR neonatologists >= 0),
    anesthetists INTEGER CHECK (anesthetists IS NULL OR anesthetists >= 0),
    last_neonatal_training_date DATE,
    staff_per_delivery_2024 NUMERIC(8, 4),
    night_shift_coverage availability_status,
    source_upload_id UUID REFERENCES uploads(id),
    source_row_number INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, country_code, facility_id)
        REFERENCES facilities (tenant_id, country_code, facility_id),
    UNIQUE (tenant_id, country_code, facility_id, effective_start_month, effective_end_month)
);

CREATE TABLE operations_facility (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    country_code CHAR(3) NOT NULL DEFAULT 'RWA',
    facility_id TEXT NOT NULL,
    effective_start_month DATE,
    effective_end_month DATE,
    avg_referral_time_hrs NUMERIC(8, 2),
    referrals_out_monthly INTEGER CHECK (referrals_out_monthly IS NULL OR referrals_out_monthly >= 0),
    referrals_in_monthly INTEGER CHECK (referrals_in_monthly IS NULL OR referrals_in_monthly >= 0),
    oxygen_cylinders_available INTEGER CHECK (oxygen_cylinders_available IS NULL OR oxygen_cylinders_available >= 0),
    oxygen_concentrators INTEGER CHECK (oxygen_concentrators IS NULL OR oxygen_concentrators >= 0),
    oxygen_plant BOOLEAN,
    ambulance_available BOOLEAN,
    kangaroo_care_practiced availability_status,
    essential_drugs_stockouts_days INTEGER CHECK (essential_drugs_stockouts_days IS NULL OR essential_drugs_stockouts_days >= 0),
    antibiotics_available availability_frequency,
    surfactant_available BOOLEAN,
    referral_feedback_rate NUMERIC(6, 5) CHECK (referral_feedback_rate IS NULL OR referral_feedback_rate BETWEEN 0 AND 1),
    source_upload_id UUID REFERENCES uploads(id),
    source_row_number INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, country_code, facility_id)
        REFERENCES facilities (tenant_id, country_code, facility_id),
    UNIQUE (tenant_id, country_code, facility_id, effective_start_month, effective_end_month)
);

CREATE TABLE data_quality_issues (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    country_code CHAR(3) NOT NULL DEFAULT 'RWA',
    facility_id TEXT,
    reporting_month DATE,
    dataset_kind dataset_kind,
    issue_type TEXT NOT NULL,
    severity issue_severity NOT NULL,
    affected_column TEXT,
    observed_value TEXT,
    expected_rule TEXT NOT NULL,
    suggested_action TEXT NOT NULL,
    source_upload_id UUID REFERENCES uploads(id),
    source_row_number INTEGER,
    is_overridden BOOLEAN NOT NULL DEFAULT false,
    override_reason TEXT,
    overridden_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_data_quality_issues_facility_month
    ON data_quality_issues (tenant_id, country_code, facility_id, reporting_month);

CREATE INDEX ix_data_quality_issues_severity ON data_quality_issues (severity);

CREATE TABLE bulletin_runs (
    id UUID PRIMARY KEY,
    batch_id UUID REFERENCES upload_batches(id),
    tenant_id TEXT NOT NULL DEFAULT 'default',
    country_code CHAR(3) NOT NULL DEFAULT 'RWA',
    reporting_period_start DATE NOT NULL,
    reporting_period_end DATE NOT NULL,
    input_upload_ids UUID[] NOT NULL,
    validation_status TEXT NOT NULL,
    metrics_version TEXT,
    ai_summary_version TEXT,
    pdf_path TEXT,
    excel_path TEXT,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE TABLE report_ready_metrics (
    id BIGSERIAL PRIMARY KEY,
    bulletin_run_id UUID REFERENCES bulletin_runs(id),
    tenant_id TEXT NOT NULL DEFAULT 'default',
    country_code CHAR(3) NOT NULL DEFAULT 'RWA',
    metric_version TEXT NOT NULL,
    reporting_period_start DATE NOT NULL,
    reporting_period_end DATE NOT NULL,
    geography_level TEXT NOT NULL,
    geography_id TEXT NOT NULL,
    facility_id TEXT,
    metric_name TEXT NOT NULL,
    metric_value NUMERIC,
    metric_unit TEXT,
    numerator NUMERIC,
    denominator NUMERIC,
    source_table TEXT NOT NULL,
    source_fields TEXT[] NOT NULL,
    calculation_rule TEXT NOT NULL,
    trace_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_report_ready_metrics_period_metric
    ON report_ready_metrics (tenant_id, country_code, reporting_period_start, reporting_period_end, metric_name);

CREATE INDEX ix_report_ready_metrics_geo
    ON report_ready_metrics (tenant_id, country_code, geography_level, geography_id);
