from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Shift Schedule API"
    app_version: str = "0.1.0"
    data_dir: Path = Path("data")
    database_filename: str = "shift_schedule.sqlite3"
    session_header_name: str = "X-Session-Token"
    default_year: int = 2026
    default_month: int = 5

    model_config = SettingsConfigDict(
        env_prefix="SHIFT_SCHEDULE_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @property
    def database_path(self) -> Path:
        return self.data_dir / self.database_filename

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


settings = Settings()
