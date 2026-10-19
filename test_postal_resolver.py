import os
import re
from dotenv import load_dotenv
from supabase import create_client
import requests

load_dotenv()
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
batchdata_key = os.getenv("BATCHDATA_API_KEY")

def normalize_la_address(raw_addr, existing_zip=None):
    if not raw_addr:
        return "", "Los Angeles", existing_zip
    addr = raw_addr.strip()
    for p in [r'\s+(?:NO|STE|SUITE|APT|UNIT|SPCE|BLDG|FL|RM|G\d|#)\s*.*$', r'-\d+\s*1/2', r'\s+1/2', r'\s+\d+\s*-\s*\d+.*$', r'\s+&\s+.*$']:
        addr = re.sub(p, '', addr, flags=re.IGNORECASE).strip()
    if 'aubrey' in addr.lower():
        addr = re.sub(r'\bW\b\s*', '', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\s+', ' ', addr).title()

    city = "Los Angeles"
    al = addr.lower()
    if 'ventura' in al and any(num in al for num in ['19', '20', '21', '22', '23']):
        city = "Woodland Hills"
    elif 'rhodes' in al:
        city = "North Hollywood"
    elif 'chandler' in al:
        city = "Sherman Oaks"
    elif 'aubrey' in al:
        city = "Beverly Hills"
        
    return addr, city, existing_zip

leads = sb.table("commercial_fire_leads").select("property_address, zip_code").execute().data

requests_payload = []
for l in leads:
    st, city, z = normalize_la_address(l["property_address"], l.get("zip_code"))
    req = {
        "propertyAddress": {
            "street": st,
            "city": city,
            "state": "CA"
        }
    }
    if z and len(str(z)) == 5 and str(z).startswith("9"):
        req["propertyAddress"]["zip"] = str(z)
    requests_payload.append(req)

headers = {"Authorization": f"Bearer {batchdata_key}", "Content-Type": "application/json"}
res = requests.post("https://api.batchdata.com/api/v1/property/skip-trace", headers=headers, json={"requests": requests_payload}).json()
persons = res.get("results", {}).get("persons", [])
matched = [p for p in persons if p.get("meta", {}).get("matched", False)]
print(f"Zero-Dependency BatchData Results: {len(matched)} / {len(leads)} Matched!")
for idx, p in enumerate(matched):
    print(f" [{idx+1}] {p.get('name', {}).get('full')} | Phones: {len(p.get('phoneNumbers', []))}")
