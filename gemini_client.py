# gemini_client.py
import asyncio
import logging
import mimetypes
import os

from google import genai

logger = logging.getLogger(__name__)

class GeminiClient:
    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash",
                 thinking_budget: int = -1):
        # 環境変数経由で API キーを設定
        os.environ["GEMINI_API_KEY"] = api_key

        self.client = genai.Client()
        self.model_name = model_name
        self.thinking_budget = thinking_budget
        logger.info(f"Initialized GeminiClient with model {model_name}")

    # ------------------------------------------------------------------
    # 音声ファイル文字起こし
    # ------------------------------------------------------------------
    async def transcribe_audio(self, audio_path: str) -> str | None:
        if not os.path.exists(audio_path):
            logger.warning(f"Audio path not found: {audio_path}")
            return None

        loop = asyncio.get_event_loop()
        mime = mimetypes.guess_type(audio_path)[0] or "audio/mpeg"

        # ① ファイルをアップロードし URI を取得
        file = await loop.run_in_executor(
            None, lambda: genai.upload_file(audio_path, mime_type=mime)
        )

        # ② アップロードが ACTIVE になるまで待機
        while True:
            meta = await loop.run_in_executor(
                None, lambda: self.client.get_file(name=file.name)
            )
            if meta.state == "ACTIVE":
                break
            await asyncio.sleep(0.4)

        # ③ file_uri / mime_type を付けて generate_content
        part = {"file_data": {"file_uri": meta.uri, "mime_type": mime}}
        resp = await loop.run_in_executor(
            None,
            lambda: self.client.models.generate_content(
                model=self.model_name,
                contents=[{"role": "user", "parts": [part]}],
            ),
        )
        return getattr(resp, "text", None)

    # ------------------------------------------------------------------
    # 文字起こし結果の整形
    # ------------------------------------------------------------------
    async def enhance_transcription(self, raw: str) -> str:
        if not raw:
            return raw

        prompt = f"以下の文字起こしテキストを読みやすく整形してください。\n\n{raw}"
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            ),
        )
        return getattr(resp, "text", raw)

    # ------------------------------------------------------------------
    # 疎通確認
    # ------------------------------------------------------------------
    async def test_connection(self) -> bool:
        loop = asyncio.get_event_loop()
        try:
            resp = await loop.run_in_executor(
                None,
                lambda: self.client.models.generate_content(
                    model=self.model_name,
                    contents="ping",
                ),
            )
            return bool(getattr(resp, "text", None))
        except Exception as e:
            logger.error(f"Gemini connection test failed: {e}")
            return False
