from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class LLMProvider(str, Enum):
    GROQ = "groq"
    OPENAI = "openai"


class Settings(BaseSettings):
    telegram_bot_token: str

    # LLM provider: "groq" (default) or "openai"
    llm_provider: LLMProvider = LLMProvider.GROQ

    # Groq settings
    groq_api_key: str = ""
    groq_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    groq_transcription_model: str = "whisper-large-v3-turbo"

    # OpenAI settings (fallback)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_transcription_model: str = "whisper-1"

    vault_path: Path = Field(default=Path.home())
    authorized_users: str = ""
    bot_language: str = "es"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def authorized_user_ids(self) -> set[int]:
        if not self.authorized_users:
            return set()
        return {int(uid.strip()) for uid in self.authorized_users.split(",") if uid.strip()}

    @property
    def active_api_key(self) -> str:
        if self.llm_provider == LLMProvider.GROQ:
            return self.groq_api_key
        return self.openai_api_key

    @property
    def active_model(self) -> str:
        if self.llm_provider == LLMProvider.GROQ:
            return self.groq_model
        return self.openai_model

    @property
    def active_transcription_model(self) -> str:
        if self.llm_provider == LLMProvider.GROQ:
            return self.groq_transcription_model
        return self.openai_transcription_model

    @property
    def encounters_path(self) -> Path:
        return self.vault_path / "Encounters"

    @property
    def cards_path(self) -> Path:
        return self.vault_path / "Cards"

    @property
    def attachments_path(self) -> Path:
        return self.vault_path / "Attachments"

    @property
    def people_path(self) -> Path:
        return self.vault_path / "People"


settings = Settings()
