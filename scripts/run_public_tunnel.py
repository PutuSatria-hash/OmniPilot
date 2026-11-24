"""Public HTTPS Tunnel Supervisor: ensures OmniPilot Hub is running, starts cloudflared (HTTP/2 IPv4),
saves the public URL, copies it to clipboard, and pushes it to Boss's Telegram."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

from backend.core.config import get_settings
from backend.core.runtime_state import extract_tunnel_url, save_runtime_state

CLOUDFLARED_FALLBACKS = [
    Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe"),
    Path(r"C:\Program Files\cloudflared\cloudflared.exe"),
]


def find_cloudflared() -> Optional[str]:
    found = shutil.which("cloudflared")
    if found:
        return found
    for p in CLOUDFLARED_FALLBACKS:
        if p.exists():
            return str(p)
    return None


def is_hub_healthy(port: int) -> bool:
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=2.5)
        return r.status_code == 200
    except Exception:
        return False


def ensure_hub_running(port: int) -> Optional[subprocess.Popen[bytes]]:
    if is_hub_healthy(port):
        print("[OK] Server OmniPilot Hub sudah aktif.", flush=True)
        return None

    print("[INFO] Server OmniPilot Hub belum nyala. Menyalakan otomatis di latar belakang...", flush=True)
    venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    py_bin = str(venv_py if venv_py.exists() else Path(sys.executable))
    proc = subprocess.Popen(
        [py_bin, "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", str(port)],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(25):
        time.sleep(1.0)
        if is_hub_healthy(port):
            print("[OK] Server OmniPilot Hub berhasil aktif!", flush=True)
            return proc
    print("[PERINGATAN] Server membutuhkan waktu lebih lama untuk menyala, tetap melanjutkan tunnel...", flush=True)
    return proc


def copy_to_clipboard(text: str) -> bool:
    try:
        subprocess.run(["clip.exe"], input=text.encode("utf-8"), check=True, timeout=3)
        return True
    except Exception:
        return False


def notify_telegram(public_url: str) -> None:
    s = get_settings()
    token = s.telegram_bot_token.strip()
    chat_ids = s.allowed_telegram_ids
    if not token or not chat_ids:
        return

    direct_login_url = f"{public_url}/?token={s.api_auth_token}"
    text = (
        "[LINK PUBLIK INTERNET AKTIF]\n\n"
        f"1. Link Publik (untuk PC Lab / teman):\n{public_url}\n\n"
        f"2. Link Login Otomatis (khusus Boss, jangan dibagikan ke orang lain):\n{direct_login_url}"
    )
    for cid in chat_ids:
        try:
            httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": cid, "text": text, "disable_web_page_preview": True},
                timeout=8.0,
            )
        except Exception:
            pass


def main() -> int:
    s = get_settings()
    cf_bin = find_cloudflared()
    if not cf_bin:
        print("[ERROR] cloudflared.exe belum terpasang. Jalankan 1_SETUP_LAPTOP_ADMIN.bat terlebih dahulu.", flush=True)
        return 1

    hub_proc = ensure_hub_running(s.port)

    print("\nSedang meminta Link Publik HTTPS dari Cloudflare (tunggu 5-10 detik)...", flush=True)
    print("PENTING: JANGAN kirim angka 127.0.0.1 ke teman! Tunggu link https://....trycloudflare.com di bawah.\n", flush=True)

    cmd = [
        cf_bin,
        "tunnel",
        "--protocol",
        "http2",
        "--edge-ip-version",
        "4",
        "--no-autoupdate",
        "--url",
        f"http://127.0.0.1:{s.port}",
    ]

    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    announced_url: Optional[str] = None
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            found = extract_tunnel_url(line)
            if found and found != announced_url:
                announced_url = found
                save_runtime_state({"tunnel_url": found, "tunnel_mode": "cloudflare_quick"})
                copied = copy_to_clipboard(found)
                notify_telegram(found)

                print("\n" + "=" * 72, flush=True)
                print("  LINK PUBLIK INTERNET BERHASIL AKTIF! (BISA DIAKSES DARI MANA SAJA)", flush=True)
                print("=" * 72, flush=True)
                print(f"\n  Link Publik (Kirim yang ini ke Teman / Buka di PC Lab):\n  >>>  {found}  <<<\n", flush=True)
                print(f"  Link Login Instan (Khusus HP/Browser Pribadi Boss):\n  >>>  {found}/?token={s.api_auth_token}  <<<\n", flush=True)
                if copied:
                    print("  [OTOMATIS] Link publik sudah disalin ke Clipboard! Tinggal Ctrl+V di WhatsApp.", flush=True)
                print("  [OTOMATIS] Link publik juga sudah dikirim ke Telegram Bot Boss.", flush=True)
                print("  Biarkan jendela ini tetap terbuka selama link publik digunakan.", flush=True)
                print("=" * 72 + "\n", flush=True)
            elif "ERR" in line or "error" in line.lower():
                if "Cannot determine default origin certificate path" not in line and "origincert" not in line:
                    print(line.rstrip(), flush=True)
        return proc.wait()
    except KeyboardInterrupt:
        print("\nMenutup tunnel publik...", flush=True)
        return 0
    finally:
        save_runtime_state({"tunnel_url": None})
        try:
            proc.terminate()
        except Exception:
            pass
        if hub_proc is not None:
            try:
                hub_proc.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
