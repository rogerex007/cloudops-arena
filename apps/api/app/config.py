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

    dynamodb_endpoint_url: str = "http://floci:4566"
    dynamodb_region: str = "us-east-1"
    dynamodb_table_name: str = "CloudOpsArena"
    game_packs_dir: str = "/app/game-packs"
    cors_origins: str = "http://localhost:5173"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
