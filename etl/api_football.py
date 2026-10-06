"""Shared api-football v3 client for the ETL.

Auth: the key comes from the ``API_FOOTBALL_KEY`` environment variable (CI,
from the repo's GitHub secrets) or, locally, from the stored
``custom.api-football`` connector attached as the ``x-apisports-key`` header
via dynamic_credentials surrogates. The raw key is never printed or logged.

Free-tier rules are enforced here: 7s sleep between calls, GET-only.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request

from .config import settings
from .logging_setup import get_logger

log = get_logger(__name__)

BASE = "https://v3.football.api-sports.io"
CREDENTIAL = "custom.api-football"


def _attach_auth(req: urllib.request.Request) -> None:
    env_key = os.environ.get("API_FOOTBALL_KEY")
    if env_key:
        req.add_header("x-apisports-key", env_key)
        return
    sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
    from dynamic_credentials import add_surrogate_to_request  # noqa: E402

    add_surrogate_to_request(req, CREDENTIAL, allowed_hosts=["v3.football.api-sports.io"])


def api_get(path: str, params: dict, *, sleep: bool = True) -> dict:
    """GET a v3 endpoint. Returns the decoded JSON body (errors/results/response)."""
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{BASE}{path}?{query}" if query else f"{BASE}{path}"
    req = urllib.request.Request(url, method="GET")
    _attach_auth(req)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", "replace")
        raise RuntimeError(f"api-football HTTP {exc.code} on {path}: {detail}") from exc
    data = json.loads(body)
    if sleep:
        time.sleep(settings.api_sleep_seconds)
    return data


def check_status() -> dict:
    """Quota/status check (does not count against the daily limit)."""
    return api_get("/status", {}, sleep=False)
