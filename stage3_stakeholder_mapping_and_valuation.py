"""
California Fire Safety Lead Generation Engine (Los Angeles 2.0)
Stage 3: Phase 2 Deep Stakeholder Mapping & Trade Contract Dollar Valuation

Target:
- Ingests QUALIFIED commercial fire leads from Supabase table 'commercial_fire_leads'.
- Analyzes legal responsibility: Commercial Landlord vs. Commercial Tenant.
- Prescribes exact NFPA Repair Scope of Work (NFPA 13, 25, 72, 96, 101).
- Calculates realistic trade contract dollar values ($) based on California prevailing rates.
- Computes the Cumulative Pipeline Dollar Value across Los Angeles.
- Updates Supabase table and exports 'LA_Commercial_Fire_Leads_Valuation_Audit.csv'.
"""

import os
import sys
import re
import csv
import time
from dotenv import load_dotenv

# Ensure clean UTF-8 encoding on Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Load credentials
load_dotenv()

raw_url = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_URL = raw_url.replace("/rest/v1", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("[!] Error: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing from .env")
    sys.exit(1)

from supabase import create_client, Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

CSV_EXPORT_PATH = os.path.join(os.path.dirname(__file__), "LA_Commercial_Fire_Leads_Valuation_Audit.csv")


def map_stakeholder_and_valuation(lead):
    """
    Applies trade valuation and legal responsibility rules from Section 6.2 and Section 12 of planning.md.
    Returns: (stakeholder_resp, detailed_diagnosis, repair_scope, estimated_value_usd)
    """
    diag = str(lead.get("damage_diagnosis") or "").upper()
    prop_type = str(lead.get("property_type") or "Commercial")
    
    # 1. Fire Sprinkler Verification / CofO on Hold
    if "SPRINKLER" in diag:
        stakeholder = "Commercial Landlord"
        diagnosis = "Active Fire Sprinkler Deficiency / Verification Hold cited by LADBS"
        repair_scope = "NFPA 13/25 comprehensive sprinkler system verification, coverage compliance review, branch line flow check, and certified sign-off to lift CofO hold."
        est_value = 4800.00
        
    # 2. Fire Alarms & Smoke Detection Systems
    elif "ALARM" in diag or "SMOKE" in diag:
        stakeholder = "Commercial Landlord"
        diagnosis = "Active Fire Alarm & Smoke Detection System Failure / Corrections Notice issued"
        repair_scope = "NFPA 72 commercial smoke detector & signaling circuit diagnostic, device replacement, battery backup load test, and fire alarm re-certification."
        est_value = 5500.00
        
    # 3. Underground & Overhead Hydrostatic Pressure Holds
    elif "HYDRO" in diag or "PUMP" in diag:
        stakeholder = "Commercial Landlord"
        diagnosis = "Fire Main / Riser Hydrostatic Pressure Defect cited by LADBS inspector"
        repair_scope = "NFPA 24/25 underground fire main and overhead riser hydrostatic pressure test (200 psi), leak isolation, and joint repair."
        est_value = 8500.00
        
    # 4. Emergency Egress & Life Safety Holds
    elif "EGRESS" in diag or "LIFE SAFETY" in diag or "EXIT" in diag:
        stakeholder = "Commercial Landlord"
        diagnosis = "Life-Safety & Emergency Egress Non-Compliance Notice issued"
        repair_scope = "NFPA 101 Life Safety Code compliance remediation, emergency lighting & exit path battery load test, and fire door clearance abatement."
        est_value = 3800.00
        
    # 5. Commercial Kitchen Hood Fire Suppression
    elif "HOOD" in diag or "ANSUL" in diag:
        stakeholder = "Commercial Tenant"
        diagnosis = "Commercial Kitchen Hood Fire Suppression Defect / Uncertified System"
        repair_scope = "NFPA 96 semi-annual commercial kitchen hood fire suppression overhaul, fusible links replacement, gas shutoff valve test, and tank recharge."
        est_value = 3200.00
        
    # 6. Backflow Prevention Assemblies
    elif "BACKFLOW" in diag:
        stakeholder = "Commercial Landlord"
        diagnosis = "Uncertified / Failed Commercial Fire Line Backflow Prevention Assembly"
        repair_scope = "ASSE 5010 / NFPA 25 annual certified backflow test, internal relief valve rebuild, and municipal water district compliance filing."
        est_value = 2600.00
        
    # 7. General Life-Safety Order to Comply
    else:
        stakeholder = "Commercial Landlord"
        diagnosis = "Active Municipal Life-Safety Order to Comply / Statutory Citation"
        repair_scope = "Comprehensive NFPA life-safety code abatement, structural deficiency repair, and official LADBS inspector verification walkthrough."
        est_value = 4500.00

    return stakeholder, diagnosis, repair_scope, est_value


def run_stage3():
    print("=" * 70)
    print(" STAGE 3: PHASE 2 STAKEHOLDER MAPPING & TRADE VALUATION ENGINE")
    print("=" * 70)
    
    limit = 500
    
    # 1. Process remaining QUALIFIED leads
    while True:
        res = supabase.table("commercial_fire_leads").select(
            "lead_id,source_city,case_number,property_address,zip_code,apn,deep_link_verification_url,intent_category,property_type,damage_diagnosis"
        ).eq("lead_status", "QUALIFIED").limit(limit).execute()
        
        batch = res.data
        if not batch:
            print("[*] All leads successfully analyzed in Supabase.")
            break
            
        print(f"[*] Processing batch of {len(batch)} remaining leads...")
        
        for lead in batch:
            lead_id = lead["lead_id"]
            stakeholder, diag, scope, value = map_stakeholder_and_valuation(lead)
            
            try:
                supabase.table("commercial_fire_leads").update({
                    "stakeholder_responsibility": stakeholder,
                    "damage_diagnosis": diag,
                    "required_nfpa_repair_scope": scope,
                    "estimated_job_value_usd": value,
                    "lead_status": "ANALYZED"
                }).eq("lead_id", lead_id).execute()
            except Exception as e:
                print(f"  [!] Update error on {lead_id}: {e}")
                
    # 2. Export complete, clean audit spreadsheet of ALL 1,448 leads
    print("\n[*] Exporting complete audit spreadsheet from Supabase...")
    all_leads = []
    export_offset = 0
    export_limit = 1000
    total_pipeline_value = 0.0
    landlord_count = 0
    tenant_count = 0
    
    while True:
        exp_res = supabase.table("commercial_fire_leads").select(
            "lead_id,property_address,property_type,case_number,stakeholder_responsibility,damage_diagnosis,required_nfpa_repair_scope,estimated_job_value_usd,deep_link_verification_url"
        ).range(export_offset, export_offset + export_limit - 1).execute()
        
        exp_batch = exp_res.data
        if not exp_batch:
            break
            
        for row in exp_batch:
            val = float(row.get("estimated_job_value_usd") or 0.0)
            total_pipeline_value += val
            resp = str(row.get("stakeholder_responsibility") or "")
            if resp == "Commercial Landlord":
                landlord_count += 1
            else:
                tenant_count += 1
                
            all_leads.append({
                "Lead ID": row.get("lead_id"),
                "Property Address": row.get("property_address"),
                "Property Type": row.get("property_type"),
                "Case / Permit Number": row.get("case_number"),
                "Stakeholder Responsibility": resp,
                "Damage Diagnosis": row.get("damage_diagnosis"),
                "Required NFPA Scope": row.get("required_nfpa_repair_scope"),
                "Estimated Job Value ($)": f"${val:,.2f}",
                "Deep-Link Verification URL": row.get("deep_link_verification_url")
            })
            
        export_offset += len(exp_batch)
        if len(exp_batch) < export_limit:
            break
            
    # Write to CSV
    fieldnames = [
        "Lead ID", "Property Address", "Property Type", "Case / Permit Number",
        "Stakeholder Responsibility", "Damage Diagnosis", "Required NFPA Scope",
        "Estimated Job Value ($)", "Deep-Link Verification URL"
    ]
    with open(CSV_EXPORT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_leads)
        
    print(f"[OK] Master audit spreadsheet successfully exported to:\n  File: {CSV_EXPORT_PATH}")
    
    print("\n" + "=" * 70)
    print(" STAGE 3 FINAL VALUATION & PIPELINE AUDIT SUMMARY")
    print("=" * 70)
    print(f"  * Total Commercial Leads Analyzed  : {len(all_leads)}")
    print(f"  * Commercial Landlord Citations    : {landlord_count}")
    print(f"  * Commercial Tenant Citations      : {tenant_count}")
    print(f"  * Cumulative Pipeline Dollar Value : ${total_pipeline_value:,.2f}")
    print(f"  * Average Contract Value per Job   : ${total_pipeline_value / max(1, len(all_leads)):,.2f}")
    print("=" * 70)
    print(">>> STAGE 3 COMPLETE: Ready for Stage 4 Contact Enrichment! <<<\n")


if __name__ == "__main__":
    run_stage3()
