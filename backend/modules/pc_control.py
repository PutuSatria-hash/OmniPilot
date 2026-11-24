"""Full PC Control Module: Telemetry, Live Screen Capture, App Launcher, and Safe Shell Execution."""

from __future__ import annotations

import asyncio
import ctypes
import io
import logging
import os
import platform
import re
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

import mss
import psutil
from PIL import Image

from backend.core.approval_gate import ApprovalGate
from backend.core.config import Settings
from backend.core.runtime_state import load_runtime_state

logger = logging.getLogger(__name__)

# Virtual-Key codes for native Windows remote keyboard shortcuts (zero bloat)
VK_MAP: dict[str, int] = {
    "enter": 0x0D,
    "return": 0x0D,
    "backspace": 0x08,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "ctrl": 0x11,
    "alt": 0x12,
    "shift": 0x10,
    "win": 0x5B,
    "f4": 0x73,
    "f5": 0x74,
}

# Patterns that require explicit Boss approval before executing on PC
# Processes that must never be closed remotely (Windows core + remote-access lifelines)
PROTECTED_PROCESS_NAMES = {
    "system",
    "system idle process",
    "registry",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "winlogon.exe",
    "services.exe",
    "lsass.exe",
    "lsaiso.exe",
    "svchost.exe",
    "fontdrvhost.exe",
    "dwm.exe",
    "explorer.exe",
    "memory compression",
    "securityhealthservice.exe",
    "msmpeng.exe",
    "tailscaled.exe",
    "tailscale-ipn.exe",
    "cloudflared.exe",
    "rustdesk.exe",
}

DANGEROUS_COMMAND_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bremove-item\b.*-recurse",
    r"\bdel\s+/[fsq]",
    r"\bformat\b",
    r"\bshutdown\b",
    r"\brestart-computer\b",
    r"\bstop-computer\b",
    r"\breg\s+delete\b",
    r"\bclear-disk\b",
    r"\bnet\s+user\b",
]


class PCControlService:
    """Provides remote PC management, screen streaming snapshots, app launches, and system audio alerts."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def get_telemetry(self) -> dict[str, Any]:
        """Collect real-time Windows PC hardware & network telemetry."""
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage(str(Path.home().anchor or "C:\\"))
        battery = psutil.sensors_battery()
        boot_ts = psutil.boot_time()
        uptime_minutes = int((time.time() - boot_ts) / 60)

        return {
            "hostname": socket.gethostname(),
            "os": f"{platform.system()} {platform.release()}",
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "ram_percent": vm.percent,
            "ram_used_gb": round(vm.used / (1024**3), 2),
            "ram_total_gb": round(vm.total / (1024**3), 2),
            "disk_percent": disk.percent,
            "battery_percent": round(battery.percent, 1) if battery else None,
            "battery_plugged": battery.power_plugged if battery else True,
            "uptime_minutes": uptime_minutes,
            "local_ip": self._detect_local_ip(),
            "tailscale_ip": self._detect_tailscale_ip(),
            "rustdesk_id": self.settings.rustdesk_pc_id or None,
            "sunshine_host": self.settings.sunshine_host_ip or self._detect_tailscale_ip(),
            "campus_tunnel_url": self.settings.campus_tunnel_url or load_runtime_state().get("tunnel_url") or None,
            "remote_input_enabled": self.settings.remote_input_enabled,
        }

    def _detect_local_ip(self) -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def _detect_tailscale_ip(self) -> Optional[str]:
        """Detect Tailscale CGNAT IPv4 (100.64.0.0/10) from local network interfaces."""
        try:
            for iface_name, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET and addr.address.startswith("100."):
                        second_octet = int(addr.address.split(".")[1])
                        if 64 <= second_octet <= 127:
                            return addr.address
        except Exception:
            pass
        return None

    def capture_screenshot_jpeg(self, quality: int = 65, max_width: int = 1280) -> bytes:
        """Capture primary desktop monitor as optimized JPEG bytes for low-latency HP preview."""
        with mss.mss() as sct:
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        if img.width > max_width:
            ratio = max_width / float(img.width)
            img = img.resize((max_width, int(img.height * ratio)), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()

    def launch_app(self, app_name: str, target_path: Optional[str] = None) -> dict[str, Any]:
        """Launch Antigravity, VS Code, Chrome, Terminal, or any local application."""
        key = app_name.strip().lower()
        workspace = target_path or self.settings.antigravity_workspace_default

        rustdesk_exe = next(
            (
                p
                for p in (
                    r"C:\Program Files\RustDesk\rustdesk.exe",
                    r"C:\Program Files (x86)\RustDesk\rustdesk.exe",
                )
                if Path(p).exists()
            ),
            "rustdesk",
        )

        app_map: dict[str, list[str]] = {
            "antigravity": ["cmd", "/c", "start", "", "antigravity", workspace],
            "vscode": ["cmd", "/c", "start", "", "code", workspace],
            "code": ["cmd", "/c", "start", "", "code", workspace],
            "chrome": ["cmd", "/c", "start", "", "chrome"],
            "edge": ["cmd", "/c", "start", "", "msedge"],
            "explorer": ["explorer", workspace],
            "terminal": ["cmd", "/c", "start", "", "wt", "-d", workspace],
            "rustdesk": ["cmd", "/c", "start", "", rustdesk_exe],
        }

        cmd = app_map.get(key)
        if not cmd:
            if Path(app_name).exists():
                cmd = ["cmd", "/c", "start", "", app_name]
            else:
                raise ValueError(
                    f"Aplikasi '{app_name}' tidak dikenal. Pilihan bawaan: {', '.join(app_map.keys())}"
                )

        subprocess.Popen(cmd, shell=False, cwd=workspace if Path(workspace).exists() else None)
        return {"status": "launched", "app": key, "workspace": workspace}

    def is_dangerous_command(self, command: str) -> bool:
        lowered = command.lower()
        return any(re.search(pattern, lowered) for pattern in DANGEROUS_COMMAND_PATTERNS)

    async def run_shell_command(
        self,
        command: str,
        approval_gate: ApprovalGate,
        cwd: Optional[str] = None,
        bypass_approval: bool = False,
    ) -> dict[str, Any]:
        """Execute a PowerShell command directly if safe, or queue for Boss approval if risky."""
        if not bypass_approval and self.is_dangerous_command(command):
            approval = await approval_gate.request_approval(
                action_type="pc_shell_command",
                title="Konfirmasi Perintah Terminal Berisiko",
                summary=f"Perintah membutuhkan persetujuan Boss:\n`{command}`",
                payload={"command": command, "cwd": cwd or self.settings.antigravity_workspace_default},
            )
            return {
                "status": "pending_approval",
                "approval_id": approval["id"],
                "message": "Perintah terdeteksi berisiko. Silakan klik Approve di HP/Dashboard untuk menjalankan.",
            }

        return await self.execute_shell_raw(command=command, cwd=cwd)

    async def execute_shell_raw(self, command: str, cwd: Optional[str] = None) -> dict[str, Any]:
        """Run a PowerShell command asynchronously with timeout protection."""
        work_dir = cwd if cwd and Path(cwd).exists() else self.settings.antigravity_workspace_default
        proc = await asyncio.create_subprocess_exec(
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
            cwd=work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45.0)
        except asyncio.TimeoutError:
            proc.kill()
            return {"status": "timeout", "exit_code": -1, "stdout": "", "stderr": "Command timeout (>45s)."}

        return {
            "status": "ok" if proc.returncode == 0 else "error",
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace").strip()[:4000],
            "stderr": stderr.decode("utf-8", errors="replace").strip()[:2000],
        }

    def play_pc_siren(self, repeat: int = 3) -> None:
        """Play a non-blocking Windows speaker siren as local alarm backup."""
        if os.name != "nt":
            return

        def _beep_worker() -> None:
            try:
                import winsound

                for _ in range(repeat):
                    winsound.Beep(1200, 350)
                    winsound.Beep(1600, 350)
                    time.sleep(0.15)
            except Exception as exc:
                logger.debug("winsound unavailable: %s", exc)

        threading.Thread(target=_beep_worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Zero-Install Browser Remote Mouse & Keyboard (for PC Lab Kampus / HP)
    # ------------------------------------------------------------------
    def _ensure_remote_input(self) -> None:
        if not self.settings.remote_input_enabled:
            raise PermissionError("Remote mouse/keyboard dinonaktifkan (REMOTE_INPUT_ENABLED=false).")
        if os.name != "nt":
            raise RuntimeError("Kontrol input native hanya tersedia di Windows.")

    def _get_primary_monitor_rect(self) -> tuple[int, int, int, int]:
        with mss.mss() as sct:
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            return int(mon["left"]), int(mon["top"]), int(mon["width"]), int(mon["height"])

    def perform_mouse_action(
        self,
        action: str,
        x_ratio: float = 0.5,
        y_ratio: float = 0.5,
        delta: int = 0,
    ) -> dict[str, Any]:
        """Move cursor, click, double-click, right-click, or scroll using native Win32 API."""
        self._ensure_remote_input()
        user32 = ctypes.windll.user32

        clamped_x = max(0.0, min(1.0, float(x_ratio)))
        clamped_y = max(0.0, min(1.0, float(y_ratio)))
        left, top, width, height = self._get_primary_monitor_rect()
        abs_x = left + int(clamped_x * max(1, width - 1))
        abs_y = top + int(clamped_y * max(1, height - 1))

        act = action.strip().lower()
        if act != "scroll":
            user32.SetCursorPos(abs_x, abs_y)

        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004
        MOUSEEVENTF_RIGHTDOWN = 0x0008
        MOUSEEVENTF_RIGHTUP = 0x0010
        MOUSEEVENTF_WHEEL = 0x0800

        if act == "move":
            pass
        elif act == "click":
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        elif act == "double_click":
            for _ in range(2):
                user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                time.sleep(0.06)
        elif act == "right_click":
            user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        elif act == "scroll":
            wheel_amount = int(delta) if delta else -360
            user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, wheel_amount, 0)
        else:
            raise ValueError(f"Aksi mouse tidak dikenal: {action}")

        return {"status": "ok", "action": act, "x": abs_x, "y": abs_y}

    def perform_keyboard_action(
        self,
        text: Optional[str] = None,
        hotkey: Optional[str] = None,
    ) -> dict[str, Any]:
        """Type Unicode text or trigger key combinations (e.g., ctrl+c, alt+tab, enter) on Windows."""
        self._ensure_remote_input()
        user32 = ctypes.windll.user32

        if text:
            self._send_unicode_text(user32, text[:500])
            return {"status": "ok", "typed_length": len(text[:500])}

        if hotkey:
            keys = [k.strip().lower() for k in hotkey.split("+") if k.strip()]
            vk_codes: list[int] = []
            for key in keys:
                if key in VK_MAP:
                    vk_codes.append(VK_MAP[key])
                elif len(key) == 1 and key.isalnum():
                    vk_codes.append(ord(key.upper()))
                else:
                    raise ValueError(f"Tombol tidak dikenal: {key}")

            KEYEVENTF_KEYUP = 0x0002
            for vk in vk_codes:
                user32.keybd_event(vk, 0, 0, 0)
                time.sleep(0.02)
            for vk in reversed(vk_codes):
                user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.02)
            return {"status": "ok", "hotkey": "+".join(keys)}

        raise ValueError("Isi parameter 'text' atau 'hotkey'.")

    def _send_unicode_text(self, user32: Any, text: str) -> None:
        INPUT_KEYBOARD = 1
        KEYEVENTF_UNICODE = 0x0004
        KEYEVENTF_KEYUP = 0x0002
        ULONG_PTR = ctypes.POINTER(ctypes.c_ulong)

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class _INPUTunion(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTunion)]

        for ch in text:
            if ch == "\n":
                user32.keybd_event(VK_MAP["enter"], 0, 0, 0)
                user32.keybd_event(VK_MAP["enter"], 0, KEYEVENTF_KEYUP, 0)
                continue
            code = ord(ch)
            down = INPUT(type=INPUT_KEYBOARD, union=_INPUTunion(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, None)))
            up = INPUT(
                type=INPUT_KEYBOARD,
                union=_INPUTunion(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)),
            )
            arr = (INPUT * 2)(down, up)
            user32.SendInput(2, ctypes.byref(arr), ctypes.sizeof(INPUT))
            time.sleep(0.008)

    def lock_workstation(self) -> dict[str, Any]:
        """Lock the Windows screen immediately (security action from HP or PC Lab)."""
        if os.name != "nt":
            raise RuntimeError("Lock workstation hanya tersedia di Windows.")
        ctypes.windll.user32.LockWorkStation()
        return {"status": "locked"}

    # ------------------------------------------------------------------
    # Remote Process Manager (RAM hogs) — closing always goes through Approval Gate
    # ------------------------------------------------------------------
    def _protected_pids(self) -> set[int]:
        pids = {os.getpid()}
        try:
            for parent in psutil.Process(os.getpid()).parents():
                pids.add(parent.pid)
        except psutil.Error:
            pass
        return pids

    def list_top_processes(self, limit: int = 5) -> list[dict[str, Any]]:
        """Group running processes by executable name, sorted by total RAM usage."""
        groups: dict[str, dict[str, Any]] = {}
        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                info = proc.info
                name = (info.get("name") or "").strip()
                mem = info.get("memory_info")
                if not name or mem is None:
                    continue
                group = groups.setdefault(
                    name.lower(),
                    {"name": name, "memory_mb": 0.0, "count": 0, "pids": [], "protected": False},
                )
                group["memory_mb"] += mem.rss / (1024**2)
                group["count"] += 1
                group["pids"].append(info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        protected_pids = self._protected_pids()
        result: list[dict[str, Any]] = []
        for group in groups.values():
            group["protected"] = group["name"].lower() in PROTECTED_PROCESS_NAMES or any(
                pid in protected_pids for pid in group["pids"]
            )
            group["memory_mb"] = round(group["memory_mb"], 1)
            group["pids"] = group["pids"][:12]
            result.append(group)
        result.sort(key=lambda g: g["memory_mb"], reverse=True)
        return result[: max(1, min(25, limit))]

    def resolve_close_target(self, target: str) -> dict[str, Any]:
        """Validate a close request (PID or executable name) without terminating anything."""
        cleaned = target.strip()
        if not cleaned:
            raise ValueError("Target proses kosong.")

        matches: list[tuple[int, str]] = []
        if cleaned.isdigit():
            pid = int(cleaned)
            try:
                matches.append((pid, psutil.Process(pid).name()))
            except psutil.NoSuchProcess:
                raise LookupError(f"PID {pid} tidak ditemukan.")
        else:
            needle = cleaned.lower()
            candidates = {needle, needle if needle.endswith(".exe") else f"{needle}.exe"}
            for proc in psutil.process_iter(["pid", "name"]):
                name = proc.info.get("name") or ""
                if name.lower() in candidates:
                    matches.append((proc.info["pid"], name))
            if not matches:
                raise LookupError(f"Proses '{cleaned}' tidak ditemukan.")

        protected_pids = self._protected_pids()
        for pid, name in matches:
            if pid in protected_pids or name.lower() in PROTECTED_PROCESS_NAMES:
                raise PermissionError(
                    f"Proses '{name}' (PID {pid}) dilindungi sistem/OmniPilot dan tidak boleh ditutup."
                )
        return {"name": matches[0][1], "pids": [pid for pid, _ in matches], "count": len(matches)}

    async def request_close_process(self, target: str, approval_gate: ApprovalGate) -> dict[str, Any]:
        """Queue a process close request for Boss approval."""
        info = await asyncio.to_thread(self.resolve_close_target, target)
        approval = await approval_gate.request_approval(
            action_type="close_process",
            title=f"Tutup Aplikasi: {info['name']}",
            summary=(
                f"Menutup {info['count']} proses {info['name']} (PID: {', '.join(map(str, info['pids'][:8]))}).\n"
                "Pekerjaan yang belum disimpan pada aplikasi ini bisa hilang."
            ),
            payload={"name": info["name"], "pids": info["pids"]},
        )
        return {
            "status": "pending_approval",
            "approval_id": approval["id"],
            "message": f"Permintaan menutup {info['name']} menunggu Approve dari Boss.",
        }

    def close_processes(self, pids: list[int]) -> str:
        """Terminate approved PIDs gracefully, force-killing stragglers after 5 seconds."""
        protected = self._protected_pids()
        terminated: list[psutil.Process] = []
        skipped = 0
        for pid in pids:
            if pid in protected:
                skipped += 1
                continue
            try:
                proc = psutil.Process(pid)
                if proc.name().lower() in PROTECTED_PROCESS_NAMES:
                    skipped += 1
                    continue
                proc.terminate()
                terminated.append(proc)
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied:
                skipped += 1

        _, alive = psutil.wait_procs(terminated, timeout=5)
        for proc in alive:
            try:
                proc.kill()
            except psutil.Error:
                skipped += 1
        return f"{len(terminated)} proses ditutup, {skipped} dilewati (dilindungi/akses ditolak)."
