"""Application configuration."""

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: str = "gemini"  # "gemini" or "openai"
    openai_api_key: str = ""
    gemini_api_key: str = ""
    google_api_key: str = ""  # alias for gemini_api_key
    langchain_tracing_v2: bool = True
    langchain_project: str = "ai-job-application-assistant"
    langchain_api_key: str = ""
    langchain_endpoint: str = "https://api.smith.langchain.com"

    database_url: str = "sqlite+aiosqlite:///./data/job_assistant.db"
    resume_storage_path: str = "./storage/resumes"
    chroma_persist_dir: str = "./data/chroma"

    max_applications_per_day: int = 20
    match_threshold: int = 75
    same_company_cooldown_days: int = 30

    tavily_api_key: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    mcp_server_command: str = "python"
    mcp_server_args: str = "-m,mcp_server.server"

    embedding_model: str = "text-embedding-3-small"
    chat_model: str = "gpt-4o-mini"
    gemini_chat_model: str = "gemini-2.0-flash"
    gemini_embedding_model: str = "models/text-embedding-004"
    test_mode: bool = False

    @property
    def active_gemini_key(self) -> str:
        return self.gemini_api_key or self.google_api_key

    @property
    def is_demo_mode(self) -> bool:
        provider = self.llm_provider.lower()
        if provider == "gemini":
            return not bool(self.active_gemini_key)
        elif provider == "openai":
            return not bool(self.openai_api_key)
        return not bool(self.active_gemini_key or self.openai_api_key)

    @property
    def resume_dir(self) -> Path:
        path = Path(self.resume_storage_path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def data_dir(self) -> Path:
        path = Path("./data")
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def mcp_args_list(self) -> list[str]:
        return [a.strip() for a in self.mcp_server_args.split(",") if a.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
