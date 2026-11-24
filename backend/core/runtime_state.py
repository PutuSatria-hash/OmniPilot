"""Shared runtime state (e.g., active Cloudflare tunnel URL) between the supervisor and the Hub."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.core.config import BASE_DIR

RUNTIME_STATE_FILE = BASE_DIR / "data" / "runtime_state.json"

# Quick tunnel hostnames look like https://brave-fox-123.trycloudflare.com (exclude api.trycloudflare.com)
_TUNNEL_URL_RE = re.compile(r"https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)


def extract_tunnel_url(line: str) -> Optional[str]:
    """Return the public quick-tunnel URL found in a cloudflared log line, if any."""
    match = _TUNNEL_URL_RE.search(line or "")
    return match.group(0).lower() if match else None


def load_runtime_state(path: Optional[Path] = None) -> dict[str, Any]:
    target = path or RUNTIME_STATE_FILE
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_runtime_state(updates: dict[str, Any], path: Optional[Path] = None) -> dict[str, Any]:
    """Merge updates into the runtime state file atomically."""
    target = path or RUNTIME_STATE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    state = load_runtime_state(target)
    state.update(updates)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(target)
    return state
