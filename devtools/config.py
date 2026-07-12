"""DevTools configuration — read from environment, no hardcoded values."""
from __future__ import annotations

import os

BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://localhost:8000")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))
LOGS_AUTO_REFRESH_SECONDS = int(os.getenv("LOGS_AUTO_REFRESH_SECONDS", "5"))
