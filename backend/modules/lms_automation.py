"""Playwright-based LMS Automation with Persistent Session & Mandatory Approval Before Submit."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from backend.core.approval_gate import ApprovalGate
from backend.core.config import Settings

logger = logging.getLogger(__name__)


class LMSAutomationService:
    """Automates LMS inspection and assignment submission using a persistent Chromium session."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def get_status(self) -> dict[str, Any]:
        profile_exists = any(self.settings.browser_profile_dir.iterdir())
        return {
            "lms_base_url": self.settings.lms_base_url or None,
            "platform": self.settings.lms_platform,
            "session_saved": profile_exists,
            "hint": (
                "Profil browser LMS siap dipakai."
                if profile_exists
                else "Isi LMS_BASE_URL di .env lalu jalankan sesi login sekali di Laptop agar cookie SSO/LMS tersimpan."
            ),
        }

    async def inspect_dashboard(self, target_url: Optional[str] = None) -> dict[str, Any]:
        """Open LMS with saved cookies, take screenshot, and extract visible assignment items."""
        url = (target_url or self.settings.lms_base_url).strip()
        if not url:
            return {
                "status": "not_configured",
                "message": "LMS_BASE_URL belum diisi di file .env.",
            }

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return {"status": "error", "message": "Playwright belum terpasang di environment."}

        screenshot_path = self.settings.screenshots_dir / "lms_latest.png"
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(self.settings.browser_profile_dir),
                headless=self.settings.lms_headless,
                viewport={"width": 1366, "height": 900},
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            page_title = await page.title()
            await page.screenshot(path=str(screenshot_path), full_page=False)

            # Extract potential assignment/deadline links generically across Moodle/Classroom/Canvas
            items = await page.evaluate(
                """() => {
                    const selectors = 'a, .event, .activityinstance, [data-region="event-item"]';
                    const nodes = Array.from(document.querySelectorAll(selectors));
                    const found = [];
                    for (const el of nodes) {
                        const txt = (el.innerText || '').trim();
                        if (txt.length > 4 && txt.length < 180 && /tugas|assign|quiz|deadline|submit|due|kumpul/i.test(txt)) {
                            found.push({ text: txt, href: el.href || '' });
                        }
                        if (found.length >= 15) break;
                    }
                    return found;
                }"""
            )
            await context.close()

        return {
            "status": "ok",
            "url": url,
            "page_title": page_title,
            "detected_items": items,
            "screenshot_path": str(screenshot_path),
        }

    async def queue_submit_assignment(
        self,
        assignment_url: str,
        file_path: str,
        notes: str,
        approval_gate: ApprovalGate,
    ) -> dict[str, Any]:
        """Stage an LMS assignment submission and require Boss confirmation before final upload."""
        target_file = Path(file_path)
        if not target_file.exists():
            raise FileNotFoundError(f"File tugas tidak ditemukan: {file_path}")

        approval = await approval_gate.request_approval(
            action_type="submit_lms",
            title=f"Upload Tugas LMS: {target_file.name}",
            summary=(
                f"URL Tugas: {assignment_url}\n"
                f"File: {target_file.name}\n"
                f"Catatan: {notes or '-'}\n"
                "Klik Approve untuk membuka halaman upload & mengunggah file."
            ),
            payload={
                "assignment_url": assignment_url,
                "file_path": str(target_file),
                "notes": notes,
            },
        )
        return {
            "status": "pending_approval",
            "approval_id": approval["id"],
            "message": "Pengumpulan tugas LMS menunggu konfirmasi Approve dari Boss.",
        }

    async def execute_submit_assignment(self, payload: dict[str, Any]) -> str:
        """Upload file to the LMS file input field after Boss approves."""
        from playwright.async_api import async_playwright

        url = payload["assignment_url"]
        file_path = payload["file_path"]
        screenshot_path = self.settings.screenshots_dir / "lms_submit_proof.png"

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(self.settings.browser_profile_dir),
                headless=self.settings.lms_headless,
                viewport={"width": 1366, "height": 900},
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1500)

            file_input = page.locator("input[type='file']").first
            if await file_input.count() == 0:
                await page.screenshot(path=str(screenshot_path))
                await context.close()
                return (
                    f"Halaman LMS dibuka ({url}), namun input file upload tidak langsung terlihat "
                    "(kemungkinan perlu klik tombol 'Add submission' khusus LMS Anda). Screenshot tersimpan."
                )

            await file_input.set_input_files(file_path)
            await page.wait_for_timeout(1500)
            await page.screenshot(path=str(screenshot_path))
            await context.close()

        return (
            f"File '{Path(file_path).name}' berhasil dimasukkan ke halaman tugas LMS ({url}). "
            f"Screenshot bukti tersimpan di {screenshot_path.name}."
        )
