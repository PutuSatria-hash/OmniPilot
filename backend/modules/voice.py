"""Voice Note Transcription: Groq Whisper (gratis & cepat) dengan fallback Gemini multimodal."""

from __future__ import annotations

import asyncio
import logging

import httpx

from backend.core.config import Settings, parse_csv

logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 20 * 1024 * 1024
MIME_EXTENSIONS = {
    "audio/ogg": "ogg",
    "audio/oga": "ogg",
    "audio/opus": "opus",
    "audio/webm": "webm",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
}
TRANSCRIBE_PROMPT = (
    "Transkripsikan rekaman suara ini apa adanya ke dalam teks (umumnya bahasa Indonesia). "
    "Balas hanya dengan teks transkripnya tanpa komentar tambahan."
)


class VoiceTranscriptionService:
    """Turns Telegram voice notes / PWA recordings into text commands."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_configured(self) -> bool:
        return bool(self.settings.groq_api_key.strip() or self.settings.gemini_api_key.strip())

    async def transcribe(self, audio: bytes, mime_type: str = "audio/ogg") -> dict[str, str]:
        if not audio:
            raise ValueError("Audio kosong.")
        if len(audio) > MAX_AUDIO_BYTES:
            raise ValueError("Rekaman terlalu besar (maksimal 20 MB).")

        mime = (mime_type or "audio/ogg").split(";")[0].strip().lower()
        if mime == "video/webm":
            mime = "audio/webm"

        errors: list[str] = []
        if self.settings.groq_api_key.strip():
            for model in parse_csv(self.settings.groq_whisper_models):
                try:
                    text = await self._transcribe_groq(audio, mime, model)
                    if text:
                        return {"text": text, "provider": f"groq/{model}"}
                    errors.append(f"groq/{model}: transkrip kosong")
                except Exception as exc:
                    errors.append(f"groq/{model}: {str(exc)[:120]}")

        if self.settings.gemini_api_key.strip():
            gemini_models = [
                m
                for m in parse_csv(f"{self.settings.gemini_model},{self.settings.gemini_fallback_models}")
                if not m.lower().startswith("gemma-")
            ][:3]
            for model in gemini_models:
                try:
                    text = await self._transcribe_gemini(audio, mime, model)
                    if text:
                        return {"text": text, "provider": f"gemini/{model}"}
                    errors.append(f"gemini/{model}: transkrip kosong")
                except Exception as exc:
                    errors.append(f"gemini/{model}: {str(exc)[:120]}")

        if not errors:
            raise RuntimeError("Belum ada GROQ_API_KEY atau GEMINI_API_KEY untuk transkripsi suara.")
        raise RuntimeError(" | ".join(errors))

    async def _transcribe_groq(self, audio: bytes, mime: str, model: str) -> str:
        ext = MIME_EXTENSIONS.get(mime, "ogg")
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.settings.groq_api_key.strip()}"},
                files={"file": (f"voice.{ext}", audio, mime)},
                data={"model": model, "language": "id", "response_format": "json", "temperature": "0"},
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:150]}")
        return (resp.json().get("text") or "").strip()

    async def _transcribe_gemini(self, audio: bytes, mime: str, model: str) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=self.settings.gemini_api_key.strip(),
            http_options=types.HttpOptions(timeout=30_000, retry_options=types.HttpRetryOptions(attempts=1)),
        )

        def _call() -> str:
            resp = client.models.generate_content(
                model=model,
                contents=[types.Part.from_bytes(data=audio, mime_type=mime), TRANSCRIBE_PROMPT],
                config=types.GenerateContentConfig(temperature=0),
            )
            return (resp.text or "").strip()

        return await asyncio.to_thread(_call)
