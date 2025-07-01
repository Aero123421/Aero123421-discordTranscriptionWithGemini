from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class BotConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    DISCORD_TOKEN: str = Field(..., description="Discord Bot トークン")
    GEMINI_API_KEY: str = Field(..., description="Google Gemini API キー")
    GEMINI_MODEL_NAME: str = Field(default="gemini-1.5-flash", description="使用モデル")
    GEMINI_API_CONCURRENCY: int = Field(default=3, description="Gemini APIへの同時リクエスト数")
    LOG_LEVEL: str = Field(default="INFO", description="ログレベル")