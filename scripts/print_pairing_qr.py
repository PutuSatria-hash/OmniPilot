"""Print connection URLs and a scannable pairing QR Code for OmniPilot Hub."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import qrcode

from backend.core.config import get_settings
from backend.modules.pc_control import PCControlService


def main() -> None:
    s = get_settings()
    pc = PCControlService(s)
    t = pc.get_telemetry()

    local_ip = t["local_ip"]
    tailscale_ip = t["tailscale_ip"]
    host_ip = tailscale_ip or local_ip
    pair_url = f"http://{host_ip}:{s.port}/?token={s.api_auth_token}"

    print(f"Local URL     : http://127.0.0.1:{s.port}")
    print(f"LAN URL       : http://{local_ip}:{s.port}")
    if tailscale_ip:
        print(f"Tailscale URL : http://{tailscale_ip}:{s.port}")
    else:
        print("Tailscale URL : (Belum terdeteksi - login Tailscale untuk akses jarak jauh)")

    print("\nScan QR Code ini dari kamera HP (otomatis mengisi token login):")
    print(pair_url)
    qr = qrcode.QRCode(border=1)
    qr.add_data(pair_url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


if __name__ == "__main__":
    main()
