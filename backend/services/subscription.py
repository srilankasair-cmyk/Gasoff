"""Subscription manager — file-based user state tracking.

Tracks free trial usage and subscription status.
Uses /tmp for cross-worker persistence on PythonAnywhere.
"""

import json
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

DATA_FILE = "/tmp/gasoff_subscriptions.json"
FREE_ANALYSES = 1          # Number of free analyses
STAR_PRICE = 150            # Price in Telegram Stars
SUBSCRIPTION_DAYS = 30     # Days per subscription

_lock = threading.Lock()


def _load() -> dict:
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(DATA_FILE) or "/tmp", exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)


def get_user(user_id: int) -> dict:
    """Return user record, creating default if missing."""
    with _lock:
        data = _load()
        uid = str(user_id)
        if uid not in data:
            data[uid] = {
                "analyses_used": 0,
                "subscribed": False,
                "subscribe_until": 0,
            }
            _save(data)
        return dict(data[uid])


def _write_user(user_id: int, record: dict) -> None:
    with _lock:
        data = _load()
        data[str(user_id)] = record
        _save(data)


def can_analyze(user_id: int) -> bool:
    """Check if user can perform an analysis (free trial or subscribed)."""
    rec = get_user(user_id)
    # Check subscription
    if rec.get("subscribed") and rec.get("subscribe_until", 0) > time.time():
        return True
    # Check free trial
    if rec.get("analyses_used", 0) < FREE_ANALYSES:
        return True
    return False


def use_analysis(user_id: int) -> None:
    """Increment analysis count."""
    rec = get_user(user_id)
    rec["analyses_used"] = rec.get("analyses_used", 0) + 1
    _write_user(user_id, rec)


def activate_subscription(user_id: int) -> None:
    """Activate subscription (called after successful Stars payment)."""
    rec = get_user(user_id)
    rec["subscribed"] = True
    rec["subscribe_until"] = int(time.time()) + SUBSCRIPTION_DAYS * 86400
    _write_user(user_id, rec)
    logger.info("Subscription activated for user %s until %s",
                user_id, rec["subscribe_until"])


def remaining_free(user_id: int) -> int:
    """Return remaining free analyses."""
    rec = get_user(user_id)
    return max(0, FREE_ANALYSES - rec.get("analyses_used", 0))
