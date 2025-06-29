from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class BotConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    DISCORD_TOKEN: str
    GEMINI_API_KEY: str
    GEMINI_MODEL_NAME: str = Field(default="gemini-2.5-flash")
    API_CONCURRENCY: int = Field(default=5)
    # 0=思考オフ, -1=動的思考, 正の整数=トークン数
    GEMINI_THINKING_BUDGET: int = Field(default=-1)
