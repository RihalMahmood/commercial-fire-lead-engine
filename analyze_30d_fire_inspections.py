import requests
import json
from datetime import datetime, timedelta, timezone

# 30-day window from latest available date
start_date = "2026-09-17T00:00:00.000"

print("=" * 75)
print(f" CITY OF LOS ANGELES 30-DAY INSPECTION AUDIT (LADBS Feed: 9w5z-rg2h)")
print(f" Analysis Window: Since {start_date[:10]} (Past 30 Days)")
print("=" * 75)

# 1. Total inspections across ALL trades
q_total = f"https://data.lacity.org/resource/9w5z-rg2h.json?$where=inspection_date >= '{start_date}'&$select=count(*)"
r_total = requests.get(q_total).json()
total_all = int(r_total[0].get("count", 0)) if r_total else 0
print(f"\n[1] Total City Inspections Across ALL Trades (30 Days): {total_all:,}")

# 2. All inspection results breakdown
q_all_res = f"https://data.lacity.org/resource/9w5z-rg2h.json?$where=inspection_date >= '{start_date}'&$select=inspection_result,count(*)&$group=inspection_result&$order=count(*) DESC"
r_all_res = requests.get(q_all_res).json()
print("\n[2] All Trades Results Breakdown:")
for r in r_all_res:
    res_name = r.get("inspection_result") or "None / Blank"
    print(f"    • {res_name:<30} : {int(r.get('count', 0)):,}")

# 3. Fire-related inspections query
# Distinct fire inspection types:
# Smoke Detectors, Fire Sprinkler, Overhead Hydro, Underground Hydro, Fire Alarm, Backflow, Kitchen Hood, etc.
fire_where = (
    f"inspection_date >= '{start_date}' and ("
    "upper(inspection) like '%FIRE%' or "
    "upper(inspection) like '%SPRINKLER%' or "
    "upper(inspection) like '%SMOKE%' or "
    "upper(inspection) like '%ALARM%' or "
    "upper(inspection) like '%HYDRO%' or "
    "upper(inspection) like '%HOOD%' or "
    "upper(inspection) like '%STANDPIPE%' or "
    "upper(inspection) like '%RISER%' or "
    "upper(inspection) like '%BACKFLOW%')"
)

q_fire_total = f"https://data.lacity.org/resource/9w5z-rg2h.json?$where={requests.utils.quote(fire_where)}&$select=count(*)"
r_fire_total = requests.get(q_fire_total).json()
total_fire = int(r_fire_total[0].get("count", 0)) if r_fire_total else 0
print(f"\n[3] Total FIRE-SPECIFIC Inspections (Passed + Failed): {total_fire:,}")

# 4. Fire-specific inspection results breakdown (Approved vs Failed)
q_fire_res = f"https://data.lacity.org/resource/9w5z-rg2h.json?$where={requests.utils.quote(fire_where)}&$select=inspection_result,count(*)&$group=inspection_result&$order=count(*) DESC"
r_fire_res = requests.get(q_fire_res).json()

print("\n[4] FIRE-SPECIFIC Inspections Result Breakdown:")
passed_count = 0
failed_count = 0
other_count = 0

passed_statuses = ["Approved", "Partial Approval"]
failed_statuses = [
    "Corrections Issued", "CofO on Hold", "Not Ready for Inspection",
    "No Access for Inspection", "Order to Comply Issued", "OTC Issued",
    "Fail", "Failed", "Violation"
]

print("  " + "-" * 70)
print(f"  {'Inspection Result Status':<35} | {'Category':<15} | {'Count':<10}")
print("  " + "-" * 70)

for r in r_fire_res:
    status = r.get("inspection_result") or "None / Blank"
    cnt = int(r.get("count", 0))
    if status in passed_statuses:
        category = "PASSED"
        passed_count += cnt
    elif any(f.lower() in status.lower() for f in failed_statuses):
        category = "FAILED / HOLD"
        failed_count += cnt
    else:
        category = "OTHER"
        other_count += cnt
    print(f"  {status:<35} | {category:<15} | {cnt:<10,}")

print("  " + "-" * 70)
print(f"\n[5] EXECUTIVE SUMMARY OF 30-DAY FIRE INSPECTIONS:")
print(f"  • Total Fire Inspections Conducted : {total_fire:,} (100.0%)")
print(f"  • PASSED (Approved)                : {passed_count:,} ({(passed_count/total_fire)*100:.1f}%) -> NOT A LEAD (Work Done)")
print(f"  • FAILED / DEFICIENT / ON HOLD     : {failed_count:,} ({(failed_count/total_fire)*100:.1f}%) -> TRUE TARGET LEADS (Needs Contractor)")
print(f"  • Other (Cancelled/Fees Due)       : {other_count:,} ({(other_count/total_fire)*100:.1f}%)")
print("=" * 75)
