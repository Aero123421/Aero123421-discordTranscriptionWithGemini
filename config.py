from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional

class BotConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Discord Bot設定
    DISCORD_TOKEN: str = Field(..., description="Discord Botトークン")

    # Gemini API設定
    GEMINI_API_KEY: str = Field(..., description="Google Gemini APIキー")
    GEMINI_MODEL_NAME: str = Field(
        default="gemini-2.5-flash", 
        description="使用するGeminiモデル名"
    )

    # API設定
    API_CONCURRENCY: int = Field(
        default=3, 
        description="API同時実行数"
    )

    # Gemini思考機能設定
    GEMINI_THINKING_BUDGET: int = Field(
        default=-1,
        description="Gemini思考予算 (0=思考オフ, -1=動的思考, 正の整数=トークン数)"
    )

    # ログレベル
    LOG_LEVEL: str = Field(
        default="INFO",
        description="ログレベル"
    )
