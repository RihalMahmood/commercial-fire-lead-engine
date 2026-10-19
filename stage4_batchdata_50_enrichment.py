"""
==============================================================================
STAGE 4: BATCHDATA 50-RECORD PILOT ENRICHMENT SCRIPT
Extracts verified commercial deed owner names & direct phone numbers
using BatchData Skip-Trace API ($0.09 - $0.12 per matched search).
==============================================================================
"""

import os
import sys
import re
import json
import csv
import time
import requests
from dotenv import load_dotenv
from supabase import create_client

# Ensure UTF-8 output encoding for Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load environment credentials
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").replace("/rest/v1", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
BATCHDATA_API_KEY = os.getenv("BATCHDATA_API_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    print("[ERROR] Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env")
    sys.exit(1)

if not BATCHDATA_API_KEY:
    print("[ERROR] Missing BATCHDATA_API_KEY in .env")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

BATCHDATA_ENDPOINT = "https://api.batchdata.com/api/v1/property/skip-trace"
HEADERS = {
    "Authorization": f"Bearer {BATCHDATA_API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}


def clean_street_address(raw_addr: str) -> str:
    """
    Cleans raw municipal addresses for optimal matching in BatchData.
    Removes internal municipal unit noise like 'NO  9H/K', 'G3 & G4', '1-15', 'UNIT 101'.
    """
    if not raw_addr:
        return ""
    
    addr = raw_addr.strip()
    
    # Remove unit/suite/space noise at the end
    patterns = [
        r'\s+(?:NO|STE|SUITE|APT|UNIT|SPCE|BLDG|FL|RM|G\d|#)\s*.*$',
        r'\s+\d+\s*-\s*\d+.*$',                     # e.g., '1-15'
        r'\s+&\s+.*$',                               # e.g., '& G4'
        r'\s+\b\d{1,4}[A-Z]\b.*$',                   # e.g., '9H'
    ]
    for p in patterns:
        addr = re.sub(p, '', addr, flags=re.IGNORECASE).strip()
        
    # Clean multiple spaces
    addr = re.sub(r'\s+', ' ', addr)
    return addr.title()


def run_batchdata_50_pilot():
    print("======================================================================")
    print(" STAGE 4: BATCHDATA 50-RECORD PILOT ENRICHMENT")
    print(" Target: 50 High-Value Commercial Landlord Citations")
    print("======================================================================")

    # 1. Fetch top 50 commercial landlord leads ordered by contract value
    res = supabase.table("commercial_fire_leads") \
        .select("lead_id, case_number, property_address, zip_code, apn, deep_link_verification_url, required_nfpa_repair_scope, estimated_job_value_usd, raw_violation_id") \
        .eq("stakeholder_responsibility", "Commercial Landlord") \
        .order("estimated_job_value_usd", desc=True) \
        .limit(50) \
        .execute()

    leads = res.data or []
    if not leads:
        print("[!] No leads found matching 'Commercial Landlord'.")
        return

    print(f"[*] Pulled {len(leads)} leads from Supabase for enrichment.")

    # 2. Build requests for BatchData API
    requests_payload = []
    lead_mapping = {}

    for lead in leads:
        clean_street = clean_street_address(lead["property_address"])
        lead_mapping[clean_street.lower()] = lead
        
        req_item = {
            "propertyAddress": {
                "street": clean_street,
                "city": "Los Angeles",
                "state": "CA"
            }
        }
        if lead.get("zip_code"):
            req_item["propertyAddress"]["zip"] = lead["zip_code"]

        requests_payload.append(req_item)

    print(f"[*] Dispatching {len(requests_payload)} properties to BatchData Skip-Trace API...")
    
    # BatchData accepts up to 100 per request, so 50 is sent in a single clean batch
    payload = {"requests": requests_payload}
    
    start_time = time.time()
    try:
        response = requests.post(BATCHDATA_ENDPOINT, headers=HEADERS, json=payload, timeout=60)
    except Exception as e:
        print(f"[ERROR] BatchData request failed: {e}")
        return

    latency = round(time.time() - start_time, 2)
    print(f"[*] BatchData API responded in {latency}s with HTTP {response.status_code}")

    if response.status_code != 200:
        print(f"[ERROR] BatchData returned error {response.status_code}: {response.text}")
        return

    data = response.json()
    persons_results = data.get("results", {}).get("persons", [])
    print(f"[*] Received {len(persons_results)} results from BatchData.")

    # 3. Process each returned person result and update Supabase
    matched_count = 0
    total_phones_extracted = 0
    audit_rows = []

    for idx, p in enumerate(persons_results):
        meta = p.get("meta", {})
        matched = meta.get("matched", False)
        
        # Get original lead
        lead = leads[idx] if idx < len(leads) else None
        if not lead:
            continue

        owner_name = p.get("name", {})
        full_name = owner_name.get("full") or f"{owner_name.get('first', '')} {owner_name.get('last', '')}".strip()
        phone_records = p.get("phoneNumbers", [])
        email_records = p.get("emails", [])

        contact_entry = []
        clean_phones_list = []

        if matched:
            matched_count += 1
            # Parse phones
            for ph in phone_records:
                num = ph.get("number") or ph.get("phone")
                p_type = ph.get("type", "Unknown")
                score = ph.get("score")
                dnc = ph.get("dnc", False)
                if num:
                    clean_phones_list.append(f"{num} ({p_type})")
                    contact_entry.append({
                        "name": full_name or "Property Owner",
                        "role": "Commercial Landlord",
                        "phone": num,
                        "phone_type": p_type,
                        "dnc": dnc,
                        "score": score,
                        "email": None,
                        "email_status": None,
                        "source": "BatchData"
                    })
            
            # Parse emails (flagged PENDING_VERISIUM)
            for em in email_records:
                email_addr = em.get("email") or em.get("address")
                if email_addr:
                    contact_entry.append({
                        "name": full_name or "Property Owner",
                        "role": "Commercial Landlord",
                        "phone": None,
                        "email": email_addr,
                        "email_status": "PENDING_VERISIUM",
                        "source": "BatchData"
                    })

            total_phones_extracted += len(clean_phones_list)

            # Update Supabase record
            update_payload = {
                "enriched_contacts": contact_entry,
                "landlord_managing_member": full_name if full_name else None,
                "lead_status": "ENRICHED",
                "updated_at": "now()"
            }
            supabase.table("commercial_fire_leads") \
                .update(update_payload) \
                .eq("lead_id", lead["lead_id"]) \
                .execute()

        # Audit row for CSV export
        primary_phone = clean_phones_list[0] if len(clean_phones_list) > 0 else "N/A"
        secondary_phone = clean_phones_list[1] if len(clean_phones_list) > 1 else "N/A"
        email_str = "; ".join([e.get("email") or e.get("address", "") for e in email_records]) if email_records else "N/A"

        audit_rows.append({
            "lead_id": lead["lead_id"],
            "case_number": lead["case_number"],
            "property_address": lead["property_address"],
            "trade_scope": lead.get("required_nfpa_repair_scope", "Fire Protection"),
            "contract_valuation_usd": f"${float(lead.get('estimated_job_value_usd') or 0):,.2f}",
            "batchdata_matched": "YES" if matched else "NO",
            "owner_full_name": full_name if full_name else "N/A",
            "primary_phone": primary_phone,
            "secondary_phone": secondary_phone,
            "total_phones_found": len(clean_phones_list),
            "emails_found": email_str,
            "verification_url": lead["deep_link_verification_url"]
        })

    # 4. Export CSV Report
    csv_filename = "LA_BatchData_50_Pilot_Enriched.csv"
    with open(csv_filename, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "lead_id", "case_number", "property_address", "trade_scope",
            "contract_valuation_usd", "batchdata_matched", "owner_full_name",
            "primary_phone", "secondary_phone", "total_phones_found",
            "emails_found", "verification_url"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(audit_rows)

    # 5. Output Summary
    est_cost = matched_count * 0.12
    print("\n======================================================================")
    print(" STAGE 4 BATCHDATA PILOT SUMMARY")
    print("======================================================================")
    print(f"  * Total Leads Processed         : {len(leads)}")
    print(f"  * Deed Owners Successfully Found: {matched_count}")
    print(f"  * Overall Match Rate            : {(matched_count / len(leads)) * 100:.1f}%")
    print(f"  * Total Direct Phones Extracted : {total_phones_extracted}")
    print(f"  * Estimated BatchData Search Cost: ~${est_cost:.2f} (at ~$0.12/match)")
    print(f"  * Master Enriched Pilot CSV     : {os.path.abspath(csv_filename)}")
    print("======================================================================\n")


if __name__ == "__main__":
    run_batchdata_50_pilot()
