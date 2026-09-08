from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from the environment or a .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "rdp-relay"
    environment: str = "development"

    database_url: str = "postgresql+asyncpg://rdp:rdp_dev_pass@127.0.0.1:55433/rdp"
    redis_url: str = "redis://127.0.0.1:6379/0"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 480

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    session_code_length: int = 8

    # Persistent operational logging (Phase 6). An empty log_dir disables
    # the file and leaves only console output.
    log_dir: str = "/var/log/rmm-relay"
    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
