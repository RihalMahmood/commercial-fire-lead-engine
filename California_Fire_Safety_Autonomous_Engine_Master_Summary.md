# California Fire Safety Lead Generation Engine: Master Architecture & Conversation Record

**System Version:** 2.0 (Autonomous Cloud-Native)  
**Target Market:** City of Los Angeles & Greater Los Angeles County (Multi-City Scalable)  
**Repository:** `commercial-fire-lead-engine` (GitHub: `RihalMahmood/commercial-fire-lead-engine`)  
**Database:** Supabase PostgreSQL (`muzchgwccbbvdokrkjhd.supabase.co`)  
**Primary Enrichment:** BatchData County Title Deed Skip-Trace (@ $0.12 / Verified Match)  
**Execution Runtime:** 24/7 Headless Cloud Automation via GitHub Actions  

---

## Executive Summary & System Objectives

The **California Fire Safety Lead Generation Engine** identifies commercial properties facing active municipal fire code deficiencies, inspection citations, and mandatory compliance deadlines from the City of Los Angeles Department of Building & Safety (LADBS).

### Core Problem Solved (The "Demand Paradox")
* Commercial fire safety is mandated by state and federal law (NFPA 13, 25, 72, California Title 19). Non-compliant building owners face compounding daily municipal fines ($250–$1,000/day), insurance policy cancellation, and revocation of the Certificate of Occupancy (CofO).
* Fire protection contractors ($4M–$15M annual revenue) are bogged down in low-margin (<10%) General Contractor bids where payments are delayed 60–90 days.
* **Our Solution:** Identify high-urgency, non-compliant commercial building owners, extract direct decision-maker contact details (deed owners, phone numbers, emails), and generate daily qualified outreach queues for direct-to-owner, high-margin (50%–70%) compliance repairs.

---

## 1. Supabase Database Schema & Data Flow Architecture

The system operates across six specialized tables to guarantee separation between operational queues, permanent historical archives, and anti-spam suppression:

```
[ LADBS SODA APIs ]
(Past 24h Violations)
        │
        ▼
┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│   daily_fire_violations_24h     │ ───►  │    raw_municipal_violations     │
│   (24h Operational Inbox)       │       │    (Permanent Ingestion Archive)│
└─────────────────────────────────┘       └─────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│   commercial_fire_leads         │  <--- Stage 2: Rapid AI Life-Safety Triage
│   (Master Qualified CRM Table)  │  <--- Stage 3: NFPA Scope & Job Valuation
└─────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐
│ central_sent_suppression_db     │  <--- Stage 5: 90-Day Anti-Spam Cooldown
│ (90-Day Deduplication Guard)    │
└─────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│   daily_commercial_leads_24h    │       │     master_enriched_leads       │
│   (Today's Active Outreach)     │ ───►  │     (Permanent Enriched DB)     │
└─────────────────────────────────┘       └─────────────────────────────────┘
```

### Table Roles & Retention Rules:
1. `daily_fire_violations_24h`: Ephemeral 24-hour inbox. Flushed and refreshed every 24 hours to hold only the fresh daily batch.
2. `raw_municipal_violations`: Permanent write-only ledger. Preserves every raw JSON payload extracted from LADBS. Old records are never lost.
3. `commercial_fire_leads`: Permanent qualified CRM storing all properties passing fire safety criteria, with mapped NFPA scopes and estimated contract values.
4. `central_sent_suppression_database`: Prevents contacting any landlord, property manager, or parcel emailed within the preceding 90 days.
5. `daily_commercial_leads_24h`: Active daily dispatch queue containing only today’s newly qualified, enriched, and unsuppressed leads.
6. `master_enriched_leads`: Permanent master database of all cumulative enriched commercial leads.

---

## 2. Technical Investigation & Root-Cause Troubleshooting

During system calibration across the pilot dataset (15 commercial properties), two critical edge cases were identified and solved:

### Issue A: Missing Executives for 100 N Central Ave
* **Symptom:** In earlier tests, 100 N Central Ave was recognized as the *Japanese American National Museum (JANM)*, yielding top executive contacts. In unified test runs, these contacts were blank.
* **Root Cause:** The discovery helper queried Google Serper but evaluated only `knowledgeGraph` and `places` response blocks. For this address, Google returned JANM inside the `organic` web results array. Because `kg` and `places` were empty, the script assumed no entity was present and bypassed discovery.
* **Resolution:** Evaluated all response blocks (`knowledgeGraph`, `places`, and `organic` titles) to ensure proper entity resolution.

### Issue B: The 4 Unmatched BatchData Deed Rows
* **Symptom:** BatchData skip-tracing initially matched 11 of 15 properties, leaving 4 unmatched:
  1. `20401 W VENTURA BLVD`
  2. `8036 N RHODES AVE`
  3. `14208 W CHANDLER BLVD`
  4. `13956 W AUBREY ROAD`
* **Root Cause (Municipal vs. County Indexing Mismatch):**
  * LADBS municipal inspection records (`data.lacity.org`) do not provide 5-digit ZIP codes. The initial script defaulted missing ZIPs to `city: "Los Angeles"`.
  * Los Angeles County Tax Assessor and Title Deed records index properties in the San Fernando Valley and the Westside under their specific **Postal Community Names** (Woodland Hills, North Hollywood, Sherman Oaks, Beverly Hills) or 5-digit postal ZIP codes. Querying `"Los Angeles"` caused County Deed lookups to fail.
  * For Aubrey Road, LADBS records prepended an erroneous `"W"` directional prefix (`13956 W Aubrey Rd` instead of `13956 Aubrey Rd`).
* **Resolution (Zero-Dependency Address Normalizer):**
  We implemented an internal address router (`normalize_la_address`) that cleans unit noise, strips erroneous directionals, and routes San Fernando Valley / Westside corridors to their proper postal communities without requiring any external paid API.
* **Live Verification Result:** **15 out of 15 matched (100.0% match rate)** at $0.12/match ($1.80 total cost).

---

## 3. The Pure BatchData Contact Enrichment Architecture

To ensure operational reliability, reduce external failure points, and eliminate unnecessary recurring costs, Serper and Floqer were decoupled from the automated pipeline. The production pipeline uses **BatchData Deed Skip-Tracing** as its single, verified contact authority:

### Output Schema & Data Fields:
Every lead in the final export contains:
* `lead_id`: Unique Supabase identifier
* `case_number`: Municipal permit/case reference number
* `property_address`: Full physical site address
* `deed_owner_name`: Legal title holder (Individual, LLC, or Family Trust)
* `primary_phone`: Direct primary contact phone number
* `phone_type`: Carrier line classification (`Mobile`, `Land Line`, `VoIP`)
* `all_phones`: Full semicolon-delimited list of all verified phone numbers with line tags
* `owner_email`: Official county deed assessor email address
* `violation_summary`: Plain-English diagnosis of the fire inspection deficiency
* `mapped_trade_service`: Specific NFPA technical repair scope
* `estimated_job_value_usd`: Algorithmically calculated contract valuation ($2,500 – $15,000+)
* `stakeholder_responsibility`: Legal party responsible (`Commercial Landlord` vs `Commercial Tenant`)
* `enrichment_source`: BatchData County Deed
* `deep_link_verification_url`: Direct permalink to the municipal city record

---

## 4. Verified Pilot Results (15 Leads / 100% Match Rate)

| Property Address | Deed Owner Name | Primary Phone | Line Type | County Email | Estimated Value |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `6018 S BRYNHURST AVE` | Adrienne E Natho | `559-513-9657` | Mobile | `adriennenatho0@gmail.com` | $4,500.00 |
| `1625 W 57TH ST` | Alicia Emma Lopez | `323-495-2216` | Mobile | *(5 verified numbers)* | $6,200.00 |
| `308 N BOWLING GREEN WAY` | Alexandra Gordon Cowie | `310-948-3684` | Mobile | `acowie@earthlink.net` | $4,500.00 |
| `20401 W VENTURA BLVD` | Dorothy E Barton Trust | `818-222-6801` | Land Line | *(5 verified numbers)* | $8,500.00 |
| `2401 S CARMONA AVE` | Matthew C Lyman | `310-614-3586` | Mobile | `mlyman@tendergreens.com` | $4,500.00 |
| `100 N CENTRAL AVE` | Vedette P Philip | `347-928-3659` | Mobile | `vphilip@oxy.edu` | $6,200.00 |
| `247 E 97TH ST` | Frank A Johnson | `858-538-2957` | Land Line | *(County Deed)* | $4,500.00 |
| `3837 W EVANS ST` | Shelley Lee Wong | `213-247-6049` | Mobile | `billtcwong@att.net` | $6,200.00 |
| `14208 W CHANDLER BLVD` | Brian Elan Lee | `206-323-9921` | Mobile | `humbirdj55@aol.com` | $6,200.00 |
| `13956 W AUBREY ROAD` | Edward G Redlich | `323-854-5483` | Mobile | `edmets@aol.com` | $4,500.00 |
| `564 N PLYMOUTH BLVD` | Ellen D Reede | `917-693-3198` | Mobile | `stevereede@aol.com` | $4,500.00 |
| `8036 N RHODES AVE` | Michael Anthony Carter | `818-266-4050` | Mobile | `m9carterlf@gmail.com` | $6,200.00 |
| `10375 W WILSHIRE BLVD` | Timothy A Te Childs | `212-319-9600` | Mobile | `bway.guy@gmail.com` | $8,500.00 |
| `2130 N MANDEVILLE CANYON RD`| Michael S Gould | `818-913-3545` | Mobile | `juleegould@gmail.com` | $6,200.00 |
| `217 W 42ND PL` | Karen Lynn Cass | `323-234-3661` | Land Line | `becass45@aol.com` | $6,200.00 |

* **Total Opportunities Value:** $87,400.00  
* **Total Skip-Trace Cost:** $1.80  
* **Unmatched / VA Review Queue:** 0  

---

## 5. 24/7 Cloud Automation Architecture (GitHub Actions)

The workflow runs entirely on GitHub Actions cloud infrastructure without requiring local machine uptime or active agent sessions:

### Workflow Specification (`.github/workflows/daily_fire_ingest.yml`):
* **Execution Trigger:** Daily Cron at `0 6 * * *` (6:00 AM UTC / 11:00 PM Pacific Time).
* **Manual Override:** `workflow_dispatch` button in the GitHub Actions dashboard.
* **Environment Secrets Required:**
  1. `SUPABASE_URL`: Live database connection endpoint
  2. `SUPABASE_SERVICE_ROLE_KEY`: Administrative database service key
  3. `BATCHDATA_API_KEY`: Authentication for deed skip-tracing API
* **Output Artifacts:** Every run attaches `Daily-Fire-Violations-24h.zip` containing:
  * `exports/LA_Enriched_Fire_Leads_YYYY_MM_DD.csv`
  * `exports/LA_Daily_VA_Review_Sheet.csv`
  * `LA_Daily_Fire_Violations_24h.csv`

---

## 6. Multi-City Handover Blueprint

To deploy this engine for any other municipality (e.g. San Francisco, San Diego, Chicago, Dallas):

### Step 1: Repository Clone & Dependencies
```bash
git clone https://github.com/RihalMahmood/commercial-fire-lead-engine.git
cd commercial-fire-lead-engine
pip install requests supabase python-dotenv
```

### Step 2: Configure Environment
Add `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `BATCHDATA_API_KEY` to `.env` (or GitHub Secrets).

### Step 3: Update Municipal Data Ingestion Endpoint
In `run_daily_pipeline.py`:
1. Change `source_city` (e.g., `"san_francisco"`).
2. Point SODA URL to target city portal (e.g., `data.sfgov.org`).
3. Map local field names for address, date, and violation description.

### Step 4: Run Historical 60-Day Backlog
Pull the last 60 days of violations with a single command:
```bash
python run_daily_pipeline.py --days 60
```

### Step 5: Automate 24-Hour Runs
* **Cloud Mode:** Enable GitHub Actions workflow.
* **Local Server Mode:**
  ```cron
  0 6 * * * cd /path/to/engine && python3 run_daily_pipeline.py --days 1 >> daily_run.log 2>&1
  ```

---

## Summary Checklist

| Component | Status | Verification Detail |
| :--- | :--- | :--- |
| **Municipal Data Ingestion** | ✅ Complete | SODA endpoints `u82d-eh7z` & `9w5z-rg2h` verified |
| **Rapid AI Triage** | ✅ Complete | NFPA scope classification & trade valuation live |
| **90-Day Cooldown Suppression** | ✅ Complete | Central suppression deduplication active |
| **BatchData Skip-Trace** | ✅ Complete | 15/15 (100%) deed match rate verified at $0.12/match |
| **Address Normalizer** | ✅ Complete | Zero external dependencies; local postal routing |
| **Cloud Automation** | ✅ Complete | GitHub Actions cron active (`0 6 * * *`) |
| **Multi-City Readiness** | ✅ Complete | `--days 60` flag and generic ingestion ready |
