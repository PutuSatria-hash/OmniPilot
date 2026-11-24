"""One-time visible Playwright browser launcher to save Boss's LMS login session (SSO/2FA safe)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.async_api import async_playwright
from backend.core.config import get_settings


async def main() -> None:
    settings = get_settings()
    url = settings.lms_base_url.strip() or input("Masukkan URL LMS Boss (misal https://lms.kampus.ac.id): ").strip()
    if not url:
        print("URL LMS kosong. Dibatalkan.")
        return

    print(f"Membuka browser LMS dengan profil tersimpan di: {settings.browser_profile_dir}")
    print("Silakan login secara normal (termasuk SSO/2FA). Setelah masuk dashboard LMS, tutup jendela browser.")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(settings.browser_profile_dir),
            headless=False,
            viewport={"width": 1366, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        try:
            await page.wait_for_event("close", timeout=0)
        except Exception:
            pass
        await context.close()

    print("Sesi login LMS tersimpan, Boss!")


if __name__ == "__main__":
    asyncio.run(main())
