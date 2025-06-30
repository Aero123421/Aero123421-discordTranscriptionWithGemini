import asyncio
import logging
import mimetypes
import os

from google import genai

logger = logging.getLogger(__name__)


class GeminiClient:
    """
    Google Gemini 公式 Python SDK(v0.3 以降) 用ラッパー
    """

    def __init__(self, api_key: str, model_name: str, thinking_budget: int = -1):
        os.environ["GEMINI_API_KEY"] = api_key          # SDK は環境変数でキーを読む
        self.client = genai.Client()                    # <<< 新しい初期化方法[16]
        self.model_name = model_name
        self.thinking_budget = thinking_budget
        logger.info(f"Initialized GeminiClient with model {model_name}")

    # ------------------------------------------------------------------ #
    # 音声 → 文字起こし
    # ------------------------------------------------------------------ #
    async def transcribe_audio(self, audio_path: str) -> str | None:
        if not os.path.exists(audio_path):
            logger.warning(f"Audio path not found: {audio_path}")
            return None

        # 1) 音声ファイルをアップロード（Files API）
        loop = asyncio.get_event_loop()
        uploaded_file = await loop.run_in_executor(
            None,
            lambda: self.client.files.upload(              # <<< SDK v0.3 方式[16]
                file=audio_path,
                config={"mime_type": mimetypes.guess_type(audio_path)[0] or "audio/mpeg"}
            )
        )

        # 2) transcription 用プロンプト実行
        prompt = "音声を日本語で文字起こししてください。"
        response = await loop.run_in_executor(
            None,
            lambda: self.client.models.generate_content(
                model=self.model_name,
                contents=[prompt, uploaded_file]           # ファイルをそのまま parts に渡す[16]
            )
        )

        return getattr(response, "text", None)

    # ------------------------------------------------------------------ #
    # 文字起こし結果の整形
    # ------------------------------------------------------------------ #
    async def enhance_transcription(self, raw: str) -> str:
        if not raw:
            return raw

        loop = asyncio.get_event_loop()
        instr = (
            "次のテキストは会議の文字起こしです。"
            "体裁を整えて、話者を推定・付与し、読みやすくしてください。"
        )
        response = await loop.run_in_executor(
            None,
            lambda: self.client.models.generate_content(
                model=self.model_name,
                contents=[instr, raw],
            ),
        )
        return getattr(response, "text", raw)

    # ------------------------------------------------------------------ #
    # 疎通確認
    # ------------------------------------------------------------------ #
    async def test_connection(self) -> bool:
        loop = asyncio.get_event_loop()
        try:
            resp = await loop.run_in_executor(
                None,
                lambda: self.client.models.generate_content(
                    model=self.model_name, contents="ping"
                ),
            )
            return bool(getattr(resp, "text", None))
        except Exception as e:
            logger.error(f"Gemini connection test failed: {e}")
            return False
