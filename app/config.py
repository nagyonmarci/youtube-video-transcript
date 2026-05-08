from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    secret_key: str
    google_client_id: str = ""
    google_client_secret: str = ""
    dev_mode: bool = False
    dev_auth_token: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()
