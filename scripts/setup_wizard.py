"""Interactive Setup Wizard for OmniPilot Hub (.env generator & updater).

Memudahkan pengguna baru yang baru meng-clone repository untuk mengatur file .env
tanpa harus mencari baris satu per satu. Nilai yang sudah ada akan dipertahankan
jika pengguna menekan Enter.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT / ".env.example"
ENV_FILE = ROOT / ".env"

PLACEHOLDER_TOKENS = {
    "",
    "CHANGE_ME_TO_A_STRONG_SECRET_TOKEN",
    "CHANGE_ME_GENERATE_A_SECRET_TOKEN",
    "omnipilot_boss_local_9f4a2c8e7d1b6035",
}


def load_env_map(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip()
    return values


def mask_secret(val: str) -> str:
    if not val:
        return "(kosong)"
    if len(val) <= 6:
        return "******"
    return f"****{val[-4:]}"


def write_env_preserving_template(updates: dict[str, str]) -> None:
    """Write .env based on .env.example template (or existing .env) while preserving comments."""
    base_path = ENV_FILE if ENV_FILE.exists() else ENV_EXAMPLE
    lines = base_path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    output: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                output.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        output.append(line)

    for key, val in updates.items():
        if key not in seen:
            output.append(f"{key}={val}")

    ENV_FILE.write_text("\n".join(output) + "\n", encoding="utf-8")


def ask(label: str, current: str = "", default_suggestion: str = "", secret: bool = False, hint: str = "") -> str:
    if hint:
        print(f"  Info: {hint}")
    display_curr = mask_secret(current) if (secret and current) else (current or "(kosong)")
    if current:
        prompt = f"  {label} [saat ini: {display_curr} | Enter = pertahankan]: "
    elif default_suggestion:
        prompt = f"  {label} [Enter = pakai '{default_suggestion}']: "
    else:
        prompt = f"  {label} [Enter = lewati]: "

    entered = input(prompt).strip()
    if entered:
        return entered
    if current:
        return current
    return default_suggestion


def bootstrap_env_noninteractive() -> Path:
    """Create .env from .env.example with a random API_AUTH_TOKEN if .env does not exist yet."""
    if ENV_FILE.exists():
        return ENV_FILE
    token = f"omnipilot_{secrets.token_urlsafe(20)}"
    write_env_preserving_template(
        {
            "API_AUTH_TOKEN": token,
            "ANTIGRAVITY_WORKSPACE_DEFAULT": str(ROOT),
        }
    )
    print(f"[OK] File .env otomatis dibuat dengan API_AUTH_TOKEN acak yang aman.")
    return ENV_FILE


def run_wizard() -> None:
    print("=" * 68)
    print("  OmniPilot Hub - Interactive Setup Wizard (.env Configuration)")
    print("=" * 68)
    print("Tekan ENTER untuk melewati kolom opsional atau mempertahankan nilai lama.\n")

    current = load_env_map(ENV_FILE) if ENV_FILE.exists() else load_env_map(ENV_EXAMPLE)
    updates: dict[str, str] = {}

    # 1. Security & Core
    print("[1/5] Keamanan & Zona Waktu")
    existing_token = current.get("API_AUTH_TOKEN", "")
    if existing_token in PLACEHOLDER_TOKENS:
        suggested = f"omnipilot_{secrets.token_urlsafe(20)}"
        updates["API_AUTH_TOKEN"] = ask(
            "API_AUTH_TOKEN",
            current="",
            default_suggestion=suggested,
            secret=False,
            hint="Sandi rahasia untuk login Web Dashboard & akses dari PC Lab/HP.",
        )
    else:
        updates["API_AUTH_TOKEN"] = ask(
            "API_AUTH_TOKEN",
            current=existing_token,
            secret=True,
            hint="Sandi rahasia login Web Dashboard (sudah terisi).",
        )

    updates["TIMEZONE"] = ask(
        "TIMEZONE",
        current=current.get("TIMEZONE", ""),
        default_suggestion="Asia/Makassar",
        hint="Pilihan Indonesia: Asia/Jakarta (WIB), Asia/Makassar (WITA), Asia/Jayapura (WIT).",
    )
    updates["ANTIGRAVITY_WORKSPACE_DEFAULT"] = current.get("ANTIGRAVITY_WORKSPACE_DEFAULT") or str(ROOT)

    # 2. AI Waterfall (Free Providers)
    print("\n[2/5] AI Provider Gratis (Cukup isi minimal 1 agar Chat Bebas & Voice Note aktif)")
    updates["GEMINI_API_KEY"] = ask(
        "GEMINI_API_KEY",
        current=current.get("GEMINI_API_KEY", ""),
        secret=True,
        hint="Gratis di: https://aistudio.google.com/app/api-keys",
    )
    updates["GROQ_API_KEY"] = ask(
        "GROQ_API_KEY (disarankan untuk Voice Note & cadangan super cepat)",
        current=current.get("GROQ_API_KEY", ""),
        secret=True,
        hint="Gratis di: https://console.groq.com/keys",
    )
    updates["OPENROUTER_API_KEY"] = ask(
        "OPENROUTER_API_KEY (opsional cadangan model :free)",
        current=current.get("OPENROUTER_API_KEY", ""),
        secret=True,
        hint="Gratis di: https://openrouter.ai/keys",
    )

    # 3. Telegram Bot
    print("\n[3/5] Remote Control via Telegram Bot (Sangat Disarankan)")
    updates["TELEGRAM_BOT_TOKEN"] = ask(
        "TELEGRAM_BOT_TOKEN",
        current=current.get("TELEGRAM_BOT_TOKEN", ""),
        secret=True,
        hint="Buat bot baru di Telegram @BotFather dengan perintah /newbot.",
    )
    updates["TELEGRAM_ALLOWED_USER_ID"] = ask(
        "TELEGRAM_ALLOWED_USER_ID",
        current=current.get("TELEGRAM_ALLOWED_USER_ID", ""),
        hint="Cek angka ID akun Telegram Anda di @userinfobot agar bot terkunci khusus untuk Anda.",
    )

    # 4. Calendar & LMS
    print("\n[4/5] Jadwal Google Calendar & LMS Kampus (Opsional)")
    updates["GOOGLE_CALENDAR_ICS_URL"] = ask(
        "GOOGLE_CALENDAR_ICS_URL",
        current=current.get("GOOGLE_CALENDAR_ICS_URL", ""),
        secret=True,
        hint="Google Calendar Settings -> Integrate calendar -> salin 'Secret address in iCal format' (/private-.../basic.ics).",
    )
    updates["LMS_BASE_URL"] = ask(
        "LMS_BASE_URL",
        current=current.get("LMS_BASE_URL", ""),
        hint="Contoh: https://elearning.kampus.ac.id (lalu jalankan 4_LOGIN_LMS.bat untuk login sekali).",
    )

    # 5. Remote Desktop & WhatsApp
    print("\n[5/5] Remote Desktop & WhatsApp Safe Bridge (Opsional)")
    updates["RUSTDESK_PC_ID"] = ask(
        "RUSTDESK_PC_ID",
        current=current.get("RUSTDESK_PC_ID", ""),
        hint="Angka ID 9 digit dari aplikasi RustDesk (tanpa spasi, JANGAN masukkan password).",
    )
    wa_ans = ask(
        "Aktifkan WhatsApp Bridge (true/false)",
        current=current.get("WHATSAPP_ENABLED", "false"),
        default_suggestion="false",
        hint="Set 'true' hanya jika Anda akan menjalankan 5_START_WHATSAPP_BRIDGE.bat.",
    )
    updates["WHATSAPP_ENABLED"] = "true" if wa_ans.lower() in ("true", "y", "yes", "ya", "1") else "false"

    write_env_preserving_template(updates)
    print("\n" + "=" * 68)
    print("  Konfigurasi .env berhasil disimpan!")
    print("  Langkah selanjutnya:")
    print("    - Jalankan START_ALL.bat (Server + Link Publik + Auto Telegram)")
    print("    - Atau jalankan 2_START_HUB.bat (Server Lokal / Tailscale + QR HP)")
    print("=" * 68)


if __name__ == "__main__":
    if "--bootstrap" in sys.argv:
        bootstrap_env_noninteractive()
    else:
        try:
            run_wizard()
        except KeyboardInterrupt:
            print("\nSetup dibatalkan.")
