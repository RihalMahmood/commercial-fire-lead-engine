"""
==============================================================================
CALIFORNIA FIRE SAFETY AUTONOMOUS ENGINE — 24-HOUR DAILY PIPELINE
Executes the unified 24h pipeline:
1. SODA Ingest (Past 24h or specified lookback) into daily_fire_violations_24h & raw_municipal_violations
2. Stage 2 Rapid AI Life-Safety Triage (Fire vs Non-Fire, Commercial vs Residential)
3. Stage 3 Stakeholder Mapping & Trade Contract Valuation (Landlord vs Tenant + $ Valuation)
4. Stage 5 Central Sent Suppression Deduplication (90-day cooldown check)
5. Exports fresh daily opportunities to LA_Daily_Fire_Violations_24h.csv
==============================================================================
"""

import os
import sys
import re
import json
import csv
import time
import argparse
import urllib.parse
from datetime import datetime, timedelta, timezone
import requests
from dotenv import load_dotenv
from supabase import create_client, Client
from stage4_serper_decision_makers import run_stage4_decision_maker_pipeline

# Ensure UTF-8 output encoding for Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").replace("/rest/v1", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("[ERROR] SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing from .env")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def fetch_soda_unbounded(endpoint_id: str, where_clause: str, order_clause: str, limit: int = 1000):
    base_url = f"https://data.lacity.org/resource/{endpoint_id}.json"
    offset = 0
    all_records = []
    
    print(f"[*] Querying SODA feed [{endpoint_id}]...")
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
                print(f"  [!] HTTP {resp.status_code} on offset {offset}: {resp.text[:120]}")
                break
            batch = resp.json()
            if not batch or not isinstance(batch, list):
                break
            all_records.extend(batch)
            print(f"  [+] Pulled {offset} to {offset + len(batch)} records (Total: {len(all_records)})")
            if len(batch) < limit:
                break
            offset += limit
            time.sleep(0.15)
        except Exception as e:
            print(f"  [!] Network error on offset {offset}: {e}")
            break
            
    return all_records


def clean_address_parts(stno, predir, stname, suffix):
    parts = [str(stno or '').strip(), str(predir or '').strip(), str(stname or '').strip(), str(suffix or '').strip()]
    return ' '.join([p for p in parts if p]).upper()


# ------------------------------------------------------------------------------
# STAGE 1: INGESTION INTO daily_fire_violations_24h & raw_municipal_violations
# ------------------------------------------------------------------------------
def ingest_daily_soda(start_date_iso: str, clear_daily_table: bool = True):
    print("======================================================================")
    print(" STEP 1: SODA MUNICIPAL INGESTION (24-HOUR / DELTA WINDOW)")
    print(f"[*] Querying records since: {start_date_iso}")
    print("======================================================================")

    if clear_daily_table:
        try:
            # Clear today's operational inbox table before inserting fresh batch
            supabase.table("daily_fire_violations_24h").delete().neq("source_city", "___").execute()
            print("[*] Cleared daily_fire_violations_24h inbox for fresh 24h batch.")
        except Exception as e:
            print(f"[*] Note on clearing daily table: {e}")

    # 1. Endpoint 1: LADBS Code Enforcement Open Cases (u82d-eh7z)
    ep1 = "u82d-eh7z"
    where1 = f"adddttm >= '{start_date_iso}'"
    rows1 = fetch_soda_unbounded(ep1, where1, "adddttm DESC")
    prepared_ep1 = []

    for r in rows1:
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
        violation_text = f"Case Type: {aptype} | Sub-Case: {apname}"
        deep_link = f"https://data.lacity.org/resource/u82d-eh7z.json?apno={case_no}"

        prepared_ep1.append({
            "source_city": "los_angeles",
            "source_endpoint_id": ep1,
            "case_or_permit_number": case_no,
            "property_address": addr,
            "zip_code": zip_code,
            "apn": apn,
            "violation_date": date_str if date_str else None,
            "status_desc": status_desc,
            "violation_summary": violation_text,
            "mapped_trade_service": "Pending Triage",
            "deep_link_verification_url": deep_link,
            "raw_payload": r,
            "pipeline_status": "EXTRACTED"
        })

    # 2. Endpoint 2: LADBS Building and Safety Inspections Feed (9w5z-rg2h)
    ep2 = "9w5z-rg2h"
    where2 = (
        f"inspection_date >= '{start_date_iso}' and "
        "inspection_result in('Order to Comply Issued', 'OTC Issued', 'Corrections Issued', 'CofO on Hold', 'Not Ready for Inspection', 'No Access for Inspection', 'Fail', 'Failed', 'Violation')"
    )
    rows2 = fetch_soda_unbounded(ep2, where2, "inspection_date DESC")
    prepared_ep2 = []

    for r in rows2:
        permit_raw = str(r.get("permit") or "").strip()
        if not permit_raw:
            continue
        addr = str(r.get("address") or "").strip().upper()
        date_str = str(r.get("inspection_date") or "")[:10]
        insp_type = str(r.get("inspection") or "").strip()
        insp_result = str(r.get("inspection_result") or "").strip()
        permit_status = str(r.get("permit_status") or "").strip()

        clean_permit = permit_raw.replace(" ", "-")
        clean_insp = "".join([c for c in insp_type if c.isalnum()])[:15]
        unique_case_id = f"{clean_permit}_{clean_insp}_{date_str}"
        violation_text = f"Inspection: {insp_type} | Result: {insp_result} | Permit Status: {permit_status}"
        encoded_permit = urllib.parse.quote(permit_raw)
        deep_link = f"https://data.lacity.org/resource/9w5z-rg2h.json?permit={encoded_permit}"

        prepared_ep2.append({
            "source_city": "los_angeles",
            "source_endpoint_id": ep2,
            "case_or_permit_number": unique_case_id,
            "property_address": addr,
            "zip_code": None,
            "apn": None,
            "violation_date": date_str if date_str else None,
            "status_desc": insp_result,
            "violation_summary": violation_text,
            "mapped_trade_service": "Pending Triage",
            "deep_link_verification_url": deep_link,
            "raw_payload": r,
            "pipeline_status": "EXTRACTED"
        })

    total_extracted = prepared_ep1 + prepared_ep2
    print(f"[*] Total raw records extracted in this cycle: {len(total_extracted)}")

    if total_extracted:
        # Commit to daily_fire_violations_24h in batches
        for i in range(0, len(total_extracted), 100):
            chunk = total_extracted[i:i + 100]
            try:
                supabase.table("daily_fire_violations_24h").upsert(
                    chunk, on_conflict="source_city,source_endpoint_id,case_or_permit_number,violation_date"
                ).execute()
            except Exception as e:
                print(f"  [!] Daily table upsert note: {e}")

        # Also preserve in permanent raw_municipal_violations archive
        raw_archive_rows = []
        for item in total_extracted:
            raw_archive_rows.append({
                "source_city": item["source_city"],
                "source_endpoint_id": item["source_endpoint_id"],
                "source_dataset_name": "LADBS 24h Daily Feed",
                "case_or_permit_number": item["case_or_permit_number"],
                "property_address": item["property_address"],
                "zip_code": item["zip_code"],
                "apn": item["apn"],
                "violation_date": item["violation_date"],
                "status_desc": item["status_desc"],
                "raw_violation_text": item["violation_summary"],
                "deep_link_verification_url": item["deep_link_verification_url"],
                "raw_payload": item["raw_payload"],
                "triage_status": "PENDING"
            })
        for i in range(0, len(raw_archive_rows), 100):
            chunk = raw_archive_rows[i:i + 100]
            try:
                supabase.table("raw_municipal_violations").upsert(
                    chunk, on_conflict="source_city,source_endpoint_id,case_or_permit_number"
                ).execute()
            except Exception as e:
                pass

    print(f"[OK] Ingestion complete: {len(total_extracted)} rows populated in daily_fire_violations_24h.")
    return len(total_extracted)


# ------------------------------------------------------------------------------
# STAGE 2 & 3: RAPID TRIAGE, STAKEHOLDER MAPPING & TRADE VALUATION
# ------------------------------------------------------------------------------
def triage_and_valuate_daily_batch():
    print("\n======================================================================")
    print(" STEP 2 & 3: RAPID AI TRIAGE, STAKEHOLDER MAPPING & VALUATION")
    print("======================================================================")

    res = supabase.table("daily_fire_violations_24h") \
        .select("*") \
        .eq("pipeline_status", "EXTRACTED") \
        .execute()

    records = res.data or []
    if not records:
        print("[*] No new EXTRACTED records in daily_fire_violations_24h to process.")
        return 0

    print(f"[*] Processing {len(records)} daily records through Triage & Valuation...")

    FIRE_KEYWORDS = [
        "FIRE", "SPRINKLER", "ALARM", "STANDPIPE", "HOOD", "SUPPRESSION",
        "HYDRO", "HYDROSTATIC", "RISER", "BACKFLOW", "PUMP", "SMOKE",
        "EGRESS", "EXIT", "TITLE 19", "REG 4", "REGULATION 4"
    ]

    qualified_leads = []
    
    for r in records:
        text = f"{r.get('violation_summary', '')} {json.dumps(r.get('raw_payload', {}))}".upper()
        is_fire = any(k in text for k in FIRE_KEYWORDS)

        if not is_fire:
            # Mark as non-fire and continue
            supabase.table("daily_fire_violations_24h") \
                .update({"pipeline_status": "TRIAGED_NON_FIRE"}) \
                .eq("id", r["id"]) \
                .execute()
            continue

        # Classify Stakeholder & Scope
        if any(k in text for k in ["HOOD", "COMMERCIAL KITCHEN", "DUCT", "ANSUL"]):
            stakeholder = "Commercial Tenant"
            scope = "NFPA 96 semi-annual commercial kitchen hood fire suppression overhaul, fusible links replacement, gas shutoff valve test, and tank recharge."
            val_min, val_max, val_est = 2000.0, 5500.0, 3200.0
        elif any(k in text for k in ["HYDRO", "HYDROSTATIC", "RISER", "UNDERGROUND", "STANDPIPE"]):
            stakeholder = "Commercial Landlord"
            scope = "NFPA 24/25 underground fire main and overhead riser hydrostatic pressure test (200 psi), leak isolation, and joint repair."
            val_min, val_max, val_est = 5000.0, 15000.0, 8500.0
        elif any(k in text for k in ["ALARM", "SMOKE DETECTOR", "PANEL", "STROBE"]):
            stakeholder = "Commercial Landlord"
            scope = "NFPA 72 commercial fire alarm panel ground fault diagnosis, initiating device remediation, and central station dispatch certification."
            val_min, val_max, val_est = 3500.0, 9500.0, 6200.0
        elif any(k in text for k in ["BACKFLOW", "DOUBLE CHECK", "RPZ"]):
            stakeholder = "Commercial Landlord"
            scope = "ASSE 1013 backflow preventer rebuild, relief valve kit installation, and cross-connection re-certification."
            val_min, val_max, val_est = 1800.0, 3500.0, 2600.0
        else:
            stakeholder = "Commercial Landlord"
            scope = "NFPA 25 comprehensive life-safety compliance repair, control valve replacement, and municipal certificate filing."
            val_min, val_max, val_est = 2500.0, 7000.0, 4500.0

        # Update daily_fire_violations_24h
        supabase.table("daily_fire_violations_24h") \
            .update({
                "mapped_trade_service": scope,
                "status_desc": f"{stakeholder} | Est: ${val_est:,.2f}",
                "pipeline_status": "VALUATED"
            }) \
            .eq("id", r["id"]) \
            .execute()

        # Insert or Upsert into permanent commercial_fire_leads CRM
        lead_payload = {
            "source_city": "los_angeles",
            "case_number": r["case_or_permit_number"],
            "property_address": r["property_address"],
            "zip_code": r.get("zip_code"),
            "apn": r.get("apn"),
            "deep_link_verification_url": r["deep_link_verification_url"],
            "intent_category": "Intent 2: Notice of Violation",
            "property_type": "Commercial",
            "is_fire_violation": True,
            "stakeholder_responsibility": stakeholder,
            "damage_diagnosis": r.get("violation_summary"),
            "required_nfpa_repair_scope": scope,
            "estimated_job_value_usd": val_est,
            "lead_status": "QUALIFIED"
        }

        try:
            supabase.table("commercial_fire_leads").upsert(
                lead_payload, on_conflict="source_city,case_number"
            ).execute()
        except Exception:
            supabase.table("commercial_fire_leads").insert(lead_payload).execute()

        qualified_leads.append(lead_payload)

    print(f"[OK] Triage & Valuation complete: {len(qualified_leads)} commercial fire opportunities qualified.")
    return len(qualified_leads)


# ------------------------------------------------------------------------------
# STAGE 5: CENTRAL SUPPRESSION DEDUPLICATION CHECK
# ------------------------------------------------------------------------------
def run_suppression_check():
    print("\n======================================================================")
    print(" STEP 4: CENTRAL SENT SUPPRESSION CHECK (90-DAY COOLDOWN)")
    print("======================================================================")

    res = supabase.table("commercial_fire_leads") \
        .select("lead_id, property_address, lead_status") \
        .eq("lead_status", "QUALIFIED") \
        .execute()

    leads = res.data or []
    if not leads:
        print("[*] No newly QUALIFIED leads to check for suppression.")
        return 0

    suppressed_count = 0
    ready_count = 0

    for l in leads:
        addr = l["property_address"]
        # Check if address was emailed in the last 90 days
        supp_check = supabase.table("central_sent_suppression_database") \
            .select("id") \
            .eq("property_address", addr) \
            .gte("sent_timestamp", (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()) \
            .execute()

        if supp_check.data and len(supp_check.data) > 0:
            suppressed_count += 1
            supabase.table("commercial_fire_leads") \
                .update({"lead_status": "SUPPRESSED"}) \
                .eq("lead_id", l["lead_id"]) \
                .execute()
        else:
            ready_count += 1
            supabase.table("commercial_fire_leads") \
                .update({"lead_status": "READY_FOR_DISPATCH"}) \
                .eq("lead_id", l["lead_id"]) \
                .execute()

    print(f"[OK] Suppression check finished: {ready_count} Approved for Dispatch | {suppressed_count} Suppressed.")
    return ready_count


# ------------------------------------------------------------------------------
# EXPORT DAILY AUDIT SPREADSHEET
# ------------------------------------------------------------------------------
def export_daily_csv():
    csv_file = "LA_Daily_Fire_Violations_24h.csv"
    res = supabase.table("daily_fire_violations_24h").select("*").execute()
    rows = res.data or []
    if not rows:
        print("[*] No rows to export for today's daily CSV.")
        return

    fieldnames = [
        "case_or_permit_number", "property_address", "violation_date",
        "status_desc", "mapped_trade_service", "pipeline_status",
        "deep_link_verification_url"
    ]

    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"[OK] Daily fresh opportunities exported to: {os.path.abspath(csv_file)}")


# ------------------------------------------------------------------------------
# MAIN PIPELINE ORCHESTRATOR
# ------------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Autonomous California Fire Safety 24h Engine")
    parser.add_argument("--start-date", type=str, default=None, help="Start date in ISO format YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=1, help="Lookback window in days (default: 1 for daily cron)")
    args = parser.parse_args()

    if args.start_date:
        start_date_iso = f"{args.start_date}T00:00:00.000"
    else:
        # Default 24-hour lookback
        start_dt = datetime.now(timezone.utc) - timedelta(days=args.days)
        start_date_iso = start_dt.strftime("%Y-%m-%dT00:00:00.000")

    print(f"\n======================================================================")
    print(f" AUTONOMOUS 24H FIRE PIPELINE RUNNER")
    print(f" Window: Since {start_date_iso} (Lookback: {args.days} days)")
    print(f" Connected DB: {SUPABASE_URL}")
    print(f"======================================================================\n")

    # Step 1: Ingest into daily_fire_violations_24h & raw_municipal_violations
    count = ingest_daily_soda(start_date_iso)

    # Step 2 & 3: Rapid Triage & Trade Valuation
    triage_and_valuate_daily_batch()

    # Step 4: 90-Day Suppression Deduplication
    run_suppression_check()

    # Step 5: Stage 4 Multi-Tier Serper Decision-Maker Discovery & Storage
    run_stage4_decision_maker_pipeline()

    # Step 6: Export daily opportunities CSV
    export_daily_csv()

    print("\n======================================================================")
    print(" >>> 24-HOUR DAILY PIPELINE RUN COMPLETE! <<<")
    print("======================================================================\n")


if __name__ == "__main__":
    main()
