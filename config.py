from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # LLM
    aws_region: str = "eu-central-1"
    llm_model_name: str = "eu.amazon.nova-micro-v1:0"
    llm_max_retries: int = 3
    llm_retry_wait_min: float = 1.0
    llm_retry_wait_max: float = 10.0

    # Gmail OAuth2
    gmail_credentials_path: Path = Path("credentials.json")
    gmail_token_path: Path = Path("token.json")
    gmail_scopes: str = "https://www.googleapis.com/auth/gmail.readonly"

    # Output
    invoice_output_dir: Path = Path("invoices")

    @property
    def gmail_scopes_list(self) -> list[str]:
        return [s.strip() for s in self.gmail_scopes.split(",")]


settings = Settings()
