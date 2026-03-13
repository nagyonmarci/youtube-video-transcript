from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql://ytuser:ytpassword@localhost:5432/transcripts"
    secret_key: str = "super-secret-change-me"
    google_client_id: str = ""
    google_client_secret: str = ""
    dev_mode: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()
