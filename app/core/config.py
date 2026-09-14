from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    cloudinary_cloud_name: str
    cloudinary_api_key: str
    cloudinary_api_secret: str

    cloudinary_temp_folder: str
    cloudinary_quarantine_folder: str
    cloudinary_review_folder: str
    cloudinary_permanent_folder: str

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()