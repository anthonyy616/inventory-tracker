"""Configuration loading from environment variables."""

import sys
from dotenv import load_dotenv
import os

load_dotenv()

# Required environment variables - fail fast if missing
REQUIRED_ENV_VARS = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "RECEIPT_SERVICE_CLIENT_ID",
]

missing_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing_vars:
    print(f"ERROR: Missing required environment variables: {', '.join(missing_vars)}")
    print("Please set them in your .env file or environment.")
    sys.exit(1)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
RECEIPT_SERVICE_CLIENT_ID = os.getenv("RECEIPT_SERVICE_CLIENT_ID")
RECEIPT_CALLBACK_SECRET = os.getenv("RECEIPT_CALLBACK_SECRET")
