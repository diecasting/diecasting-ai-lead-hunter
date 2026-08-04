"""Application settings loaded from environment / .env file."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Application
    app_name: str = "diecasting-ai-lead-hunter"
    debug: bool = False

    # PostgreSQL (individual parts; DATABASE_URL overrides when set)
    postgres_server: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "leadhunter"
    database_url: str = ""

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Crawler
    crawler_headless: bool = True
    crawler_max_pages: int = 50
    crawler_max_retries: int = 3
    crawler_request_timeout: int = 30000  # ms

    # Search (Google SERP)
    search_country_default: str = "us"
    search_max_results_default: int = 20
    keywords_file: str = "data/keywords.txt"

    # Export
    export_dir: str = "data/exports"

    # Scheduler (APScheduler)
    scheduler_enabled: bool = False
    scheduler_hour: int = 6
    scheduler_minute: int = 0
    scheduler_max_results: int = 20

    @property
    def sqlalchemy_database_uri(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_server}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
