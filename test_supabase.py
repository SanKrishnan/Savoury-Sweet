import os
from dotenv import load_dotenv
from supabase import create_client
import traceback

load_dotenv("c:/Users/Sanjana/Downloads/Savoury-Sweet-main/Savoury-Sweet-main/.env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("No supabase credentials!")
    exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

try:
    print("Testing insert...")
    response = supabase.table("orders").insert({
        "customer": "Test User",
        "items": [{"name": "Test", "quantity": 1, "price": 10}],
        "total": 10,
        "invoice_url": "http://test.com"
    }).execute()
    print("Insert success:", response)
except Exception as e:
    print("Insert error:")
    traceback.print_exc()
