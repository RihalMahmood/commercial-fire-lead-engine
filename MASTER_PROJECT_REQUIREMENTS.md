# MASTER PROJECT REQUIREMENTS & SYSTEM SPECIFICATION
## California Fire Safety Lead Generation Engine (Los Angeles 2.0)

> **Document Status:** Active & Continuously Updated  
> **Last Updated:** October 2026  
> **Target Metro Area:** City of Los Angeles & Greater Los Angeles County  
> **User Role:** Cold Email & Lead Generation Specialist  
> **Antigravity Role:** Lead Architect, Data Engineer & System Consultant  

---

## 1. Executive Mission & Business Architecture

### 1.1 The Core Business Model
* **Our Role:** We are cold email specialists and database intelligence architects.
* **Our Clients:** Independent, mid-sized fire safety and life-safety contracting companies ($4M to $15M annual revenue, 10 to 40 technicians) who have dedicated service estimators on payroll.
* **The End Customers (Leads):** Commercial property managers, building owners, facility directors, and asset managers whose commercial buildings have active, documented compliance triggers or emergencies.
* **The Offer:** We book qualified on-site walkthrough appointments directly onto the fire contractor's estimator/service calendar (Pay-Per-Appointment or Base + Performance model).

### 1.2 The "Demand Paradox" & Service Selection Rule
* **The Reality:** Fire protection contractors do **not** struggle with total demand because life safety is mandated by law (NFPA codes, municipal fire ordinances). Contractors are actively constrained by labor shortages and overwhelmed with low-bid construction work.
* **The Rule of Exclusion:** We strictly **avoid** low-bid new construction projects from General Contractors (GCs) (margins under 10%, slow 90-day pay cycles) and single-family residential properties.
* **The Target ("The Golden Goose"):** We exclusively target **direct-to-owner, high-margin deficiency remediation, violation abatement, and emergency repairs (50% to 70% profit margins, immediate credit card/Net-15 payment)**.

---

## 2. Intent-to-Service Mapping Matrix

The engine operates across **4 Core High-Urgency Buying Intents**, each mapped to specific trade services provided by our fire protection clients:

| Intent Category | Real-World Trigger on Building | Mapped Fire Protection Services | Decision-Maker Pain / Urgency |
| :--- | :--- | :--- | :--- |
| **Intent 1: Active Fire Watch & System Impairments** | Sprinkler main burst, defective alarm panel, or offline system. Building legally mandated to post 24/7 human patrols. | • 24/7 Emergency Impairment Repair Dispatch<br/>• Riser / Valve / Piping Replacement<br/>• Fire Alarm Panel Restoration<br/>• Official Fire Watch Lift Certification with AHJ | **CRITICAL (24–48 hours)**<br/>Owner bleeding $1,500–$3,500/day in security guard fees. |
| **Intent 2: Notice of Violation (NOV) & Fire Code Citations** | City Fire Marshal / LADBS issued an official citation or physical Red-Tag for failed equipment or missing safety checks. | • Code Deficiency Remediation<br/>• Backflow Preventer Overhaul & Testing<br/>• 5-Year Title 19 / NFPA 25 Internal Pipe Inspection<br/>• Official City Proof of Abatement Sign-Off | **HIGH (14–30 day deadline)**<br/>Daily escalating fines ($250–$1,000/day), court summons, loss of insurance. |
| **Intent 3: Overdue Municipal Portals & Reg 4 Testing** | Annual testing deadline lapsed in municipal tracking software (Brycer / The Compliance Engine) or LAFD Chief's Reg 4 registry. | • Annual NFPA 25 / 72 Complete System Certification<br/>• Direct Digital Portal Upload to City Database<br/>• Deficiency Upsell & Multi-Year Maintenance Contract | **MODERATE-HIGH (30 days)**<br/>Pending formal city citation and enforcement action. |
| **Intent 4: Change of Occupancy & Commercial Alterations** | Building sold, tenant remodel, warehouse high-pile racking added. Existing NFPA 13 hydraulic calculation is legally void. | • NFPA 13 Hydraulic Recalculation & Engineering Review<br/>• Sprinkler Head Relocation & TI Drops<br/>• High-Pile Storage Upgrades (ESFR)<br/>• Final City Inspection Walkthrough for CofO | **HIGH (Project Blocker)**<br/>City holds Certificate of Occupancy (CofO); tenant cannot legally open or pay rent. |

---

## 3. Mandatory Data Source Standards & Zero-Paywall Policy

### 3.1 100% Free Public Government Data (Strict Rule)
* **Zero Paywalls:** Strictly **NO** paid third-party data platforms (no Apollo, ZoomInfo, Seamless, etc.).
* **Authenticity:** All leads must originate directly from official municipal, county, or state government open-data portals, building department registries, and fire prevention records.
* **Multi-Database Corroboration:** Cross-reference multiple public feeds to validate the intent (e.g., matching a failed inspection record with an open code enforcement case).

### 3.2 Target Public Repositories (Los Angeles Blueprint)
1. **LADBS Open Data (Socrata SODA API):**
   * Code Enforcement Open Cases & Substandard Buildings (`u82d-eh7z`)
   * Building & Safety Inspections Feed (`9w5z-rg2h`)
   * Building Permits Issued (`pi9x-tg5x`)
   * Building Permits Submitted (`ps4h-4w44`)
   * Mechanical & Fire Sprinkler Permits Issued (`67is-svtd`)
   * Mechanical & Fire Sprinkler Permits Submitted (`9rag-xmmd`)
   * Certificate of Occupancy (CofO) Feed (`3f9m-afei`)
2. **LAFD Fire Prevention Bureau & Chief’s Regulation 4 (Reg 4):**
   * Mandated 15-system life safety testing roster and non-compliance citations.
3. **LA County Assessor Open Portal:**
   * Free parcel lookup matching APN / Address to Legal Entity / LLC Name on title deed.
4. **California Secretary of State (bizfile Online):**
   * Free corporate filings lookup to extract Managing Members, Officers, and Registered Agents of property-owning LLCs.

---

## 4. Specific Technical & Extraction Requirements

### 4.1 Granular Verification URLs for Every Lead
* For **every single lead extracted**, the record must contain a direct, clickable **Data Source Verification URL**.
* **Standard:** It cannot be just a homepage domain (e.g., `data.lacity.org`). It must point directly to the specific record inside the database (e.g., LADBS permit detail query, SODA API resource permalink, or municipal inspection report) proving the exact citation, permit number, or violation.

### 4.2 Timeframe Relevance per Intent
Data from years ago is worthless. The extraction engine must enforce strict, intent-appropriate temporal boundaries:

| Intent | Target Timeframe Window | Rationale |
| :--- | :--- | :--- |
| **Intent 1: Fire Watch & Impairments** | **Past 7 to 14 days** (Max 30 days active) | Fire watch is an immediate crisis. After 30 days, it is either resolved or shut down. |
| **Intent 2: Notice of Violations (NOV)** | **Past 30 to 60 days** (Active/Unabated) | Matches the official 15-to-30-day city cure window plus follow-up grace period. |
| **Intent 3: Overdue Inspections & Portals** | **Past 30 to 90 days overdue** | Target owners right as automated city warning letters escalate before court action. |
| **Intent 4: Change of Occupancy / Alterations** | **Past 30 to 90 days** (Active permit / CofO pending) | Captures the active build-out window before final inspection sign-off. |

### 4.3 Rigorous Extraction Engineering (No Shortcuts)
* **Unbounded Pagination:** The scraper/pipeline must loop through paginated endpoints until all qualifying records are retrieved. No arbitrary `LIMIT 1000` truncations.
* **No Truncation or Query Caps:** Handle complete datasets gracefully using robust cursor/offset loops.
* **No Shortcut Compromises:** The system must never truncate data, skip fields, or cut corners to save tokens or compute time. Thoroughness and accuracy are non-negotiable.

### 4.4 Strict Commercial / Multi-Family Filtering
* **Strict Inclusion:** Commercial zones (C1, C2, C4, CM), Industrial/Manufacturing zones (M1, M2, M3), and Multi-Family Residential (10+ units, R3, R4, R5).
* **Strict Exclusion:** Single-Family Residential (R1, RS, RE), Duplexes/Triplexes, and Accessory Dwelling Units (ADUs).

---

## 5. The 3-Step Intent Extraction & Classification Pipeline

For every intent we target, the workflow executes systematically in three distinct, rigorous stages:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ STEP 1: CATALOG & RAW TIME-BOUND EXTRACTION                                            │
│ • Identify all public municipal databases/feeds indicating the targeted intent         │
│ • Ingest 100% RAW, unfiltered datasets for the specific intent timeframe               │
│ • No premature keyword cuts; comprehensive row-by-row violation/record analysis        │
└────────────────────────────────────────┬───────────────────────────────────────────────┘
                                         │
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ STEP 2: ROW-BY-ROW FIRE & INTENT FILTERING                                             │
│ • Inspect every single row across all fields (description, code, permit type, status) │
│ • Discard non-fire / non-life-safety records (e.g. general zoning, trash, noise)      │
│ • Retain only verified fire safety violations or genuine intent signals                │
└────────────────────────────────────────┬───────────────────────────────────────────────┘
                                         │
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ STEP 3: GRANULAR PROPERTY & RESPONSIBILITY CLASSIFICATION                              │
│ • Analyze zoning, use codes, work scope, tenant names, and building attributes         │
│ • Classify into: Single-Family, Multi-Family (10+ units), or Commercial                │
│ • In Commercial, determine Landlord/Owner Issue vs. Tenant Issue                      │
│ • Output dedicated column: [Property_Responsibility_Classification]                    │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### Detailed Pipeline Mechanics:

#### Step 1: Catalog & Raw Time-Bounded Extraction
* **Scope:** We isolate and work on **one intent at a time**.
* **Cataloging:** Enumerate every authentic government database, registry, and public feed in the target municipality that tracks this intent.
* **Extraction:** Ingest the **raw, complete dataset** bounded strictly by the intent's defined timeframe (e.g., past 30–60 days for NOV, past 7–14 days for Fire Watch).
* **Row-by-Row Baseline:** Preserve all original columns and populate a direct verification deep-link URL for every single row.

#### Step 2: Row-by-Row Fire & Intent Filtering
* **Analysis:** Evaluate each row to determine whether the record involves a genuine life-safety or fire protection issue.
* **Separation:** General municipal code issues (e.g., overgrown weeds, unauthorized exterior sign, trash accumulation, plumbing drain clog, general building structural issues) are cleanly separated and filtered out.
* **Retention:** Only records directly related to fire sprinklers, fire alarms, smoke control, backflow prevention, fire pumps, emergency egress, kitchen hood suppression, or hazardous life-safety conditions are preserved.

#### Step 3: Granular Property & Responsibility Classification
To know whom to contact and what contract to pitch, the AI analyzes all fields (zoning codes, use descriptions, property names, and work text) and creates a dedicated classification column:
* **`Commercial Landlord / Building Owner`:** The issue pertains to the central building life-safety infrastructure (e.g., central fire riser, main backflow assembly, fire pump, building-wide fire alarm panel, 5-year Title 19 inspection, structural standpipes). *Pitch: Direct building owner compliance contract.*
* **`Commercial Tenant`:** The issue is isolated to a specific tenant space or interior leasehold (e.g., commercial restaurant kitchen hood suppression, retail tenant improvement walls blocking sprinkler throw, tenant build-out fire permit, warehouse tenant rack configuration). *Pitch: Tenant improvement contractor / commercial tenant compliance.*
* **`Multi-Family Residential (10+ Units)`:** Apartment complexes, senior living facilities, residential mid-rises. *Pitch: Property management firm / HOA management.*
* **`Single-Family Residential / Duplex / ADU`:** Flagged for exclusion (low margin, out of scope for our mid-sized commercial clients).

---

## 5. Streamlined 2-Phase AI Processing & Multi-Party Enrichment Pipeline

Based on direct executive alignment (Conversation.txt), the workflow eliminates intermediate friction and operates in a streamlined, two-phase AI structure coupled with high-deliverability verification:

```
[ GitHub Actions (Cloud Cron) ──► Fetches Raw Updates into Supabase (Zero VPS) ]
                                      │
                                      ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ PHASE 1: ZERO-SEARCH RAPID CLASSIFICATION (High-Speed Ingestion)                       │
│ • Input: Full payload of raw updated records from municipal SODA / open-data APIs      │
│ • Execution: Antigravity Prompt #1 running WITHOUT external search (zero latency)      │
│ • Tasks:                                                                               │
│     1. Fire Hazard Filter: Is it Fire / Life-Safety vs. Non-Fire standard municipal?   │
│     2. Property Triage: Commercial (Retail, Office, Warehouse, MFR 10+) vs. SFR/Duplex│
│ • Output Routing:                                                                      │
│     ► Pure Residential (SFR/Duplex) ──► Routed to BatchData Residential Stream         │
│     ► Commercial & Multi-Family Fire Records ──► Advanced to Phase 2                   │
└────────────────────────────────────────┬───────────────────────────────────────────────┘
                                         │
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ PHASE 2: DEEP STAKEHOLDER MAPPING & ENTITY RESOLUTION (Web Search ENABLED)             │
│ • Input: Qualified Commercial Fire Records from Phase 1                                │
│ • Execution: Antigravity Prompt #2 with WEB SEARCH ENABLED                             │
│ • Tasks:                                                                               │
│     1. Identify the Landlord / Property Owner Entity (Holding Co, Deed, Asset Manager) │
│     2. Identify the Commercial Tenant / Business Occupants (Operating retail/dining)   │
│     3. Map Legal Responsibility: Landlord Issue (Central Riser/Pump) vs. Tenant Issue  │
│     4. Enumerate all relevant decision-makers across both entities                     │
└────────────────────────────────────────┬───────────────────────────────────────────────┘
                                         │
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ PHASE 3: MULTI-TOOL CONTACT ENRICHMENT & DEDUPLICATION                                 │
│ • BatchData: LLC corporate veil piercing & property owner skip-tracing                 │
│ • Floqer: B2B corporate people search (Director of Facilities, Property Managers)      │
│ • Verisium: Email extraction & real-time SMTP inbox deliverability verification        │
│ • Master Deduplication: Checks Central Sent Suppression DB (drops prior 90-180d sends) │
│ • Execution Rule: Outreach ONLY launches to VERIFIED emails; all risky/invalid dropped │
└────────────────────────────────────────┬───────────────────────────────────────────────┘
                                         │
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ PHASE 4: MULTI-PRONGED OUTREACH & DAILY FREELANCER QA                                  │
│ • PlusVibe: Deploys simultaneous sequences to Landlord (fines) & Tenant (disruption)   │
│ • Daily Review Sheet: Unmatched or partial records routed to Freelancer Desk (24h SLA) │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Automation Infrastructure & Cloud Scheduling

* **Cloud Automation Engine:** **GitHub Actions** (100% free, 2,000 monthly compute minutes, runs scheduled Python cron workflows 24/7 with zero VPS server costs).
* **Database & Webhook Hub:** **Supabase** (PostgreSQL cloud database storing master records, triggers, and suppression lists).
* **Non-Tech Dashboard:** Simple frontend / export interface allowing team members (Brother Jabir, Sales reps) to inspect and download verified leads and pipeline value reports.

---

## 7. Development Roadmap & Immediate Milestones

* [x] **Milestone 1:** Business model validation & Demand Paradox analysis (Completed).
* [x] **Milestone 2:** Master Intent-to-Service Mapping Guide & Beginner PDF generated (Completed).
* [x] **Milestone 3:** Master Requirements & Technical Specification Document created (Completed).
* [x] **Milestone 4:** Streamlined 2-Phase AI Processing & Multi-Party Stack Architecture aligned (Completed).
* [ ] **Milestone 5 (CURRENT FOCUS):** Extract Raw Los Angeles Time-Bounded Dataset (Intent 2: Notice of Violations / Code Citations) with exact deep-link verification URLs.
* [ ] **Milestone 6:** Execute Phase 1 AI Triage (Fire vs. Non-Fire & Commercial vs. Residential).
* [ ] **Milestone 7:** Execute Phase 2 Stakeholder Analysis (Commercial Landlord vs. Tenant + Estimated Repair Pipeline Value).
* [ ] **Milestone 8:** Implement Enrichment (BatchData + Floqer + Verisium) and deduplication.


