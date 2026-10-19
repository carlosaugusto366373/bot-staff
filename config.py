import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

TOKEN = os.getenv("DISCORD_TOKEN")

LOG_ORDERS_CHANNEL_ID = int(os.getenv("LOG_ORDERS_CHANNEL_ID", "0") or 0)
DELIVERED_CHANNEL_ID  = int(os.getenv("DELIVERED_CHANNEL_ID", "0") or 0)
CART_EVENTS_CHANNEL_ID = int(os.getenv("CART_EVENTS_CHANNEL_ID", "0") or 0)
CUSTOMER_ROLE_ID = int(os.getenv("CUSTOMER_ROLE_ID", "0") or 0)

RECOVERY_CHECK_INTERVAL_MIN = int(os.getenv("RECOVERY_CHECK_INTERVAL_MIN", "15"))
RECOVERY_MAX_ATTEMPTS = int(os.getenv("RECOVERY_MAX_ATTEMPTS", "3"))