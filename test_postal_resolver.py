import os
import re
import json
import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

key = os.getenv("SERPER_API_KEY")
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
leads = supabase.table("commercial_fire_leads").select("property_address, zip_code").execute().data

KNOWN_COMMUNITIES = [
    "Woodland Hills", "North Hollywood", "Sherman Oaks", "Beverly Hills",
    "Van Nuys", "Encino", "Tarzana", "Studio City", "Canoga Park",
    "Chatsworth", "Granada Hills", "Reseda", "Sylmar", "Pacoima",
    "Sun Valley", "Tujunga", "Porter Ranch", "West Hills", "Winnetka",
    "Valley Village", "Century City", "Westwood", "Brentwood", "Venice",
    "Mar Vista", "San Pedro", "Wilmington", "Hollywood", "Playa del Rey",
    "Los Angeles"
]

def clean_address(raw_addr):
    if not raw_addr:
        return ""
    addr = raw_addr.strip()
    patterns = [
        r'\s+(?:NO|STE|SUITE|APT|UNIT|SPCE|BLDG|FL|RM|G\d|#)\s*.*$',
        r'-\d+\s*1/2',
        r'\s+1/2',
        r'\s+\d+\s*-\s*\d+.*$',
        r'\s+&\s+.*$',
    ]
    for p in patterns:
        addr = re.sub(p, '', addr, flags=re.IGNORECASE).strip()
    if 'aubrey' in addr.lower():
        addr = re.sub(r'\bW\b\s*', '', addr, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', addr).title()

def resolve_postal(street, existing_zip):
    if existing_zip and len(str(existing_zip)) == 5 and str(existing_zip).startswith("9"):
        return "Los Angeles", str(existing_zip)
    if key:
        try:
            r = requests.post("https://google.serper.dev/search", headers={"X-API-KEY": key, "Content-Type": "application/json"}, json={"q": f"{street} Los Angeles CA", "num": 3}, timeout=10).json()
            text = " ".join([o.get("title", "") + " " + o.get("snippet", "") for o in r.get("organic", [])])
            if r.get("knowledgeGraph"):
                text += " " + json.dumps(r.get("knowledgeGraph"))
            
            # Find 5-digit California ZIP code (always starts with 9)
            zip_matches = re.findall(r'\b(9\d{4})\b', text)
            resolved_zip = zip_matches[0] if zip_matches else None
            
            # Match known LA postal community
            resolved_city = "Los Angeles"
            for comm in KNOWN_COMMUNITIES:
                if re.search(r'\b' + re.escape(comm) + r'\b', text, flags=re.IGNORECASE):
                    resolved_city = comm
                    break
                    
            if resolved_zip:
                return resolved_city, resolved_zip
        except Exception:
            pass
    return "Los Angeles", None

for l in leads:
    cl = clean_address(l["property_address"])
    city, z = resolve_postal(cl, l.get("zip_code"))
    print(f'{l["property_address"]} -> Street: "{cl}" | City: "{city}" | ZIP: "{z}"')
