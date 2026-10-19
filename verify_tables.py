import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
url = os.getenv("SUPABASE_URL", "").replace("/rest/v1", "").rstrip("/")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(url, key)

tables = [
    ("daily_fire_violations_24h", "id"),
    ("raw_municipal_violations", "id"),
    ("commercial_fire_leads", "lead_id"),
    ("central_sent_suppression_database", "id")
]

print("Checking Supabase tables...")
for t, col in tables:
    try:
        res = supabase.table(t).select(col, count="exact").limit(1).execute()
        print(f" [+] Table '{t}': LIVE (rows: {res.count})")
    except Exception as e:
        print(f" [!] Table '{t}': ERROR -> {e}")
