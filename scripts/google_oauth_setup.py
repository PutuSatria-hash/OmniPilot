"""One-time Google OAuth2 authorization helper for Gmail API."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from google_auth_oauthlib.flow import InstalledAppFlow
from backend.core.config import get_settings
from backend.modules.gmail_service import GMAIL_SCOPES


def main() -> None:
    settings = get_settings()
    creds_file = ROOT / settings.google_credentials_file
    token_file = ROOT / settings.google_token_file

    if not creds_file.exists():
        print(f"File OAuth client belum ditemukan di: {creds_file}")
        print("Unduh OAuth 2.0 Client ID (Desktop App) dari Google Cloud Console lalu simpan ke path tersebut.")
        return

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), GMAIL_SCOPES)
    creds = flow.run_local_server(port=0)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    print(f"Berhasil! Token Gmail tersimpan di: {token_file}")


if __name__ == "__main__":
    main()
