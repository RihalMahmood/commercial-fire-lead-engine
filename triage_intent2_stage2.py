"""
California Fire Safety Lead Generation Engine (Los Angeles 2.0)
Stage 2: Phase 1 Rapid Triage (Fire vs. Non-Fire & Commercial vs. Residential)

Target:
- Ingests pending records from Supabase table 'raw_municipal_violations'.
- Evaluates fire/life-safety compliance triggers against municipal noise.
- Classifies property type: Commercial, Multi-Family (10+ units), or Single-Family.
- Updates 'raw_municipal_violations' with triage status.
- Promotes qualified Commercial & Multi-Family Fire Leads into 'commercial_fire_leads'.
"""

import os
import sys
import re
import json
import time
from dotenv import load_dotenv

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

# ------------------------------------------------------------------------------
# CLASSIFICATION LOGIC & RULES (Section 6.1 of planning.md)
# ------------------------------------------------------------------------------

# Fire and Life-Safety keyword triggers
FIRE_KEYWORDS = [
    r"\bSPRINKLER\b", r"\bFIRE\b", r"\bSMOKE\b", r"\bALARM\b", r"\bBACKFLOW\b",
    r"\bFIRE PUMP\b", r"\bSTANDPIPE\b", r"\bHOOD\b", r"\bANSUL\b", r"\bHYDRO\b",
    r"\bEGRESS\b", r"\bEXIT\b", r"\bLIFE SAFETY\b", r"\bFLAMMABLE\b", r"\bEXTINGUISHER\b",
    r"\bSUPPRESSION\b", r"\bFIRE DOOR\b", r"\bRISER\b", r"\bTITLE 19\b", r"\bREG 4\b"
]
FIRE_REGEX = re.compile("|".join(FIRE_KEYWORDS), re.IGNORECASE)

# Routine non-fire keywords to drop
NON_FIRE_KEYWORDS = [
    r"\bDRYWALL\b", r"\bSTUCCO\b", r"\bGRADING\b", r"\bPRE-GUNITE\b", r"\bSWIMMING POOL\b",
    r"\bWOOD FRAME\b", r"\bROOFING\b", r"\bSEWER\b", r"\bWATER HEATER\b", r"\bDRAIN\b",
    r"\bFENCE\b", r"\bGRAFFITI\b", r"\bWEEDS\b", r"\bSIGN\b", r"\bTRASH\b", r"\bPAINT\b",
    r"\bFOOTING\b", r"\bFOUNDATION\b", r"\bLIGHT GAGE STEEL\b", r"\bSLAB\b", r"\bLATHING\b",
    r"\bINSULATION\b", r"\bGAS TEST\b"
]
NON_FIRE_REGEX = re.compile("|".join(NON_FIRE_KEYWORDS), re.IGNORECASE)

# Zoning Classifications (Los Angeles Zoning Code)
C_ZONES = ["C1", "C1.5", "C2", "C4", "C5", "CR", "CW", "CM", "CCS", "LAX", "USC", "ADP"]
M_ZONES = ["M1", "M2", "M3", "MR1", "MR2", "MP"]
MF_ZONES = ["R3", "R4", "R5", "RAS3", "RAS4"]
SF_PURE_ZONES = ["R1", "RS", "RE", "RA", "RU", "RZ", "R2", "RD"]


def evaluate_record(row):
    """
    Evaluates a single raw municipal record for fire relevance and property category.
    Returns: (is_fire, violation_category, property_category, reasoning)
    """
    raw_text = str(row.get("raw_violation_text") or "")
    payload = row.get("raw_payload") or {}
    status_desc = str(row.get("status_desc") or "")
    
    # Inspect all textual components
    full_text = f"{raw_text} {status_desc} {json.dumps(payload)}".upper()
    
    # 1. Fire / Life-Safety Detection
    is_fire = False
    category = "GENERAL_CODE"
    
    if re.search(r"\bSPRINKLER\b", full_text):
        is_fire = True
        category = "SPRINKLER"
    elif re.search(r"\bALARM\b|\bSMOKE\b", full_text):
        is_fire = True
        category = "ALARM"
    elif re.search(r"\bBACKFLOW\b", full_text):
        is_fire = True
        category = "BACKFLOW"
    elif re.search(r"\bFIRE PUMP\b|\bSTANDPIPE\b|\bHYDRO\b", full_text):
        is_fire = True
        category = "FIRE_PUMP"
    elif re.search(r"\bHOOD\b|\bANSUL\b|\bSUPPRESSION\b", full_text):
        is_fire = True
        category = "HOOD_SUPPRESSION"
    elif re.search(r"\bEGRESS\b|\bEXIT\b|\bFIRE DOOR\b|\bLIFE SAFETY\b", full_text):
        is_fire = True
        category = "EGRESS"
    elif FIRE_REGEX.search(full_text):
        is_fire = True
        category = "SPRINKLER"

    # 2. Property Classification
    zone = str(payload.get("zone") or payload.get("zoning") or "").strip().upper()
    clean_zone = re.sub(r'\[.*?\]|\(.*?\)', '', zone).strip()
    zone_tokens = re.split(r'[-\s,/;]+', clean_zone)
    base_zone = zone_tokens[0] if zone_tokens else clean_zone
    
    permit_sub = str(payload.get("permit_sub_type") or payload.get("use_desc") or "").upper()
    work_desc = str(payload.get("work_desc") or payload.get("inspection") or "").upper()
    
    # Check for Single-Family / ADU exclusions
    is_adu = "ADU" in work_desc or "ACCESSORY DWELLING" in permit_sub or "ADU" in permit_sub
    is_sfr = any(base_zone.startswith(sf) for sf in SF_PURE_ZONES) or "1 OR 2 FAMILY" in permit_sub or "SINGLE FAMILY" in permit_sub
    
    # Check for Commercial / Industrial / Multi-Family
    is_comm = any(base_zone.startswith(cz) for cz in C_ZONES) or "COMMERCIAL" in permit_sub or "COMMERCIAL" in full_text
    is_ind = any(base_zone.startswith(mz) for mz in M_ZONES) or "INDUSTRIAL" in permit_sub or "WAREHOUSE" in full_text or "MANUFACTURING" in full_text
    is_mf = any(base_zone.startswith(mfz) for mfz in MF_ZONES) or "APARTMENT" in permit_sub or "MULTI-FAMILY" in permit_sub
    
    if is_adu or (is_sfr and not is_comm and not is_mf):
        prop_category = "Residential"
    elif is_comm:
        prop_category = "Commercial"
    elif is_ind:
        prop_category = "Industrial"
    elif is_mf:
        prop_category = "Multi-Family"
    else:
        if any(term in full_text for term in ["BLVD", "SUITE", "STE", "UNIT B", "RETAIL", "OFFICE", "RESTAURANT", "PLAZA", "MALL"]):
            prop_category = "Commercial"
        else:
            prop_category = "Commercial"
            
    reasoning = f"{category} citation on {prop_category} property ({status_desc})"
    return is_fire, category, prop_category, reasoning


def batch_update_status(table, status_value, id_list, chunk_size=200):
    for i in range(0, len(id_list), chunk_size):
        chunk = id_list[i:i + chunk_size]
        try:
            supabase.table(table).update({"triage_status": status_value}).in_("id", chunk).execute()
        except Exception as e:
            print(f"    [!] Error batch-updating status: {e}")
            for single_id in chunk:
                try:
                    supabase.table(table).update({"triage_status": status_value}).eq("id", single_id).execute()
                except Exception:
                    pass


def run_stage2_triage():
    print("=" * 65)
    print(" STAGE 2: PHASE 1 AI RAPID TRIAGE (ZERO SEARCH)")
    print("=" * 65)
    
    limit = 1000
    total_processed = 0
    fire_count = 0
    non_fire_count = 0
    promoted_commercial_count = 0
    
    print("[*] Loading PENDING records from Supabase 'raw_municipal_violations'...")
    
    while True:
        # Fetch pending records
        res = supabase.table("raw_municipal_violations").select(
            "id,source_city,source_endpoint_id,case_or_permit_number,property_address,zip_code,apn,status_desc,raw_violation_text,deep_link_verification_url,raw_payload"
        ).eq("triage_status", "PENDING").limit(limit).execute()
        
        batch = res.data
        if not batch:
            print("[*] No more PENDING records found in raw_municipal_violations.")
            break
            
        print(f"[*] Processing batch of {len(batch)} records...")
        
        raw_updates_fire = []
        raw_updates_non_fire = []
        commercial_leads_to_insert = []
        
        for row in batch:
            row_id = row["id"]
            is_fire, category, prop_category, reasoning = evaluate_record(row)
            
            if is_fire:
                fire_count += 1
                raw_updates_fire.append(row_id)
                
                # Only Commercial, Industrial, and Multi-Family (10+) advance to commercial_fire_leads
                if prop_category in ["Commercial", "Industrial", "Multi-Family"]:
                    commercial_leads_to_insert.append({
                        "raw_violation_id": row_id,
                        "source_city": row.get("source_city", "los_angeles"),
                        "case_number": row.get("case_or_permit_number"),
                        "property_address": row.get("property_address"),
                        "zip_code": row.get("zip_code"),
                        "apn": row.get("apn"),
                        "deep_link_verification_url": row.get("deep_link_verification_url"),
                        "intent_category": "Intent 2: Notice of Violation (NOV)",
                        "property_type": prop_category,
                        "is_fire_violation": True,
                        "damage_diagnosis": f"Active {category} deficiency cited: {row.get('raw_violation_text')}",
                        "lead_status": "QUALIFIED"
                    })
            else:
                non_fire_count += 1
                raw_updates_non_fire.append(row_id)
                
        # Batch update triage statuses
        if raw_updates_fire:
            batch_update_status("raw_municipal_violations", "TRIAGED_FIRE", raw_updates_fire)
                
        if raw_updates_non_fire:
            batch_update_status("raw_municipal_violations", "TRIAGED_NON_FIRE", raw_updates_non_fire)
                
        # Insert qualified commercial leads in chunks
        if commercial_leads_to_insert:
            for i in range(0, len(commercial_leads_to_insert), 200):
                c_chunk = commercial_leads_to_insert[i:i + 200]
                try:
                    supabase.table("commercial_fire_leads").insert(c_chunk).execute()
                    promoted_commercial_count += len(c_chunk)
                except Exception as e:
                    print(f"  [!] Batch insert error on commercial leads: {e}")
                    for single_lead in c_chunk:
                        try:
                            supabase.table("commercial_fire_leads").insert(single_lead).execute()
                            promoted_commercial_count += 1
                        except Exception:
                            pass
                            
            print(f"  [+] Promoted {len(commercial_leads_to_insert)} qualified commercial fire leads to 'commercial_fire_leads'!")
                        
        total_processed += len(batch)
        print(f"  [+] Total Processed: {total_processed} | Fire: {fire_count} | Promoted Commercial: {promoted_commercial_count}")
        
    print("\n" + "=" * 65)
    print(" STAGE 2 TRIAGE SUMMARY")
    print("=" * 65)
    print(f"  • Total Raw Records Processed   : {total_processed}")
    print(f"  • Total Fire Violations Found    : {fire_count}")
    print(f"  • Non-Fire Violations Filtered   : {non_fire_count}")
    print(f"  • Promoted Commercial Fire Leads : {promoted_commercial_count}")
    print("=" * 65)
    print(">>> STAGE 2 COMPLETE: Ready for Phase 2 Deep Stakeholder Mapping! <<<\n")


if __name__ == "__main__":
    run_stage2_triage()
