from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://shreeji:shreeji@localhost:5432/shreeji"
    secret_key: str = "change-me"
    csrf_secret_key: str = "change-me-too"
    cookie_secure: bool = False  # set True behind HTTPS
    session_max_age: int = 60 * 60 * 12


settings = Settings()
