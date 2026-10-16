-- ==============================================================================
-- CALIFORNIA FIRE SAFETY LEAD GENERATION ENGINE (LOS ANGELES 2.0)
-- Master Supabase / PostgreSQL Schema Definition
-- ==============================================================================

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ------------------------------------------------------------------------------
-- TABLE 1: raw_municipal_violations
-- Ingests 100% RAW, unfiltered records directly from city SODA APIs.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_municipal_violations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_city VARCHAR(50) NOT NULL DEFAULT 'los_angeles',
    source_endpoint_id VARCHAR(50) NOT NULL, -- e.g., 'u82d-eh7z', '9w5z-rg2h'
    source_dataset_name VARCHAR(150),
    case_or_permit_number VARCHAR(100) NOT NULL,
    property_address TEXT NOT NULL,
    zip_code VARCHAR(20),
    apn VARCHAR(50),                         -- Assessor Parcel Number
    council_district VARCHAR(20),
    violation_date DATE,
    status_desc VARCHAR(100),
    raw_violation_text TEXT,
    deep_link_verification_url TEXT NOT NULL,
    raw_payload JSONB,                       -- Complete original JSON from SODA API
    ingested_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    triage_status VARCHAR(50) DEFAULT 'PENDING' -- PENDING, TRIAGED_FIRE, TRIAGED_NON_FIRE, ERROR
);

-- Indexing for fast deduplication & lookup
CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_violations_unique_case 
ON raw_municipal_violations (source_city, source_endpoint_id, case_or_permit_number);

CREATE INDEX IF NOT EXISTS idx_raw_violations_address ON raw_municipal_violations (property_address);
CREATE INDEX IF NOT EXISTS idx_raw_violations_apn ON raw_municipal_violations (apn);
CREATE INDEX IF NOT EXISTS idx_raw_violations_triage_status ON raw_municipal_violations (triage_status);


-- ------------------------------------------------------------------------------
-- TABLE 2: commercial_fire_leads
-- Stores verified, triaged, and enriched commercial fire leads.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS commercial_fire_leads (
    lead_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_violation_id UUID REFERENCES raw_municipal_violations(id) ON DELETE SET NULL,
    
    -- Municipal Reference
    source_city VARCHAR(50) NOT NULL DEFAULT 'los_angeles',
    case_number VARCHAR(100),
    property_address TEXT NOT NULL,
    zip_code VARCHAR(20),
    apn VARCHAR(50),
    deep_link_verification_url TEXT NOT NULL,
    
    -- Phase 1 Triage Classifications
    intent_category VARCHAR(50),             -- 'Intent 1: Fire Watch', 'Intent 2: NOV', etc.
    property_type VARCHAR(50),               -- 'Commercial', 'Industrial', 'Multi-Family'
    is_fire_violation BOOLEAN DEFAULT TRUE,
    
    -- Phase 2 Deep Stakeholder Analysis
    stakeholder_responsibility VARCHAR(50),   -- 'Commercial Landlord', 'Commercial Tenant', 'Shared'
    damage_diagnosis TEXT,
    required_nfpa_repair_scope TEXT,
    estimated_job_value_usd NUMERIC(12, 2) DEFAULT 0.00,
    
    -- Landlord Entity (From Assessor + CA SOS)
    landlord_company_name TEXT,
    landlord_entity_type VARCHAR(50),
    landlord_managing_member TEXT,
    landlord_corporate_address TEXT,
    
    -- Tenant Entity (From Business Tax Registry / Floqer)
    tenant_business_name TEXT,
    tenant_industry VARCHAR(50),
    tenant_manager_name TEXT,
    
    -- Enriched Contacts (BatchData + Floqer + Verisium)
    enriched_contacts JSONB DEFAULT '[]'::jsonb, 
    -- Format: [{"name": "...", "role": "Owner/Tenant", "email": "...", "phone": "...", "email_status": "Valid", "source": "BatchData/Floqer"}]
    
    -- Pipeline Status
    lead_status VARCHAR(50) DEFAULT 'QUALIFIED', -- QUALIFIED, ENRICHED, READY_FOR_DISPATCH, SUPPRESSED, DISPATCHED
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_commercial_leads_address ON commercial_fire_leads (property_address);
CREATE INDEX IF NOT EXISTS idx_commercial_leads_status ON commercial_fire_leads (lead_status);
CREATE INDEX IF NOT EXISTS idx_commercial_leads_apn ON commercial_fire_leads (apn);


-- ------------------------------------------------------------------------------
-- TABLE 3: central_sent_suppression_database
-- Master deduplication and cooldown tracking (prevents over-emailing).
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS central_sent_suppression_database (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    lead_id UUID REFERENCES commercial_fire_leads(lead_id) ON DELETE SET NULL,
    property_address TEXT NOT NULL,
    recipient_name VARCHAR(150),
    recipient_email VARCHAR(255) NOT NULL,
    recipient_role VARCHAR(50),              -- 'Landlord', 'Tenant', 'Facility Director'
    campaign_name VARCHAR(150),
    platform_message_id VARCHAR(150),        -- PlusVibe send ID
    sent_timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    cooldown_expiry TIMESTAMP WITH TIME ZONE DEFAULT (NOW() + INTERVAL '90 days')
);

CREATE INDEX IF NOT EXISTS idx_suppression_email ON central_sent_suppression_database (recipient_email);
CREATE INDEX IF NOT EXISTS idx_suppression_address ON central_sent_suppression_database (property_address);
CREATE INDEX IF NOT EXISTS idx_suppression_cooldown ON central_sent_suppression_database (cooldown_expiry);
