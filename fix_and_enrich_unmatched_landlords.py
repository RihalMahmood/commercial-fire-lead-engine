"""
==============================================================================
FIX & ENRICH UNMATCHED LANDLORD LEADS ENGINE
Applies postal ZIP code resolution and advanced address normalization
to re-query BatchData Skip-Trace API for unmatched leads.
Updates Supabase and updates LA_BatchData_50_Pilot_Enriched.csv in-place.
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

# UTF-8 encoding for Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").replace("/rest/v1", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
BATCHDATA_API_KEY = os.getenv("BATCHDATA_API_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY or not BATCHDATA_API_KEY:
    print("[ERROR] Missing credentials in .env")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

BATCHDATA_ENDPOINT = "https://api.batchdata.com/api/v1/property/skip-trace"
HEADERS = {
    "Authorization": f"Bearer {BATCHDATA_API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

CSV_FILE = "LA_BatchData_50_Pilot_Enriched.csv"
GEO_CACHE = {}


def advanced_clean_street(raw_addr: str) -> str:
    """
    Normalizes municipal address anomalies:
    1. Hyphenated numbers: '1805-1805 1/2 N WESTRIDGE ROAD' -> '1805 N Westridge Rd'
    2. Range spans: '1500-1506 S ESPERANZA ST' -> '1500 S Esperanza St'
    3. Explicit unit tags: 'BLDG 2', 'STE 100', 'NO  9H/K', 'P1', 'RM 4'
    4. Standalone trailing unit numbers: '107', 'G3 & G4', '1-15'
    5. Erroneous municipal directional prefixes: 'N VIA DE LA PAZ' -> 'VIA DE LA PAZ'
    """
    if not raw_addr:
        return ""
    
    addr = raw_addr.strip()

    # 1. Hyphenated house number cleanup
    addr = re.sub(r'^(\d+)\s*-\s*\S+\s+', r'\1 ', addr)

    # 2. Erroneous Spanish street directionals
    addr = re.sub(r'\bN\s+(VIA\s+DE\s+LA\s+PAZ)\b', r'\1', addr, flags=re.IGNORECASE)

    # 3. Explicit unit tokens
    patterns = [
        r'\s+(?:NO|STE|SUITE|APT|UNIT|SPCE|BLDG|FL|RM|G\d|P\d|#)\s*.*$',
        r'\s+\d+\s*-\s*\d+.*$',
        r'\s+&\s+.*$',
    ]
    for p in patterns:
        addr = re.sub(p, '', addr, flags=re.IGNORECASE).strip()

    # 4. Trailing unit numbers (e.g., '6150 N Laurel Canyon Blvd 107' -> '6150 N Laurel Canyon Blvd')
    addr = re.sub(r'\s+\b\d{1,5}[A-Z]?\b$', '', addr).strip()

    # 5. Collapse spaces
    addr = re.sub(r'\s+', ' ', addr)
    return addr.title()


def get_zip_from_coords(lat, lon):
    if not lat or not lon:
        return ""
    key = f"{round(float(lat), 3)},{round(float(lon), 3)}"
    if key in GEO_CACHE:
        return GEO_CACHE[key]

    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
        r = requests.get(url, headers={"User-Agent": "FireSafetyEngine/2.0"}, timeout=3)
        if r.status_code == 200:
            pc = r.json().get("address", {}).get("postcode")
            if pc and len(pc) >= 5:
                clean_pc = pc[:5]
                GEO_CACHE[key] = clean_pc
                return clean_pc
    except Exception:
        pass
    return ""


def run_fix_and_enrich():
    print("======================================================================")
    print(" FIX & RE-ENRICH UNMATCHED COMMERCIAL LANDLORDS ENGINE")
    print("======================================================================")

    if not os.path.exists(CSV_FILE):
        print(f"[ERROR] {CSV_FILE} does not exist.")
        return

    with open(CSV_FILE, "r", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    unmatched_rows = [r for r in all_rows if r.get("batchdata_matched") == "NO"]
    print(f"[*] Found {len(unmatched_rows)} unmatched records out of {len(all_rows)} total in master CSV.")

    if not unmatched_rows:
        print("[*] All records already matched! Nothing to fix.")
        return

    # Fetch corresponding raw records to get coordinates
    # Fetch corresponding raw records in small chunks of 25 to prevent URL length limits
    unmatched_lead_ids = [r["lead_id"] for r in unmatched_rows]
    lead_lookup = {}
    for i in range(0, len(unmatched_lead_ids), 25):
        chunk_ids = unmatched_lead_ids[i:i + 25]
        res = supabase.table("commercial_fire_leads") \
            .select("lead_id, raw_violation_id, zip_code") \
            .in_("lead_id", chunk_ids) \
            .execute()
        for item in (res.data or []):
            lead_lookup[item["lead_id"]] = item

    raw_ids = [l["raw_violation_id"] for l in lead_lookup.values() if l.get("raw_violation_id")]
    raw_lookup = {}
    for i in range(0, len(raw_ids), 25):
        chunk_r_ids = raw_ids[i:i + 25]
        res = supabase.table("raw_municipal_violations") \
            .select("id, zip_code, raw_payload") \
            .in_("id", chunk_r_ids) \
            .execute()
        for item in (res.data or []):
            raw_lookup[item["id"]] = item

    print("[*] Resolving real postal ZIP codes and cleaning street addresses...")
    batch_payload = []
    re_query_list = []

    for r in unmatched_rows:
        lead_id = r["lead_id"]
        raw_lead = lead_lookup.get(lead_id, {})
        raw_rec = raw_lookup.get(raw_lead.get("raw_violation_id"), {})
        
        # Address cleaning
        clean_street = advanced_clean_street(r["property_address"])
        
        # ZIP resolution
        zip_code = raw_lead.get("zip_code") or raw_rec.get("zip_code")
        if not zip_code or len(zip_code) < 5:
            lat_lon = raw_rec.get("raw_payload", {}).get("lat_lon") or {}
            zip_code = get_zip_from_coords(lat_lon.get("latitude"), lat_lon.get("longitude"))

        # Build payload item: ONLY send zip if available (do NOT send hardcoded city)
        req_item = {
            "propertyAddress": {
                "street": clean_street,
                "state": "CA"
            }
        }
        if zip_code:
            req_item["propertyAddress"]["zip"] = zip_code
        else:
            req_item["propertyAddress"]["city"] = "Los Angeles"

        batch_payload.append(req_item)
        re_query_list.append((r, clean_street, zip_code))

    print(f"[*] Dispatching {len(batch_payload)} refined requests to BatchData Skip-Trace API...")
    
    # Send in chunks of 50 to respect BatchData limits
    CHUNK_SIZE = 50
    newly_matched_count = 0
    new_phones_count = 0

    for i in range(0, len(batch_payload), CHUNK_SIZE):
        chunk_requests = batch_payload[i:i + CHUNK_SIZE]
        chunk_meta = re_query_list[i:i + CHUNK_SIZE]
        
        print(f"[*] Sending batch chunk {i + 1} to {min(i + CHUNK_SIZE, len(batch_payload))}...")
        try:
            resp = requests.post(BATCHDATA_ENDPOINT, headers=HEADERS, json={"requests": chunk_requests}, timeout=60)
            if resp.status_code != 200:
                print(f"[!] BatchData returned HTTP {resp.status_code}: {resp.text[:150]}")
                continue
            
            chunk_data = resp.json()
            persons = chunk_data.get("results", {}).get("persons", [])

            for j, p in enumerate(persons):
                meta = p.get("meta", {})
                matched = meta.get("matched", False)
                csv_row, street_sent, zip_sent = chunk_meta[j]

                if matched:
                    newly_matched_count += 1
                    owner_name = p.get("name", {})
                    full_name = owner_name.get("full") or f"{owner_name.get('first', '')} {owner_name.get('last', '')}".strip()
                    phone_records = p.get("phoneNumbers", [])
                    email_records = p.get("emails", [])

                    clean_phones = []
                    contact_entries = []

                    for ph in phone_records:
                        num = ph.get("number") or ph.get("phone")
                        p_type = ph.get("type", "Unknown")
                        score = ph.get("score")
                        dnc = ph.get("dnc", False)
                        if num:
                            clean_phones.append(f"{num} ({p_type})")
                            contact_entries.append({
                                "name": full_name or "Property Owner",
                                "role": "Commercial Landlord",
                                "phone": num,
                                "phone_type": p_type,
                                "dnc": dnc,
                                "score": score,
                                "email": None,
                                "email_status": None,
                                "source": "BatchData_Refined"
                            })

                    for em in email_records:
                        email_addr = em.get("email") or em.get("address")
                        if email_addr:
                            contact_entries.append({
                                "name": full_name or "Property Owner",
                                "role": "Commercial Landlord",
                                "phone": None,
                                "email": email_addr,
                                "email_status": "PENDING_VERISIUM",
                                "source": "BatchData_Refined"
                            })

                    new_phones_count += len(clean_phones)

                    # Update Supabase
                    supabase.table("commercial_fire_leads") \
                        .update({
                            "enriched_contacts": contact_entries,
                            "landlord_managing_member": full_name if full_name else None,
                            "lead_status": "ENRICHED",
                            "updated_at": "now()"
                        }) \
                        .eq("lead_id", csv_row["lead_id"]) \
                        .execute()

                    # Update CSV row in-memory
                    csv_row["batchdata_matched"] = "YES"
                    csv_row["owner_full_name"] = full_name if full_name else "N/A"
                    csv_row["primary_phone"] = clean_phones[0] if len(clean_phones) > 0 else "N/A"
                    csv_row["secondary_phone"] = clean_phones[1] if len(clean_phones) > 1 else "N/A"
                    csv_row["total_phones_found"] = str(len(clean_phones))
                    csv_row["emails_found"] = "; ".join([e.get("email") or e.get("address", "") for e in email_records]) if email_records else "N/A"

        except Exception as e:
            print(f"[!] Error processing chunk: {e}")

    # Re-write the updated CSV
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "lead_id", "case_number", "property_address", "trade_scope",
            "contract_valuation_usd", "batchdata_matched", "owner_full_name",
            "primary_phone", "secondary_phone", "total_phones_found",
            "emails_found", "verification_url"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    # Final stats
    total_matched_now = sum(1 for r in all_rows if r.get("batchdata_matched") == "YES")
    total_phones_now = sum(int(r.get("total_phones_found", 0)) for r in all_rows)
    est_added_cost = newly_matched_count * 0.12

    print("\n======================================================================")
    print(" RE-ENRICHMENT RUN RESULTS")
    print("======================================================================")
    print(f"  * Previous Matched Leads        : 18 / 100 (18.0%)")
    print(f"  * Newly Rescued / Matched Leads : +{newly_matched_count}")
    print(f"  * NEW Overall Matched Leads     : {total_matched_now} / 100 ({(total_matched_now/len(all_rows))*100:.1f}%)")
    print(f"  * Additional Direct Phones Found: +{new_phones_count}")
    print(f"  * Total Direct Phones in CSV    : {total_phones_now}")
    print(f"  * Additional Match Cost         : ~${est_added_cost:.2f} (at ~$0.12/match)")
    print(f"  * Updated CSV File              : {os.path.abspath(CSV_FILE)}")
    print("======================================================================\n")


if __name__ == "__main__":
    run_fix_and_enrich()
