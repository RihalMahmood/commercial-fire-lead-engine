"""
Filter LA_Commercial_Fire_Leads_Valuation_Audit.csv to remove resolved/fixed violations,
leaving ONLY active, un-fixed fire deficiencies.
"""

import os
import csv
import time
import urllib.parse
import requests

INPUT_CSV = "LA_Commercial_Fire_Leads_Valuation_Audit.csv"
OUTPUT_ACTIVE_CSV = "LA_Commercial_Fire_Leads_ACTIVE_UNRESOLVED.csv"
OUTPUT_RESOLVED_CSV = "LA_Commercial_Fire_Leads_RESOLVED_ARCHIVE.csv"

def main():
    print("=" * 75)
    print(" AUDITING & FILTERING 1,448 HISTORICAL LEADS FOR ACTIVE DEFICIENCIES")
    print(" Source: data.lacity.org (LADBS Inspections Feed: 9w5z-rg2h)")
    print("=" * 75)

    with open(INPUT_CSV, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    print(f"[*] Loaded {len(all_rows)} total rows from {INPUT_CSV}")

    # Extract all unique permits
    unique_permits = list(set(r["Case / Permit Number"].split("_")[0].replace("-", " ") for r in all_rows))
    print(f"[*] Found {len(unique_permits)} unique permits to verify live against City database...")

    # Query LADBS SODA API in batches of 40 permits
    batch_size = 40
    permit_inspections = {}
    total_fetched = 0

    for i in range(0, len(unique_permits), batch_size):
        chunk = unique_permits[i:i + batch_size]
        quoted_permits = ", ".join([f'"{p}"' for p in chunk])
        where_clause = f"permit in ({quoted_permits})"
        encoded_where = urllib.parse.quote(where_clause)
        url = f"https://data.lacity.org/resource/9w5z-rg2h.json?$where={encoded_where}&$limit=5000"

        for attempt in range(3):
            try:
                resp = requests.get(url, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data:
                        p = item.get("permit")
                        if p not in permit_inspections:
                            permit_inspections[p] = []
                        permit_inspections[p].append(item)
                    total_fetched += len(data)
                    break
                else:
                    time.sleep(1)
            except Exception as e:
                time.sleep(1)

        print(f"  [+] Checked {min(i + batch_size, len(unique_permits))} / {len(unique_permits)} permits ({total_fetched} inspection logs analyzed)...")
        time.sleep(0.1)

    print(f"[OK] Fetched all live inspection records across {len(permit_inspections)} permits.\n")

    # Evaluate each row
    active_rows = []
    resolved_rows = []

    for r in all_rows:
        case = r["Case / Permit Number"]
        parts = case.split("_")
        permit = parts[0].replace("-", " ")
        fire_type = parts[1] if len(parts) > 1 else ""
        event_date = parts[2] if len(parts) > 2 else ""

        insps = permit_inspections.get(permit, [])
        # Sort descending by inspection_date
        insps.sort(key=lambda x: str(x.get("inspection_date") or ""), reverse=True)

        is_fixed = False
        fix_evidence = ""

        for insp in insps:
            idate = str(insp.get("inspection_date") or "")[:10]
            iresult = str(insp.get("inspection_result") or "").strip()
            itype = str(insp.get("inspection") or "").strip()

            # 1. Check if entire permit was signed off / completed on or after the failure date
            if idate >= event_date and iresult in ["Permit Finaled", "CofO Issued", "Permit Closed", "CofO Corrected"]:
                is_fixed = True
                fix_evidence = f"Permit Finaled on {idate} ({iresult})"
                break

            # 2. Check if fire/life-safety inspection was approved on or after failure date
            clean_itype = "".join(c for c in itype if c.isalnum()).lower()
            clean_fire = fire_type.lower()
            
            is_same_fire_trade = (
                clean_fire in clean_itype or 
                clean_itype in clean_fire or 
                any(k in clean_itype for k in ["smoke", "sprinkler", "hydro", "alarm", "hood", "fire", "standpipe", "backflow"])
            )

            if idate >= event_date and is_same_fire_trade:
                if iresult in ["Approved", "Conditional Approval", "OK for CofO", "OK for CofC", "SGSOV Approved"]:
                    is_fixed = True
                    fix_evidence = f"{itype} Approved on {idate} ({iresult})"
                    break

        r_copy = dict(r)
        if is_fixed:
            r_copy["Resolution Status"] = "RESOLVED / CLOSED"
            r_copy["Resolution Evidence"] = fix_evidence
            resolved_rows.append(r_copy)
        else:
            r_copy["Compliance Status"] = "ACTIVE UNRESOLVED DEFICIENCY"
            r_copy["Latest Inspection Check"] = "Still Open / Corrections Pending / CofO Hold Active"
            active_rows.append(r_copy)

    # Export Active Leads CSV
    fieldnames_active = list(all_rows[0].keys()) + ["Compliance Status", "Latest Inspection Check"]
    with open(OUTPUT_ACTIVE_CSV, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames_active)
        writer.writeheader()
        writer.writerows(active_rows)

    # Export Resolved Archive CSV
    fieldnames_resolved = list(all_rows[0].keys()) + ["Resolution Status", "Resolution Evidence"]
    with open(OUTPUT_RESOLVED_CSV, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames_resolved)
        writer.writeheader()
        writer.writerows(resolved_rows)

    total_active_val = sum(float(r.get("Estimated Job Value ($)", "0").replace("$", "").replace(",", "") or 0) for r in active_rows)
    total_resolved_val = sum(float(r.get("Estimated Job Value ($)", "0").replace("$", "").replace(",", "") or 0) for r in resolved_rows)

    print("\n" + "=" * 75)
    print(" >>> AUDIT & RESOLUTION FILTER COMPLETE! <<<")
    print("=" * 75)
    print(f"  • Total Historical Records Audited     : {len(all_rows):,} (100.0%)")
    print(f"  • RESOLVED / FIXED (Discarded)         : {len(resolved_rows):,} ({(len(resolved_rows)/len(all_rows))*100:.1f}%)")
    print(f"  • ACTIVE UNRESOLVED DEFICIENCIES       : {len(active_rows):,} ({(len(active_rows)/len(all_rows))*100:.1f}%)")
    print(f"  • Active Unresolved Pipeline Value     : ${total_active_val:,.2f}")
    print(f"  • Resolved Pipeline Value (Discarded)  : ${total_resolved_val:,.2f}")
    print(f"  • Active Unresolved Leads CSV Export   : {os.path.abspath(OUTPUT_ACTIVE_CSV)}")
    print(f"  • Resolved Leads Audit CSV Export      : {os.path.abspath(OUTPUT_RESOLVED_CSV)}")
    print("=" * 75)

if __name__ == "__main__":
    main()
