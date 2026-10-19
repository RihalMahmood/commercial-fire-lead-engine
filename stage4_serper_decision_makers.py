"""
==============================================================================
STAGE 4: SERPER API MULTI-TIER DECISION-MAKER DISCOVERY ENGINE
Implements Stage 4 of California Fire Safety Specification:
- Discovers commercial entities / operating businesses at cited addresses
- Discovers 4 to 5 key decision-makers (Asset Managers, Operations Directors,
  Property Managers, General Managers, Facilities Directors) per property
- Extracts LinkedIn profile URLs, exact titles, and verified entity context
- Updates Supabase: commercial_fire_leads, daily_commercial_leads_24h, master_enriched_leads
- Generates Stage 6 exports:
    /exports/LA_Enriched_Fire_Leads_YYYY_MM_DD.csv
    /exports/LA_Daily_VA_Review_Sheet.csv (with 24h SLA SOP)
==============================================================================
"""

import os
import re
import sys
import json
import csv
import time
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv
from supabase import create_client, Client

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
SERPER_API_KEY = os.getenv("SERPER_API_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("[ERROR] SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing from .env")
    sys.exit(1)

if not SERPER_API_KEY:
    print("[ERROR] SERPER_API_KEY missing from .env")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
SERPER_HEADERS = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
SERPER_SEARCH_URL = "https://google.serper.dev/search"


def clean_address_for_search(addr: str) -> str:
    """Cleans municipal address noise for optimal Google/Serper search."""
    if not addr:
        return ""
    cleaned = addr.strip()
    # Strip unit/ste/apt/no/spce tags
    cleaned = re.sub(r'\s+(?:NO|STE|SUITE|APT|UNIT|SPCE|BLDG|FL|RM|G\d|#)\s*.*$', '', cleaned, flags=re.IGNORECASE)
    # Strip fractional addresses like 247-247 1/2 -> 247
    cleaned = re.sub(r'-\d+\s*1/2', '', cleaned)
    cleaned = re.sub(r'\s+1/2', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned.title()


def call_serper(query: str, num: int = 5) -> dict:
    """Executes a single search query on Serper API."""
    try:
        resp = requests.post(SERPER_SEARCH_URL, headers=SERPER_HEADERS, json={"q": query, "num": num}, timeout=20)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"  [!] Serper HTTP {resp.status_code}: {resp.text[:80]}")
            return {}
    except Exception as e:
        print(f"  [!] Serper network error: {e}")
        return {}


def discover_entity_name(clean_addr: str) -> str:
    """Discovers the operating business, building name, or facility at this address."""
    q = f'"{clean_addr}" Los Angeles commercial OR property OR business OR building'
    data = call_serper(q, num=4)
    
    # 1. Check knowledgeGraph
    kg = data.get("knowledgeGraph", {})
    if kg and kg.get("title"):
        return kg["title"].strip()
        
    # 2. Check places
    places = data.get("places", [])
    if places and places[0].get("title"):
        return places[0]["title"].strip()
        
    # 3. Check organic titles
    for o in data.get("organic", []):
        title = o.get("title", "")
        # Look for patterns like "Name - City", "Name | Category"
        parts = re.split(r'\s+[-|]\s+', title)
        candidate = parts[0].strip()
        if candidate and not any(skip in candidate.lower() for skip in ["building permits", "property records", "zillow", "redfin", "realtor", "permit", "compass"]):
            if len(candidate) > 3 and len(candidate) < 60:
                return candidate
                
    return ""


def parse_linkedin_person(item: dict, fallback_company: str = "") -> dict:
    """Extracts clean Name, Job Title, Company, and LinkedIn URL from a Serper search result."""
    title = item.get("title", "")
    snippet = item.get("snippet", "")
    link = item.get("link", "")
    
    # Split title: "Hamlet Vazquez, PCAM, MCAM-HR, MBA" or "Ann Burroughs - President & CEO, Japanese American ..."
    parts = re.split(r'\s+[-–|:]\s+', title)
    name_candidate = parts[0].strip()
    
    # Clean professional degrees / honorifics
    name_candidate = re.sub(r',\s*(?:PCAM|MCAM-HR|MBA|CPM|CCIM|PE|RPA|CPA|JD|Esq|Ph\.?D).*$', '', name_candidate, flags=re.IGNORECASE).strip()
    # Strip any trailing "on LinkedIn" or "..."
    name_candidate = re.sub(r'\s+on\s+LinkedIn.*$', '', name_candidate, flags=re.IGNORECASE).strip()
    
    # Discard non-person names
    if any(skip in name_candidate.lower() for skip in ["linkedin", "top", "best", "the", "find", "search", "people", "permits"]):
        return None
    if len(name_candidate.split()) < 2:
        return None
        
    job_title = ""
    company = fallback_company
    
    if len(parts) > 1:
        job_title = parts[1].strip()
        if len(parts) > 2 and not company:
            company = parts[2].strip()
            
    # Extract role from snippet if title is just company or empty
    role_matches = re.findall(
        r'((?:General Manager|Property Manager|Facility Director|Director of Operations|Building Manager|Operations Manager|Asset Manager|Chief Engineer|President & CEO|CEO|Executive Director|Director of [A-Za-z\s]+)[^.,;]*)',
        snippet, re.IGNORECASE
    )
    if role_matches:
        job_title = role_matches[0].strip()
    elif not job_title or job_title.lower() == "linkedin":
        job_title = "Commercial Property Decision Maker"

    return {
        "name": name_candidate,
        "title": job_title[:75],
        "company": company or fallback_company,
        "linkedin_url": link,
        "source": "Serper"
    }


def discover_decision_makers(clean_addr: str, entity_name: str, responsibility: str) -> list:
    """Discovers 4 to 5 key decision-makers for a commercial property using Serper."""
    contacts = []
    seen_links = set()
    seen_names = set()

    queries = []
    # 1. Entity-specific LinkedIn search
    if entity_name:
        queries.append(f'site:linkedin.com/in ("{entity_name}") ("Property Manager" OR "General Manager" OR "Operations" OR "Facilities" OR "Asset Manager" OR "Director" OR "President")')
    
    # 2. Address-based LinkedIn search
    queries.append(f'site:linkedin.com/in "{clean_addr}" ("Property Manager" OR "Building Manager" OR "Operations" OR "Facilities" OR "Manager" OR "Director")')
    
    # 3. Supplemental web search for management personnel
    queries.append(f'"{clean_addr}" Los Angeles ("Property Manager" OR "Building Manager" OR "Asset Manager" OR "Operations")')

    role_label = responsibility or "Commercial Landlord"

    for q in queries:
        if len(contacts) >= 5:
            break
        data = call_serper(q, num=6)
        time.sleep(0.15)
        
        for item in data.get("organic", []):
            link = item.get("link", "")
            if "linkedin.com/in/" in link:
                person = parse_linkedin_person(item, fallback_company=entity_name)
                if person:
                    name_key = person["name"].lower()
                    if name_key not in seen_names and link not in seen_links:
                        seen_names.add(name_key)
                        seen_links.add(link)
                        person["role"] = role_label
                        person["phone"] = None
                        person["email"] = None
                        person["email_status"] = "Unverified"
                        contacts.append(person)
                        if len(contacts) >= 5:
                            break
            else:
                # Web snippet parsing for building managers
                snippet = item.get("snippet", "")
                title = item.get("title", "")
                # Find names associated with manager roles in snippets
                mgr_match = re.search(r'([A-Z][a-z]+ [A-Z][a-z]+)[,\s\-–]+(?:Property Manager|Building Manager|General Manager|Asset Manager|Manager)', snippet)
                if mgr_match:
                    found_name = mgr_match.group(1).strip()
                    if found_name.lower() not in seen_names and not any(skip in found_name.lower() for skip in ["los angeles", "san fernando", "building permits"]):
                        seen_names.add(found_name.lower())
                        contacts.append({
                            "name": found_name,
                            "title": "Property / Building Manager",
                            "company": entity_name or clean_addr,
                            "linkedin_url": link,
                            "role": role_label,
                            "phone": None,
                            "email": None,
                            "email_status": "Unverified",
                            "source": "Serper"
                        })
                        if len(contacts) >= 5:
                            break

    return contacts[:5]


def run_stage4_decision_maker_pipeline():
    print("======================================================================")
    print(" STAGE 4: SERPER MULTI-TIER DECISION-MAKER ENRICHMENT PIPELINE")
    print(f" Target Database: {SUPABASE_URL}")
    print("======================================================================\n")

    # 1. Fetch qualified commercial leads from commercial_fire_leads
    res = supabase.table("commercial_fire_leads").select("*").execute()
    leads = res.data or []
    if not leads:
        print("[!] No leads found in commercial_fire_leads to enrich.")
        return

    print(f"[*] Found {len(leads)} qualified commercial fire leads for Stage 4 enrichment.\n")

    enriched_records = []
    unmatched_records = []
    today_str = datetime.now(timezone.utc).strftime("%Y_%m_%d")

    for idx, lead in enumerate(leads, 1):
        lead_id = lead["lead_id"]
        raw_addr = lead["property_address"]
        case_no = lead.get("case_number", "")
        clean_addr = clean_address_for_search(raw_addr)
        resp_type = lead.get("stakeholder_responsibility", "Commercial Landlord")
        violation_sum = lead.get("damage_diagnosis") or lead.get("violation_summary") or "Municipal life-safety deficiency citation"
        mapped_service = lead.get("required_nfpa_repair_scope") or "NFPA life-safety compliance repair"
        est_val = float(lead.get("estimated_job_value_usd") or 0.0)
        deep_link = lead.get("deep_link_verification_url") or f"https://data.lacity.org/resource/9w5z-rg2h.json?case={case_no}"

        print(f"[{idx}/{len(leads)}] Processing: {clean_addr}")
        print(f"    Case: {case_no} | Est. Value: ${est_val:,.2f}")

        # Step A: Discover Entity Name
        entity_name = lead.get("landlord_company_name") or lead.get("tenant_business_name")
        if not entity_name:
            entity_name = discover_entity_name(clean_addr)
            if entity_name:
                print(f"    [+] Discovered Entity: {entity_name}")
            else:
                entity_name = clean_addr

        # Step B: Discover 4-5 Decision Makers via Serper
        contacts = discover_decision_makers(clean_addr, entity_name, resp_type)
        print(f"    [+] Discovered {len(contacts)} Decision-Makers:")
        for c in contacts:
            print(f"        * {c['name']} - {c['title']} ({c.get('company', '')})")

        # Step C: Prepare Enriched Lead Payload
        enriched_item = {
            "lead_id": lead_id,
            "case_number": case_no,
            "property_address": raw_addr,
            "clean_address": clean_addr,
            "zip_code": lead.get("zip_code"),
            "apn": lead.get("apn"),
            "violation_summary": violation_sum,
            "mapped_trade_service": mapped_service,
            "estimated_job_value_usd": est_val,
            "stakeholder_responsibility": resp_type,
            "entity_name": entity_name,
            "enriched_contacts": contacts,
            "deep_link_verification_url": deep_link,
            "lead_status": "ENRICHED" if len(contacts) >= 2 else "PARTIAL",
            "contacts_count": len(contacts)
        }

        # Step D: Update commercial_fire_leads in Supabase
        update_data = {
            "landlord_company_name": entity_name if "Landlord" in resp_type else lead.get("landlord_company_name"),
            "tenant_business_name": entity_name if "Tenant" in resp_type else lead.get("tenant_business_name"),
            "enriched_contacts": contacts,
            "lead_status": "ENRICHED" if len(contacts) >= 2 else "PARTIAL",
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        supabase.table("commercial_fire_leads").update(update_data).eq("lead_id", lead_id).execute()

        # Step E: Upsert into daily_commercial_leads_24h
        daily_payload = {
            "case_number": case_no,
            "property_address": raw_addr,
            "zip_code": lead.get("zip_code"),
            "apn": lead.get("apn"),
            "violation_summary": violation_sum,
            "mapped_trade_service": mapped_service,
            "estimated_job_value_usd": est_val,
            "stakeholder_responsibility": resp_type,
            "entity_name": entity_name,
            "enriched_contacts": contacts,
            "deep_link_verification_url": deep_link,
            "lead_status": "ENRICHED" if len(contacts) >= 2 else "PARTIAL"
        }
        try:
            supabase.table("daily_commercial_leads_24h").upsert(
                daily_payload, on_conflict="case_number"
            ).execute()
        except Exception:
            supabase.table("daily_commercial_leads_24h").insert(daily_payload).execute()

        # Step F: Upsert into master_enriched_leads (Permanent cumulative master)
        master_payload = {
            "source_city": "los_angeles",
            "case_number": case_no,
            "property_address": raw_addr,
            "zip_code": lead.get("zip_code"),
            "apn": lead.get("apn"),
            "violation_summary": violation_sum,
            "mapped_trade_service": mapped_service,
            "estimated_job_value_usd": est_val,
            "stakeholder_responsibility": resp_type,
            "landlord_company_name": entity_name if "Landlord" in resp_type else None,
            "tenant_business_name": entity_name if "Tenant" in resp_type else None,
            "enriched_contacts": contacts,
            "deep_link_verification_url": deep_link,
            "lead_status": "ENRICHED" if len(contacts) >= 2 else "PARTIAL"
        }
        try:
            supabase.table("master_enriched_leads").upsert(
                master_payload, on_conflict="source_city,case_number"
            ).execute()
        except Exception:
            supabase.table("master_enriched_leads").insert(master_payload).execute()

        enriched_records.append(enriched_item)
        if len(contacts) < 3:
            unmatched_records.append(enriched_item)

        time.sleep(0.2)

    # --------------------------------------------------------------------------
    # STAGE 6: EXPORT TO /exports/ AND DAILY VA REVIEW SHEET
    # --------------------------------------------------------------------------
    os.makedirs("exports", exist_ok=True)
    master_csv_path = os.path.join("exports", f"LA_Enriched_Fire_Leads_{today_str}.csv")
    va_sheet_path = os.path.join("exports", "LA_Daily_VA_Review_Sheet.csv")

    # 1. Master Enriched Leads CSV
    with open(master_csv_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "lead_id", "case_number", "property_address", "entity_name",
            "violation_summary", "mapped_trade_service", "estimated_job_value_usd",
            "stakeholder_responsibility", "contacts_count",
            "contact_1_name", "contact_1_title", "contact_1_linkedin",
            "contact_2_name", "contact_2_title", "contact_2_linkedin",
            "contact_3_name", "contact_3_title", "contact_3_linkedin",
            "contact_4_name", "contact_4_title", "contact_4_linkedin",
            "contact_5_name", "contact_5_title", "contact_5_linkedin",
            "deep_link_verification_url"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for item in enriched_records:
            contacts = item["enriched_contacts"]
            row = {
                "lead_id": item["lead_id"],
                "case_number": item["case_number"],
                "property_address": item["property_address"],
                "entity_name": item["entity_name"],
                "violation_summary": item["violation_summary"],
                "mapped_trade_service": item["mapped_trade_service"],
                "estimated_job_value_usd": f"${item['estimated_job_value_usd']:,.2f}",
                "stakeholder_responsibility": item["stakeholder_responsibility"],
                "contacts_count": item["contacts_count"],
                "deep_link_verification_url": item["deep_link_verification_url"]
            }
            for i in range(1, 6):
                if i <= len(contacts):
                    c = contacts[i - 1]
                    row[f"contact_{i}_name"] = c.get("name", "")
                    row[f"contact_{i}_title"] = c.get("title", "")
                    row[f"contact_{i}_linkedin"] = c.get("linkedin_url", "")
                else:
                    row[f"contact_{i}_name"] = ""
                    row[f"contact_{i}_title"] = ""
                    row[f"contact_{i}_linkedin"] = ""
            writer.writerow(row)

    # 2. Daily VA Review Sheet (SOP 24h SLA)
    with open(va_sheet_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "lead_id", "case_number", "property_address", "entity_name",
            "violation_summary", "mapped_trade_service", "estimated_job_value_usd",
            "contacts_found", "status", "va_action_required", "va_sop_guidance",
            "verification_url"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for item in unmatched_records:
            writer.writerow({
                "lead_id": item["lead_id"],
                "case_number": item["case_number"],
                "property_address": item["property_address"],
                "entity_name": item["entity_name"],
                "violation_summary": item["violation_summary"],
                "mapped_trade_service": item["mapped_trade_service"],
                "estimated_job_value_usd": f"${item['estimated_job_value_usd']:,.2f}",
                "contacts_found": item["contacts_count"],
                "status": "REQUIRES_MANUAL_ENRICHMENT",
                "va_action_required": "Identify missing Property Manager or Corporate Officer via CA SOS or County Assessor",
                "va_sop_guidance": "Search CA bizfile online with entity name, or search LA County Assessor Portal with address to find deed owner.",
                "verification_url": item["deep_link_verification_url"]
            })

    total_pipeline_val = sum(item["estimated_job_value_usd"] for item in enriched_records)
    total_contacts = sum(item["contacts_count"] for item in enriched_records)

    print("\n======================================================================")
    print(" >>> STAGE 4 ENRICHMENT & STAGE 6 EXPORT COMPLETE! <<<")
    print("======================================================================")
    print(f"  * Total Leads Processed          : {len(enriched_records)}")
    print(f"  * Total Decision-Makers Extracted : {total_contacts}")
    print(f"  * Cumulative Pipeline Valuation  : ${total_pipeline_val:,.2f}")
    print(f"  * Leads In Daily VA Review Queue  : {len(unmatched_records)}")
    print(f"  * Supabase Tables Populated       : daily_commercial_leads_24h, master_enriched_leads")
    print(f"  * Master Enriched Export CSV      : {os.path.abspath(master_csv_path)}")
    print(f"  * Daily VA Review Sheet CSV       : {os.path.abspath(va_sheet_path)}")
    print("======================================================================\n")


if __name__ == "__main__":
    run_stage4_decision_maker_pipeline()
