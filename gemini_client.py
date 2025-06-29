import asyncio
import logging
import os
from google import genai

logger = logging.getLogger(__name__)

class GeminiClient:
    def __init__(self, api_key: str, model_name: str, thinking_budget: int):
        os.environ["GEMINI_API_KEY"] = api_key
        self.client = genai.Client()
        self.model_name = model_name
        logger.info(f"Initialized GeminiClient with model {model_name}")

    async def transcribe_audio(self, audio_path: str) -> str | None:
        if not os.path.exists(audio_path):
            return None
        resp = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self.client.models.generate_content(
                model=self.model_name,
                contents=[open(audio_path, "rb")]
            )
        )
        return getattr(resp, "text", None)

    async def enhance_transcription(self, raw: str) -> str:
        resp = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self.client.models.generate_content(
                model=self.model_name,
                contents=raw
            )
        )
        return getattr(resp, "text", raw)

    async def test_connection(self) -> bool:
        resp = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self.client.models.generate_content(
                model=self.model_name,
                contents="Hello"
            )
        )
        return bool(getattr(resp, "text", None))

