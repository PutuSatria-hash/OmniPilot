"""Centralized typed configuration for OmniPilot Hub."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


def parse_csv(raw: str) -> list[str]:
    """Split a comma-separated config value into a deduplicated, ordered list."""
    result: list[str] = []
    for item in (raw or "").split(","):
        cleaned = item.strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server & Security
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8787)
    api_auth_token: str = Field(default="CHANGE_ME_GENERATE_A_SECRET_TOKEN")
    allowed_origins: str = Field(default="*")

    # AI Engine — Multi-Provider Free Waterfall (Anti-Limit / Anti-503)
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-3.5-flash-lite")
    gemini_fallback_models: str = Field(
        default="gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.5-flash,gemini-3.6-flash,gemini-3.8-flash,gemini-4-hydrogen,gemma-4-26b-a4b-it,gemma-4-31b-it"
    )

    # Provider Cadangan #2: Groq (https://console.groq.com/keys)
    groq_api_key: str = Field(default="")
    groq_models: str = Field(default="llama-3.3-70b-versatile,llama-3.1-8b-instant,qwen/qwen3-32b")
    groq_whisper_models: str = Field(default="whisper-large-v3-turbo,whisper-large-v3")

    # Provider Cadangan #3: Cerebras (https://cloud.cerebras.ai)
    cerebras_api_key: str = Field(default="")
    cerebras_models: str = Field(default="llama3.1-8b,gpt-oss-120b")

    # Provider Cadangan #4: OpenRouter :free (https://openrouter.ai/keys)
    openrouter_api_key: str = Field(default="")
    openrouter_models: str = Field(
        default="meta-llama/llama-3.3-70b-instruct:free,google/gemma-3-27b-it:free,qwen/qwen3-next-80b-a3b-instruct:free"
    )

    # Provider Cadangan #5: Mistral Free (https://console.mistral.ai/api-keys)
    mistral_api_key: str = Field(default="")
    mistral_models: str = Field(default="mistral-small-latest")

    # Provider Cadangan #6: Ollama Lokal (http://127.0.0.1:11434/v1) atau Ollama Cloud (https://ollama.com/v1)
    ollama_base_url: str = Field(default="http://127.0.0.1:11434/v1")
    ollama_api_key: str = Field(default="")
    ollama_model: str = Field(default="")

    # Memori Percakapan Multi-Turn
    chat_history_turns: int = Field(default=10, ge=0, le=40)

    # Telegram Bot
    telegram_bot_token: str = Field(default="")
    telegram_allowed_user_id: str = Field(default="")

    # Smart Escalation Alarm & Phone Heartbeat
    alarm_default_timeout_minutes: int = Field(default=5, ge=1, le=120)
    phone_inactive_threshold_minutes: int = Field(default=10, ge=1, le=240)
    pc_fallback_siren_enabled: bool = Field(default=True)

    # Laptop Health Watchdog
    health_check_interval_seconds: int = Field(default=60, ge=15, le=3600)
    health_ram_alert_percent: int = Field(default=94, ge=1, le=100)
    health_battery_alert_percent: int = Field(default=20, ge=1, le=100)
    health_disk_alert_percent: int = Field(default=95, ge=1, le=100)
    health_alert_cooldown_minutes: int = Field(default=30, ge=1, le=1440)

    # Alarm Channel A: ntfy + MacroDroid
    ntfy_server_url: str = Field(default="https://ntfy.sh")
    ntfy_topic: str = Field(default="")
    ntfy_token: str = Field(default="")
    macrodroid_webhook_url: str = Field(default="")

    # Alarm Channel B: Pushover Emergency (Priority 2)
    pushover_app_token: str = Field(default="")
    pushover_user_key: str = Field(default="")

    # Daily Schedule & Calendar
    morning_briefing_time: str = Field(default="06:30")
    timezone: str = Field(default="Asia/Makassar")
    google_calendar_ics_url: str = Field(default="")

    # Google OAuth (Gmail / Calendar / Docs)
    google_credentials_file: str = Field(default="data/google_credentials.json")
    google_token_file: str = Field(default="data/google_token.json")

    # LMS Automation
    lms_base_url: str = Field(default="")
    lms_platform: str = Field(default="moodle")
    lms_headless: bool = Field(default=False)

    # WhatsApp Safe Bridge
    whatsapp_bridge_url: str = Field(default="http://127.0.0.1:3005")
    whatsapp_enabled: bool = Field(default=False)

    # Remote Desktop Quick Links & Interactive Input
    rustdesk_pc_id: str = Field(default="")
    sunshine_host_ip: str = Field(default="")
    campus_tunnel_url: str = Field(default="")
    remote_input_enabled: bool = Field(default=True)
    antigravity_workspace_default: str = Field(default=str(BASE_DIR))

    @property
    def data_dir(self) -> Path:
        path = BASE_DIR / "data"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "omnipilot.db"

    @property
    def documents_dir(self) -> Path:
        path = BASE_DIR / "outputs" / "documents"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def screenshots_dir(self) -> Path:
        path = BASE_DIR / "outputs" / "screenshots"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def browser_profile_dir(self) -> Path:
        path = self.data_dir / "browser_profile"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def allowed_telegram_ids(self) -> set[int]:
        ids: set[int] = set()
        for raw in self.telegram_allowed_user_id.split(","):
            raw = raw.strip()
            if raw.isdigit():
                ids.add(int(raw))
        return ids


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton Settings instance."""
    return Settings()
