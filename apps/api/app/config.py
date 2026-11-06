from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "CloudOps Arena API"
    environment: str = "local"
    demo_mode: bool = True
    jwt_secret: str = "CHANGE-ME-TO-A-LONG-RANDOM-SECRET-32-CHARS"
    jwt_exp_minutes: int = 480
    admin_username: str = "admin"
    admin_password: str = "change-me-now"
    github_webhook_secret: str = ""
    github_legacy_scoring_enabled: bool = False
    github_app_config_file: str = ""
    github_app_private_key_file: str = ""
    public_base_url: str = "https://arena.costacorp.net"
    evaluation_runner_url: str = ""
    playground_manager_url: str = ""
    evaluation_runner_token_file: str = ""
    evaluation_internal_api_url: str = "http://api:8000"
    evaluation_concurrency: int = Field(default=2,ge=1,le=4)
    evaluation_queue_wait_seconds: int = Field(default=1800,ge=60,le=3600)
    evaluation_queue_limit: int = Field(default=50,ge=1,le=1000)
    actions_oidc_audience: str = "https://arena.costacorp.net"

    dynamodb_endpoint_url: str = "http://floci:4566"
    dynamodb_region: str = "us-east-1"
    dynamodb_table_name: str = "CloudOpsArena"
    game_packs_dir: str = "/app/game-packs"
    cors_origins: str = "http://localhost:5173"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
