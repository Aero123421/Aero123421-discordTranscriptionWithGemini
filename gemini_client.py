import asyncio
import logging
import mimetypes
import os

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

logger = logging.getLogger(__name__)


class GeminiClient:
    """
    Google Gemini APIラッパー
    レート制限対策（セマフォ、指数バックオフリトライ）と、
    大学の講義向けのプロンプトエンジニアリングを適用。
    """

    def __init__(self, api_key: str, model_name: str, concurrency: int = 3, max_retries: int = 5, initial_backoff: float = 2.0):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
        self.semaphore = asyncio.Semaphore(concurrency)
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        logger.info(f"Initialized GeminiClient with model {model_name}, concurrency={concurrency}, max_retries={max_retries}")

    async def _generate_with_retry(self, *args, **kwargs):
        """API呼び出しに指数バックオフリトライを適用するラッパー"""
        backoff_time = self.initial_backoff
        for i in range(self.max_retries):
            try:
                async with self.semaphore:
                    loop = asyncio.get_event_loop()
                    response = await loop.run_in_executor(
                        None,
                        lambda: self.model.generate_content(*args, **kwargs)
                    )
                    return response
            except (google_exceptions.ResourceExhausted,
                    google_exceptions.ServiceUnavailable,
                    google_exceptions.InternalServerError,
                    google_exceptions.DeadlineExceeded) as e:
                if i == self.max_retries - 1:
                    logger.error(f"Gemini API call failed after {self.max_retries} retries: {e}")
                    raise
                logger.warning(f"Gemini API call failed with {type(e).__name__}, retrying in {backoff_time:.2f} seconds... (Attempt {i + 1}/{self.max_retries})")
                await asyncio.sleep(backoff_time)
                backoff_time *= 2.0
        return None

    async def _upload_with_retry(self, *args, **kwargs):
        """ファイルアップロードに指数バックオフリトライを適用するラッパー"""
        backoff_time = self.initial_backoff
        for i in range(self.max_retries):
            try:
                loop = asyncio.get_event_loop()
                uploaded_file = await loop.run_in_executor(
                    None,
                    lambda: genai.upload_file(*args, **kwargs)
                )
                return uploaded_file
            except (google_exceptions.ResourceExhausted,
                    google_exceptions.ServiceUnavailable,
                    google_exceptions.InternalServerError,
                    google_exceptions.DeadlineExceeded) as e:
                if i == self.max_retries - 1:
                    logger.error(f"Gemini file upload failed after {self.max_retries} retries: {e}")
                    raise
                logger.warning(f"Gemini file upload failed with {type(e).__name__}, retrying in {backoff_time:.2f} seconds... (Attempt {i + 1}/{self.max_retries})")
                await asyncio.sleep(backoff_time)
                backoff_time *= 2.0
        return None

    # ------------------------------------------------------------------ #
    # 音声 → 文字起こし
    # ------------------------------------------------------------------ #
    async def transcribe_audio(self, audio_path: str) -> str | None:
        if not os.path.exists(audio_path):
            logger.warning(f"Audio path not found: {audio_path}")
            return None

        logger.info(f"Uploading audio file: {audio_path}")
        uploaded_file = None
        try:
            uploaded_file = await self._upload_with_retry(
                path=audio_path,
                mime_type=mimetypes.guess_type(audio_path)[0] or "audio/mpeg"
            )
            if not uploaded_file:
                logger.error("Failed to upload audio file.")
                return None
            logger.info(f"Audio file uploaded successfully: {uploaded_file.name}")

            prompt = '''
            以下の音声は大学の講義を録音したものです。専門用語や固有名詞が含まれる可能性があります。
            話者は主に一人の教授で、時折学生からの質問が入ります。
            以下の点に注意して、できるだけ正確に日本語で文字起こししてください。

            - 「えー」「あのー」といったフィラー（言い淀み）は除去してください。
            - 句読点を適切に使用し、読みやすい文章にしてください。
            - 話の内容が変わる部分では、適切に段落を分けてください。
            '''
            
            response = await self._generate_with_retry(
                contents=[prompt, uploaded_file]
            )
            return getattr(response, "text", None)
        except Exception as e:
            logger.error(f"Error during transcription: {e}")
            return None
        finally:
            if uploaded_file:
                logger.info(f"Deleting uploaded file: {uploaded_file.name}")
                await asyncio.to_thread(genai.delete_file, name=uploaded_file.name)
                logger.info(f"Cleaned up uploaded file: {uploaded_file.name}")

    # ------------------------------------------------------------------ #
    # 文字起こし結果の整形
    # ------------------------------------------------------------------ #
    async def enhance_transcription(self, raw: str) -> str:
        if not raw:
            return raw

        instr = '''
        以下のテキストは、大学の講義の文字起こしです。
        内容を解析し、以下の指示に従って、構造化された読みやすい議事録を作成してください。

        【指示】
        1.  **話者の特定**: 話者を「教授」「学生」として特定し、発言の前に `[教授]` や `[学生]` のように明記してください。複数の学生がいる場合、`[学生A]` `[学生B]` のように区別を試みてください。
        2.  **誤字脱字の修正**: 明らかな誤字や脱字があれば修正してください。
        3.  **構造化**: 講義の主要なトピックやセクションごとに見出しを付けてください。（例： `## 1. 今日のテーマ` `## 2. XXXの歴史的背景`）
        4.  **要点の箇条書き**: 各セクションの最後に、重要なポイントを箇条書きでまとめてください。
        5.  **全体の要約**: 最後に、講義全体の要約を3〜5行程度で記述してください。

        【文字起こしテキスト】
        '''
        
        try:
            response = await self._generate_with_retry(
                contents=[instr, raw],
            )
            return getattr(response, "text", raw)
        except Exception as e:
            logger.error(f"Error during transcription enhancement: {e}")
            return raw

    # ------------------------------------------------------------------ #
    # 疎通確認
    # ------------------------------------------------------------------ #
    async def test_connection(self) -> bool:
        try:
            response = await self._generate_with_retry(contents=["ping"])
            return bool(getattr(response, "text", None))
        except Exception as e:
            logger.error(f"Gemini connection test failed: {e}")
            return False