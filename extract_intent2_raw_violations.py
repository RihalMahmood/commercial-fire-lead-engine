"""
California Fire Safety Lead Generation Engine (Los Angeles 2.0)
Stage 1: Raw Municipal Data Ingestion for Intent 2 (Notices of Violation & Code Citations)

Target Datasets (City of Los Angeles / LADBS SODA APIs):
1. LADBS Code Enforcement Open Cases & Substandards (u82d-eh7z)
   - Captures official Orders to Comply, Substandard Notices, Citations (past 60 days).
2. LADBS Building & Safety Daily Inspections Feed (9w5z-rg2h)
   - Captures active inspection orders to comply, red-tags, corrections, and CofO holds.

Standards:
- Strict 60-day active compliance timeframe window.
- Unbounded pagination (loops until 100% records retrieved).
- Generates verified deep-link permalinks for every single record.
- Ingests / upserts into Supabase table: raw_municipal_violations.
"""

import os
import sys
import time
import json
import urllib.parse
from datetime import datetime, timedelta, timezone
import requests
from dotenv import load_dotenv

# Load credentials
load_dotenv()

raw_url = os.getenv("SUPABASE_URL", "").strip()
# Auto-clean URL to prevent PostgREST duplicate /rest/v1 pathing
SUPABASE_URL = raw_url.replace("/rest/v1", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("[!] Error: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing from .env")
    sys.exit(1)

from supabase import create_client, Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Date Boundary: Past 60 days
REF_DATE = datetime(2026, 10, 16, tzinfo=timezone.utc)
DAYS_WINDOW = 60
START_DATE = REF_DATE - timedelta(days=DAYS_WINDOW)
START_DATE_ISO = START_DATE.strftime("%Y-%m-%dT00:00:00.000")

print("=" * 65)
print(" STAGE 1: RAW MUNICIPAL DATA INGESTION — INTENT 2 (LOS ANGELES)")
print("=" * 65)
print(f"[*] Reference Date   : {REF_DATE.strftime('%Y-%m-%d')}")
print(f"[*] Lookback Window  : {DAYS_WINDOW} days (Since {START_DATE.strftime('%Y-%m-%d')})")
print(f"[*] Supabase Endpoint: {SUPABASE_URL}")
print("=" * 65 + "\n")


def fetch_soda_unbounded(endpoint_id: str, where_clause: str, order_clause: str, limit: int = 1000):
    """
    Fetches 100% of records from a SODA API endpoint using unbounded pagination.
    Loops with $offset until zero records are returned.
    """
    base_url = f"https://data.lacity.org/resource/{endpoint_id}.json"
    offset = 0
    all_records = []
    
    print(f"[*] Starting unbounded pagination on [{endpoint_id}]...")
    while True:
        params = {
            "$limit": limit,
            "$offset": offset,
            "$where": where_clause,
            "$order": order_clause
        }
        
        try:
            resp = requests.get(base_url, params=params, timeout=30)
            if resp.status_code != 200:
                print(f"  [!] HTTP Error {resp.status_code} on offset {offset}: {resp.text[:150]}")
                break
            
            batch = resp.json()
            if not batch or not isinstance(batch, list):
                break
            
            all_records.extend(batch)
            print(f"  [+] Pulled records {offset} to {offset + len(batch)} (Total so far: {len(all_records)})")
            
            if len(batch) < limit:
                # Reached end of available records
                break
            
            offset += limit
            time.sleep(0.15) # Gentle rate-limiting
            
        except Exception as e:
            print(f"  [!] Network exception during pagination at offset {offset}: {e}")
            break
            
    print(f"[OK] Ingestion complete for [{endpoint_id}]. Retrieved {len(all_records)} total raw records.\n")
    return all_records


def clean_address_parts(stno, predir, stname, suffix):
    parts = [str(stno or '').strip(), str(predir or '').strip(), str(stname or '').strip(), str(suffix or '').strip()]
    return ' '.join([p for p in parts if p]).upper()


def upsert_to_supabase(records, batch_size=200):
    """
    Upserts prepared rows into Supabase in chunks to prevent payload overflows.
    """
    if not records:
        print("  [*] No records to upload.")
        return 0
    
    total_upserted = 0
    print(f"[*] Committing {len(records)} records to Supabase 'raw_municipal_violations'...")
    
    for i in range(0, len(records), batch_size):
        chunk = records[i:i + batch_size]
        try:
            supabase.table("raw_municipal_violations").upsert(
                chunk, 
                on_conflict="source_city,source_endpoint_id,case_or_permit_number"
            ).execute()
            total_upserted += len(chunk)
            print(f"  [+] Committed {total_upserted} / {len(records)} rows...")
        except Exception as e:
            print(f"  [!] Batch upsert error at index {i}: {e}")
            # Fallback row-by-row on error
            for row in chunk:
                try:
                    supabase.table("raw_municipal_violations").upsert(
                        row, 
                        on_conflict="source_city,source_endpoint_id,case_or_permit_number"
                    ).execute()
                    total_upserted += 1
                except Exception as row_err:
                    print(f"    [-] Skipped row {row.get('case_or_permit_number')}: {row_err}")
                    
    print(f"[OK] Supabase sync completed: {total_upserted} records secured.\n")
    return total_upserted


def process_code_enforcement_cases():
    """
    Endpoint 1: LADBS Code Enforcement Open Cases & Substandards (u82d-eh7z)
    Captures Orders to Comply, Substandard Notices, Citations.
    """
    endpoint_id = "u82d-eh7z"
    where_clause = f"adddttm >= '{START_DATE_ISO}'"
    order_clause = "adddttm DESC"
    
    raw_rows = fetch_soda_unbounded(endpoint_id, where_clause, order_clause)
    prepared_records = []
    
    for r in raw_rows:
        case_no = str(r.get("apno") or "").strip()
        if not case_no:
            continue
        
        addr = clean_address_parts(r.get("stno"), r.get("predir"), r.get("stname"), r.get("suffix"))
        zip_code = str(r.get("zip") or "").replace("-", "").strip()
        apn = str(r.get("prclid") or "").strip()
        date_str = str(r.get("adddttm") or "")[:10]
        status_desc = "Open" if str(r.get("stat") or "").upper() == "O" else str(r.get("stat") or "")
        
        aptype = str(r.get("aptype") or "").strip()
        apname = str(r.get("apname") or "").strip()
        apc = str(r.get("apc") or "").strip()
        violation_text = f"Case Type: {aptype} | Sub-Case: {apname} | Planning Area: {apc}"
        
        # Exact Deep-Link Verification URL
        deep_link = f"https://data.lacity.org/resource/u82d-eh7z.json?apno={case_no}"
        
        prepared_records.append({
            "source_city": "los_angeles",
            "source_endpoint_id": endpoint_id,
            "source_dataset_name": "LADBS Code Enforcement Open Cases & Substandards",
            "case_or_permit_number": case_no,
            "property_address": addr,
            "zip_code": zip_code,
            "apn": apn,
            "violation_date": date_str if date_str else None,
            "status_desc": status_desc,
            "raw_violation_text": violation_text,
            "deep_link_verification_url": deep_link,
            "raw_payload": r,
            "triage_status": "PENDING"
        })
        
    return upsert_to_supabase(prepared_records)


def process_inspections_feed():
    """
    Endpoint 2: LADBS Building and Safety Inspections Feed (9w5z-rg2h)
    Captures Orders to Comply, Citations, Correction Notices, and CofO Holds.
    """
    endpoint_id = "9w5z-rg2h"
    where_clause = (
        f"inspection_date >= '{START_DATE_ISO}' and "
        "inspection_result in('Order to Comply Issued', 'OTC Issued', 'Corrections Issued', 'CofO on Hold', 'Not Ready for Inspection', 'No Access for Inspection', 'Fail', 'Failed', 'Violation')"
    )
    order_clause = "inspection_date DESC"
    
    raw_rows = fetch_soda_unbounded(endpoint_id, where_clause, order_clause)
    prepared_records = []
    
    for r in raw_rows:
        permit_raw = str(r.get("permit") or "").strip()
        if not permit_raw:
            continue
            
        addr = str(r.get("address") or "").strip().upper()
        date_str = str(r.get("inspection_date") or "")[:10]
        insp_type = str(r.get("inspection") or "").strip()
        insp_result = str(r.get("inspection_result") or "").strip()
        permit_status = str(r.get("permit_status") or "").strip()
        
        # Create deterministic unique case identifier per inspection event
        clean_permit = permit_raw.replace(" ", "-")
        clean_insp = "".join([c for c in insp_type if c.isalnum()])[:15]
        unique_case_id = f"{clean_permit}_{clean_insp}_{date_str}"
        
        violation_text = f"Inspection: {insp_type} | Result: {insp_result} | Permit Status: {permit_status}"
        
        # Deep-Link Verification URL querying the specific permit on SODA
        encoded_permit = urllib.parse.quote(permit_raw)
        deep_link = f"https://data.lacity.org/resource/9w5z-rg2h.json?permit={encoded_permit}"
        
        council_dist = str(r.get(":@computed_region_kqwf_mjcx") or "")
        
        prepared_records.append({
            "source_city": "los_angeles",
            "source_endpoint_id": endpoint_id,
            "source_dataset_name": "LADBS Building & Safety Daily Inspections Feed",
            "case_or_permit_number": unique_case_id,
            "property_address": addr,
            "council_district": council_dist if council_dist else None,
            "violation_date": date_str if date_str else None,
            "status_desc": insp_result,
            "raw_violation_text": violation_text,
            "deep_link_verification_url": deep_link,
            "raw_payload": r,
            "triage_status": "PENDING"
        })
        
    return upsert_to_supabase(prepared_records)


if __name__ == "__main__":
    t0 = time.time()
    
    # 1. Ingest Code Enforcement Cases (u82d-eh7z)
    total_cases = process_code_enforcement_cases()
    
    # 2. Ingest Inspections Feed (9w5z-rg2h)
    total_inspections = process_inspections_feed()
    
    elapsed = round(time.time() - t0, 1)
    print("=" * 65)
    print(" RAW MUNICIPAL INGESTION SUMMARY (INTENT 2)")
    print("=" * 65)
    print(f"  • Open Code Cases Processed       : {total_cases}")
    print(f"  • Inspection Feed Events Processed: {total_inspections}")
    print(f"  • Total Raw Records in Supabase   : {total_cases + total_inspections}")
    print(f"  • Execution Time                  : {elapsed} seconds")
    print("=" * 65)
    print(">>> STAGE 1 COMPLETE: Ready for Phase 1 AI Rapid Triage! <<<\n")
