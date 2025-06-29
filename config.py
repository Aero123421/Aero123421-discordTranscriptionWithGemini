from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional

class BotConfig(BaseSettings):
    """環境変数を使用した設定管理"""

    # Discord Bot設定
    discord_token: str = Field(..., env="DISCORD_TOKEN", description="Discord Botトークン")

    # Gemini API設定
    gemini_api_key: str = Field(..., env="GEMINI_API_KEY", description="Google Gemini APIキー")
    gemini_model_name: str = Field(
        default="gemini-2.5-flash", 
        env="GEMINI_MODEL_NAME", 
        description="使用するGeminiモデル名"
    )

    # API設定
    api_concurrency: int = Field(
        default=3, 
        env="API_CONCURRENCY", 
        description="API同時実行数"
    )

    # Gemini思考機能設定（2.5 Flash用）
    gemini_thinking_budget: int = Field(
        default=-1,
        env="GEMINI_THINKING_BUDGET",
        description="Gemini思考予算 (0=思考オフ, -1=動的思考, 正の整数=トークン数)"
    )

    # 暗号化キー（設定ファイル用）
    encryption_key: Optional[str] = Field(
        default=None,
        env="ENCRYPTION_KEY",
        description="設定ファイル暗号化キー（未設定時は自動生成）"
    )

    # ログレベル
    log_level: str = Field(
        default="INFO",
        env="LOG_LEVEL",
        description="ログレベル"
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
