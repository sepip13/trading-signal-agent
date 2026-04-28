from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str
    DATABASE_URL: str
    APP_ENV: str = "development"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "info"

    class Config:
        env_file = ".env"


settings = Settings()
