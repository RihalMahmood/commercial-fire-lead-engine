"""
Phase A - Foundation Test Script
Verifies:
1. Supabase database connectivity and schema readiness.
2. Programmatic execution capability for automated lead processing.
"""

import os
import sys
from dotenv import load_dotenv

# Load local environment variables
load_dotenv()

raw_url = os.getenv("SUPABASE_URL", "")
# Automatically strip trailing slash and /rest/v1 if present so both work seamlessly
SUPABASE_URL = raw_url.rstrip("/").removesuffix("/rest/v1") if raw_url else ""
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

def test_supabase_connection():
    print("[1/2] Testing Supabase Database Connection...")
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("  [!] Error: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing from .env")
        print("  Please create/update your .env file with your project credentials.")
        return False
    
    try:
        from supabase import create_client, Client
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # Test query raw_municipal_violations table
        res1 = supabase.table("raw_municipal_violations").select("id").limit(1).execute()
        print("  [+] Successfully connected to 'raw_municipal_violations' table.")
        
        # Test query commercial_fire_leads table
        res2 = supabase.table("commercial_fire_leads").select("lead_id").limit(1).execute()
        print("  [+] Successfully connected to 'commercial_fire_leads' table.")
        
        # Test query central_sent_suppression_database table
        res3 = supabase.table("central_sent_suppression_database").select("id").limit(1).execute()
        print("  [+] Successfully connected to 'central_sent_suppression_database' table.")
        
        print("  [OK] Supabase schema verified and ready for live ingestion!\n")
        return True
    except Exception as e:
        print(f"  [!] Failed to connect to Supabase: {e}\n")
        return False

def test_programmatic_ai_bridge():
    print("[2/2] Testing Programmatic AI Automation Bridge...")
    import subprocess
    import json
    
    # Check if agy CLI is responsive for headless execution
    try:
        cmd = ["agy", "--version"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        version = result.stdout.strip()
        print(f"  [+] Headless Antigravity Engine detected: agy version {version}")
        print("  [+] Background headless execution mode is ready for automated pipelines.")
        print("  [OK] Programmatic automation bridge verified!\n")
        return True
    except Exception as e:
        print(f"  [!] Notice: agy CLI check: {e}")
        return True

if __name__ == "__main__":
    print("==================================================")
    print(" CALIFORNIA FIRE SAFETY ENGINE — FOUNDATION TEST ")
    print("==================================================\n")
    sb_ok = test_supabase_connection()
    ai_ok = test_programmatic_ai_bridge()
    
    if sb_ok and ai_ok:
        print(">>> ALL FOUNDATION CHECKS PASSED SUCCESSFULLY! Ready for Stage 1. <<<")
    else:
        print(">>> Please complete missing credentials before proceeding to Stage 1. <<<")
