"""Application settings loaded from environment / .env file."""
from pydantic import model_validator
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

    # Search (Phase 5 Stage 4: provider selection)
    # SEARCH_PROVIDER: google (default, Playwright SERP scraping fallback) |
    #                  serpapi (production API; requires SERPAPI_KEY)
    search_country_default: str = "us"
    search_max_results_default: int = 20
    search_provider: str = "google"
    serpapi_key: str = ""
    keywords_file: str = "data/keywords.txt"

    # Export
    export_dir: str = "data/exports"

    # Phase 7: Quora + SEO Authority Engine
    quora_export_dir: str = "data/quora_exports"
    seo_blog_dir: str = "data/seo_blog"

    # Phase 8: Email Discovery & Verification Engine
    email_crawler_max_pages: int = 8
    email_verify_smtp_enabled: bool = True
    email_verify_catch_all_enabled: bool = True

    # Phase 8.5: Contact Intelligence Engine
    contact_discovery_max_pages: int = 8

    # Scheduler (APScheduler)
    scheduler_enabled: bool = False
    scheduler_hour: int = 6
    scheduler_minute: int = 0
    scheduler_max_results: int = 20

    # SMTP (Phase 2.5 / Phase 4 Stage 5 outreach sending)
    # SMTP_USERNAME and SMTP_FROM_EMAIL are the canonical env names (Stage 5);
    # SMTP_USER is kept for backward compatibility and synced with SMTP_USERNAME.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True

    # IMAP (Phase 6 Stage 3 reply inbox connector) — leave blank to run the
    # in-memory mock connector (dry-run, used by tests and local dev).
    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_use_ssl: bool = True
    imap_folder: str = "INBOX"

    @model_validator(mode="after")
    def _sync_smtp_credentials(self):
        if self.smtp_username and not self.smtp_user:
            self.smtp_user = self.smtp_username
        if self.smtp_user and not self.smtp_username:
            self.smtp_username = self.smtp_user
        return self

    @property
    def sqlalchemy_database_uri(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_server}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
