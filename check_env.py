from app.config import settings
import os
import sys

print(f"CWD: {os.getcwd()}")
print(f"DEV_MODE from settings: {settings.dev_mode}")
print(f"DATABASE_URL from settings: {settings.database_url}")
print(f"DEV_MODE env var: {os.getenv('DEV_MODE')}")
